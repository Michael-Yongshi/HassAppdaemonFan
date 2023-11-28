import appdaemon.plugins.hass.hassapi as hass
import datetime
import requests

import mqttapi as mqtt

class WatchFan(mqtt.Mqtt, hass.Hass):
    """
    Type of class:
    - Event Listener

    Method called:
    - Post to api of fan-pi to switch on ventilator with speed x
    
    Test this class by firing a test event
    -> hass web ui -> developer tools -> events -> type "FAN_OVERRIDE -> fire event

    add data like below and replace x with 0 - 3 (0 means stop override)
    {'speed': x}
    """

    # Next, we will define our initialize function, which is how AppDaemon starts our app. 
    def initialize(self):
        
        # we set some humidity limits, TODO can become MQTT settings in the future to set by the user
        self.limit3 = 95
        self.limit2 = 85

        # Were keeping track of an override variable to keep override only on for a certain amount of time
        self.override_expiration = datetime.datetime.now()
        self.override_interval = 30

        # override set topic is a queue to take commands and always gets reset back to 99 after a command is taken
        self.topic_override_set = "fan/override/set"
        # override status topic is the current status of the override
        self.topic_override_status = "fan/override/status"
        self.topic_override_timeleft = "fan/override/timeleft"

        # call a certain method when mqtt updates are available.
        self.listen_state(self.mqtt_update, "sensor.mqtt_bathroom_humidity")
        self.listen_state(self.override, "sensor.mqtt_fan_override_set")

        # enforce determining setting even if humidity is unchanged every minute
        self.run_minutely(self.determine_setting, datetime.time(0, 0, 0))

        self.determine_setting()

    # the method that is called when someone wants to override fan setting from home assistant itself
    def override(self, entity, attribute, old, new, kwargs):

        # immediately reset override command flag in mqtt to gather additional inputs
        self.mqtt_publish(topic = self.topic_override_set, payload = 99, qos = 1)

        status_new = int(new)
        status_old = int(self.get_fan_speed())

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
            self.event_happened(f"Fan override persists!")

        # check if requested to go back to automatic programming
        elif status_new == 9:

            # disable override by setting expiration to current time
            self.override_expiration = current_time
            self.mqtt_publish(topic = self.topic_override_status, payload = "Automatic Programming", qos = 1)
            self.event_happened(f"Fan override lifted!")

            # immediately run automatically setting the fan as override is stopped
            self.determine_setting(kwargs)

        # temporary override is requested. determining which type
        elif status_new in [0,1,2,3]:

            # if override is already active (and speed is the same as previous override) extend the override
            if status_new == status_old and self.override_expiration > current_time:

                # extend the override parameter
                self.override_expiration += datetime.timedelta(minutes=self.override_interval)
                pretty_time = self.pretty_time(self.override_expiration)
                self.event_happened(f"Someone requested fan override, extending the override by {self.override_interval} minutes to {pretty_time}!")

            # override is currently not active (or for a different speed) so override is set anew
            elif status_new == 0:

                # override to shut off the fan for longer period of time
                self.override_expiration = current_time + datetime.timedelta(days=1)
                self.post_fan_speed(status_new)
                pretty_time = self.pretty_time(self.override_expiration)
                self.event_happened(f"Someone requested stopping the fan, shutting off the fan until {pretty_time}!")

            else:
                # new override
                self.override_expiration = current_time + datetime.timedelta(minutes=self.override_interval)
                self.post_fan_speed(status_new)
                pretty_time = self.pretty_time(self.override_expiration)
                self.event_happened(f"Someone requested fan override, setting speed {status_old} => {status_new} until {pretty_time}!")
            
            # publish override to MQTT
            time_left = self.time_left()
            self.mqtt_publish(topic = self.topic_override_status, payload = "Temporary Override", qos = 1)
            self.mqtt_publish(topic = self.topic_override_timeleft, payload = f"{time_left}", qos = 1)

        else:
            self.log(f"Error, no valid input received: {status_new}")

        self.log(f"Current date and time is: {current_time}")

    # determine setting when humidity changed
    def mqtt_update(self, entity, attribute, old, new, kwargs):

        self.determine_setting(kwargs)

    # determining the setting for the fan based on humidity and override expiration
    def determine_setting(self, kwargs):

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

        # Collect requested settings
        settings = []
        settings += [self.determine_time()]
        # settings += [self.determine_humidity()]
        # settings += [self.determine_cooling()]

        # retrieve highest setting from the array (sort and get last element)
        new_speed = sorted(settings)[-1]

        if current_speed != new_speed:
            self.event_happened(f"Setting fan speed to {new_speed}!")
            self.post_fan_speed(new_speed)

    def get_fan_speed(self):
        """
        get the current speed of the fan
        """

        # get hass sensor data
        current_speed = int(self.get_state("sensor.mqtt_fan_status"))

        return current_speed

    def post_fan_speed(self, speed):

        self.mqtt_publish(topic = "fan/set", payload = speed, qos = 1)

    def determine_time(self):
        """
        Requests a setting to shut off in the evening when all the hearths are spreading smoke in the neighborhood
        """

        current_time = datetime.datetime.now()
        evening_time = current_time.replace(hour=19, minute=0, second=0)

        if current_time > evening_time:
            setting = 0
        else:
            setting = 1

        # self.event_happened(f"Timebased program requires setting {setting}")
        return setting

    def determine_humidity(self):
        """
        Requests a setting to exhaust moisture
        """

        # humidity level (try block as sensor can be down)
        try:
            humidity = float(self.get_state("sensor.mqtt_bathroom_humidity"))
        
            self.log(f"Measured humidity at {humidity}%!")

            # set to 3 if humidity increased to above limit3
            if humidity >= self.limit3:
                setting = 3
                self.log(f"level above {self.limit3}%  observed!")
            
            # set to 2 if humidity is above limit2
            elif humidity >= self.limit2:
                setting = 2
                self.log(f"level above {self.limit2}%, but below {self.limit3}, observed!")

            # set to 1 if humidity is below limit2
            elif humidity < self.limit2:
                setting = 1
                self.log(f"level below {self.limit2}% observed!")

        # if sensor is down, return fan to lowest setting
        except:
            setting = 1
            self.log(f"Couldn't observe humidity!")
        
        return setting
    
    def determine_cooling(self):
        """
        Requests a higher setting in order to cool
        """

        try:
            comfort_temp = 12
            inside_temp = float(self.get_state("sensor.mqtt_living_temperature"))
            outside_temp = float(self.get_state(entity_id="weather.serenity", attribute="temperature"))
            self.log(f"Inside temperature is {inside_temp} versus outside temperature of {outside_temp}")

            if inside_temp > 23:
                self.log(f"Inside temperature is high")
                if inside_temp > outside_temp:
                    setting = 2
                    self.log(f"Outside temperature is low enough to cool!")
                else:
                    setting = 1
                    self.log(f"Outside temperature is too high!")
            else:
                setting = 1
                self.log(f"Inside temperature reached target")

        except:
            setting = 1
            self.log(f"Couldn't observe temperature!")

        return setting


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

    def event_happened(self, message):
        """
        the method that is called when an event happens
        """

        # log the message before sending it
        self.log(message)

        # Call telegram message service to send the message from the telegram bot
        self.call_service(
            "telegram_bot/send_message", message=message,
        )