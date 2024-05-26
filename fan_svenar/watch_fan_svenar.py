import appdaemon.plugins.hass.hassapi as hass
import datetime
import pytz
from pytz import utc

import mqttapi as mqtt

class WatchFan(mqtt.Mqtt, hass.Hass):
    """
    Assumes Fan is controlled by Svenars ESPHome
    This can read massive amounts of data of the comfoair / whr930, in addition to being able to set some settings, e.g. fan mode and speeds.
    
    Assumes automation in home assistant to convert a climate service call in an mqtt topic update
    """

    # Next, we will define our initialize function, which is how AppDaemon starts our app. 
    def initialize(self):

        # Fan climate Entity
        self.climate_entity = self.args["climate_comfoair"]
        self.sensor_status = self.args["sensor_status"]

        ###### User program

        # Toggle to turn programming on or off
        self.toggle = self.args["toggle"]

        # helper format
        helper_type_speed = "input_number."
        helper_type_end = "input_datetime."
        self.helper_speed = helper_type_speed + "fan_speed_"
        self.helper_end = helper_type_end + "fan_timeslot_"
        self.timeslotcategories = self.args["timeslots"]

        # variables to watch with initial value
        self.current_program = self.set_program()


        ###### Override method: Complex
        # get interval setting from a helper
        self.set_override_interval = self.args["interval"]

        # variable to watch with initial value
        self.override_expiration = datetime.datetime.now()

        # keep track of timeslot and override request
        self.last_timeslot_end = 0
        self.last_override_status = 9

        # Sensor and topic for override requests
        self.sensor_override_set_with = self.args["sensor_override_with"]
        self.sensor_override_set_without = self.args["sensor_override_without"]
        self.topic_override_set_with = self.args["topic_override_with"]
        self.topic_override_set_without = self.args["topic_override_without"]

        # Topics to push info into only
        self.topic_override_status = self.args["topic_override_status"]
        self.topic_override_timeleft = self.args["topic_override_time"]

        """
        Callback runs to watch for overrides depending if speed still needs to be set or not
        """
        self.listen_state(self.override_with_command, self.sensor_override_set_with)
        self.listen_state(self.override_without_command, self.sensor_override_set_without)

        """
        Following call runs every minute to check if something needs to happen
        """
        self.run_minutely(self.determine_setting, datetime.time(0, 0, 0))

        self.determine_setting(kwargs=None)

    def override_with_command(self, entity, attribute, old, new, kwargs):
        """
        the method that is called to register override usage AND set the requested speed
        """

        self.override(new=new, command=True)

        # immediately reset override command flag in mqtt to gather additional inputs
        self.mqtt_publish(topic = self.topic_override_set_with, payload = 99, qos = 1)

    def override_without_command(self, entity, attribute, old, new, kwargs):
        """
        the method that is called to register override usage when speed has already been set directly
        """

        self.override(new=new, command=False)

        # immediately reset override command flag in mqtt to gather additional inputs
        self.mqtt_publish(topic = self.topic_override_set_without, payload = 99, qos = 1)

    def override(self, new, command, status_old=""):
        """
        the method that is called to register override usage
        """

        status_new = int(new)

        current_time = datetime.datetime.now()

        # disregard a reset of the override command topic to value 99
        if status_new == 99:

            # disregard
            return

        # persistent override is requested
        elif status_new == 8:

            # no override expiration
            self.override_expiration = datetime.datetime(9999, 1, 1)
            self.mqtt_publish(topic = self.topic_override_status, payload = "Persistent Override", qos = 1)
            self.last_override_status = status_new
            self.event_happened(f"Fan override persists!")

        # check if requested to go back to automatic programming
        elif status_new == 9:

            # disable override by setting expiration to current time
            self.override_expiration = current_time
            self.mqtt_publish(topic = self.topic_override_status, payload = "Automatic Programming", qos = 1)
            self.last_override_status = 9
            self.event_happened(f"Fan override lifted!")

            # immediately run automatically setting the fan as override is stopped
            self.determine_setting(kwargs=None)

        # temporary override is requested. determining which type
        elif status_new in [0,1,2,3]:

            override_interval_raw = self.get_state(self.set_override_interval)
            override_interval = int(override_interval_raw.split('.')[0])

            # if override is already active (and speed is the same as previous override) extend the override
            if status_new == self.last_override_status and self.override_expiration > current_time:

                # extend the override parameter
                self.override_expiration += datetime.timedelta(minutes=override_interval)
                pretty_time = self.pretty_time(self.override_expiration)
                self.event_happened(f"Someone requested fan override, extending the override by {override_interval} minutes to {pretty_time}!")

            # override is currently not active (or for a different speed) so override is set anew
            else:

                self.override_expiration = current_time + datetime.timedelta(minutes=override_interval)
                pretty_time = self.pretty_time(self.override_expiration)
                self.event_happened(f"Someone requested fan override, setting speed {status_old} => {status_new} until {pretty_time}!")
            
                if command == True:
                    self.post_fan_speed(status_new)

            # publish override to MQTT
            time_left = self.time_left()
            self.mqtt_publish(topic = self.topic_override_status, payload = "Temporary Override", qos = 1)
            self.mqtt_publish(topic = self.topic_override_timeleft, payload = f"{time_left}", qos = 1)

            # remember last override request
            self.last_override_status = status_new

        else:
            self.log(f"Error, no valid input received: {status_new}")

        self.log(f"Current date and time is: {current_time}")

    def determine_setting(self, kwargs):
        """
        Check logic to see if target speed should change on the thermostat
        """

        if self.get_state(self.toggle) != "on":
            return

        # get fanspeed state
        current_speed = self.get_fan_speed()
        # self.log(f"Fan speed is {current_speed}")

        current_time = datetime.datetime.now()

        # check if override is active
        if self.override_expiration >= current_time:

            # publish override to MQTT
            time_left = self.time_left()
            self.mqtt_publish(topic = self.topic_override_timeleft, payload = f"{time_left}", qos = 1)

            return

        else:
            # make sure override status is on auto
            self.mqtt_publish(topic = self.topic_override_status, payload = "Automatic programming", qos = 1)



        # reload user determined program
        self.current_program = self.set_program()

        # get current and target values
        current_timeslot = self.get_current_timeslot(current_time)
        current_timeslot_end = current_timeslot["end"]
        program_target = current_timeslot["speed"]
        # self.log(f"Programming target speed is {program_target}, while current target speed is {current_speed}")

        # check if we already programmed this timeslot before (we will only once, so user can still change it)
        if self.last_timeslot_end != current_timeslot_end:

            # register that we now programmed this timeslot
            self.last_timeslot_end = current_timeslot_end

        # only set new speed if its different
        if program_target != current_speed:
            # set new target speed
            self.post_fan_speed(speed=program_target)
            self.event_happened(f"Set new fan speed to {program_target}, according to the program")

        else:
            # self.event_happened(f"Target fan speed is already set correctly to {program_target}")
            pass

    def get_current_timeslot(self, current_time):
        """
        Current timeslot is calculated as follows

        Iterate over the timeslots in the current program (start with morning and ending with night)
        check if current time is before the end of the timeslot
        if so this timeslot is the active timeslot
        """

        # get current time parameters
        current_year = current_time.year
        current_month = current_time.month
        current_day = current_time.day

        for timeslot in self.current_program:
            timeslot_end = timeslot["end"]

            # Convert timeslot 'end' to time type
            timeslot_end_str = datetime.datetime.strptime(timeslot_end, "%H:%M:%S")
            timeslot_end_dt = timeslot_end_str.replace(year=current_year, month=current_month, day=current_day)

            # check if current time still falls within this timeslot
            if current_time <= timeslot_end_dt:

                # set as current timeslot
                current_timeslot = timeslot
                break

        return current_timeslot

    def set_program(self):

        user_program = []

        # Iterate over user settings
        for category in self.timeslotcategories:

            # get user settings for this time of day
            timeslot_sensor = self.helper_end + category
            timeslotend = self.get_state(timeslot_sensor)
            # self.event_happened(f"timeslot sensor is {timeslot_sensor} with value {timeslotend}")

            speed_sensor = self.helper_speed + category
            speed_string = self.get_state(speed_sensor)
            speed = int(speed_string[0])
            # self.event_happened(f'speed sensor is {speed_sensor} with value {speed}')

            timeslotdict = {
                "end": timeslotend,
                "speed": speed,
            }

            user_program += [timeslotdict]
            # self.event_happened(f"Added timeslot {category} as {timeslotdict}!")

        program = user_program
        # self.event_happened(f"Set user program!")

        # add last timeslot until midnight and use the first timeslot as speed
        timeslotdict = {
            "end": "23:59:59",
            "speed": program[0]["speed"],
        }
        program += [timeslotdict]

        return program

    def time_left(self):

        current_time = datetime.datetime.now()

        time_left_delta = self.override_expiration - current_time
        time_left_str = self.pretty_time_delta(time_left_delta.total_seconds())

        return time_left_str

    def pretty_time(self, datetime):

        # Format datetime string
        pretty_t = datetime.strftime("%H:%M")

        return pretty_t

    def pretty_time_delta(self, seconds):

        seconds = int(seconds)
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)

        if days > 0:
            return f"{days}d" #{hours}h {minutes}m {seconds}s"
        elif hours > 0:
            return f"{hours}h" #{minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m" #{seconds}s"
        else:
            return f"{seconds}s"

    def get_fan_speed(self):
        """
        Check the current status of the ventilation speeds and returns result
        """

        # get hass sensor data

        speed = self.get_state(self.sensor_status)
        
        return speed

    def post_fan_speed(self, speed):

        fan_dict = {'0':'off', '1':'low', '2':"medium", '3':"high"}
        fan_speed = fan_dict[str(speed)]

        self.call_service("climate/set_fan_mode", entity_id = self.climate_entity, fan_mode = fan_speed)

    def event_happened(self, message):
        """
        the method that is called when an event happens
        """

        # log the message before sending it
        self.log(message)

        # Call telegram message service to send the message from the telegram bot
        # self.call_service(
        #     "telegram_bot/send_message", message=message, target=f"'{self.telegram_id}'"
        # )

        self.call_service(
            f'notify/telegram_log', title="", message=message)