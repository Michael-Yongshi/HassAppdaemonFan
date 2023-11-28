import appdaemon.plugins.hass.hassapi as hass
import datetime
import pytz
from pytz import utc

import mqttapi as mqtt

class WatchFan(mqtt.Mqtt, hass.Hass):
    """
    Assumes Fan is controlled by shelly buttons directly to work without home assistant
    This can switch the fan on (in our example a shelly 1 does this)
    and set the speed (in our example a shelly 2,5 controls the speed by setting its relays accordingly)
    
    Assumes automation in home assistant to convert a button press in an mqtt topic update
    This can be set by going to Devices, Shelly, Shelly button, automations, select click event in dropdown.
    Or add directly to yaml like below (fetch the device id from above method and selecting yaml in hamburger menu)
        - id: d3cb3d38464c49769f01481e5bda9bs
        alias: Fan Button Bathroom Single click
        trigger:
            platform: device
            device_id: 2c3fd5741bf15b6cbeff88d641bd4b52
            domain: shelly
            type: single
            subtype: button
        condition: []
        action:
            - service: mqtt.publish
            data:
                topic: fan/override/set
                payload: "1"
        mode: single

    For now this removes the need for the rpi to send proactively received overrides to home assistant via the fan/override/set topic 
    (as the button is now used to do this within HA itself and we just request speed using the get speed of flask)

    simple linking shelly button directly to plus 1
    https://www.iot-basics.net/post/building-with-shelly-buttons

    Channel 1
    http://192.168.178.139/relay/0?turn=on
    http://192.168.178.139/relay/0?turn=off

    Channel 2
    http://192.168.178.140/relay/1?turn=on
    http://192.168.178.140/relay/1?turn=off

    Channel 3
    http://192.168.178.140/relay/0?turn=on
    http://192.168.178.140/relay/0?turn=off

    more elaborate commands including roller 2.5
    https://www.reddit.com/r/ShellyUSA/comments/r51h5e/how_do_you_link_the_shelly_button1_to_other/

    shelly.click event.

    """

    # Next, we will define our initialize function, which is how AppDaemon starts our app. 
    def initialize(self):

        # Fan Fan Entities
        self.fan_channel_1 = self.args["fan_channel_1"]
        self.fan_channel_2 = self.args["fan_channel_2"]
        self.fan_channel_3 = self.args["fan_channel_3"]

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

        Checks the channels on the shellies to see which setting is currently active

        All channels off means fan off
        Only channel 1 means setting 1
        Channel 1 and 2 means setting 2
        Channel 1(, 2) and 3 means setting 3
        """

        # get hass sensor data

        fan_speed_1 = self.get_state(self.fan_channel_1)
        fan_speed_2 = self.get_state(self.fan_channel_2)
        fan_speed_3 = self.get_state(self.fan_channel_3)

        try:

            if fan_speed_1 == 'on' and fan_speed_3 == 'on':
                #[1,x,1]
                speed = 3

            elif fan_speed_1 == 'on' and fan_speed_2 == 'on':
                #[1,1,x]
                speed = 2

            elif fan_speed_1 == 'on':
                #[1,x,x]
                speed = 1

            else:
                #[x,x,x]
                speed = 0
            # logging.info(f"Read speed {speed}")

            return speed
        
        except:

            return -1

    def post_fan_speed(self, speed):

        if speed == 1:
            self.turn_on(self.fan_channel_1)
            self.turn_off(self.fan_channel_2)
            self.turn_off(self.fan_channel_3)

        elif speed == 2:
            self.turn_on(self.fan_channel_1)
            self.turn_on(self.fan_channel_2)
            self.turn_off(self.fan_channel_3)

        elif speed == 3:
            self.turn_on(self.fan_channel_1)
            self.turn_off(self.fan_channel_2)
            self.turn_on(self.fan_channel_3)

        elif speed == 0:
            self.turn_off(self.fan_channel_1)
            self.turn_off(self.fan_channel_2)
            self.turn_off(self.fan_channel_3)

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