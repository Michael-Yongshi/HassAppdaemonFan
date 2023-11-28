"""
A fan object that manipulates three relays to set fan speeds or turn it on/off

MQTT
Watches for MQTT messages on a broker so it can be controlled by smart logic, based on sensor data.
Sends MQTT messages back to the broker of status and availability

Flask API
Flask API is used so it can be controlled directly by buttons. This will keep working if the assistant or MQTT broker is offline
If a command is directly send over the Flask API it will send a MQTT override set message so the assistant is notified about it
Otherwise the assistant may incur a different setting, overriding the users manual action.
"""

import os
import json
import time
import logging
import threading

from flask import Flask, request
from paho.mqtt import client as mqtt_client
import gpiozero

# set up logging
logging.basicConfig(level=logging.DEBUG)

### Physical interface with the Fan
class Fan(object):
    """
    Provdes methods to interface with the physical fan connections
    """

    def __init__(self):
        """
        Default fans (in NL) work on a 3 input basis, which means it expects a combination of power on L1, L2 and L3.
        You can find often a switch in the kitchen and/or living room to control it. from those switches the Lx cables run to the fan

        L1:                 lowest speed (1)
        L1 and L2:          medium speed (2)
        L1(, L2) and L3:    highest speed (3)

        (some devices have high and medium inverted)
        """

        # Use active_high to invert the relay
        self.channel1 = gpiozero.OutputDevice(pin=26, active_high=False)
        self.channel2 = gpiozero.OutputDevice(pin=20, active_high=False)
        self.channel3 = gpiozero.OutputDevice(pin=21, active_high=False)

    def get_speed(self):
        """
        Check the current status of the ventilation speeds and returns result

        Checks the channels on GPIO to see which setting is currently active

        All channels off means fan off
        Only channel 1 means setting 1
        Channel 1 and 2 means setting 2
        Channel 1(, 2) and 3 means setting 3
        """

        try:
            #[1,x,1]
            print(self.channel1.value)
            print(self.channel2.value)
            print(self.channel3.value)

            if self.channel1.value == 1 and self.channel3.value == 1:
                #[1,x,1]
                speed = 3

            elif self.channel1.value == 1 and self.channel2.value == 1:
                #[1,1,x]
                speed = 2

            elif self.channel1.value == 1:
                #[1,x,x]
                speed = 1

            else:
                #[x,x,x]
                speed = 0
            # logging.info(f"Read speed {speed}")

            return speed

        except:
            logging.error(f"Couldn't read speed!")

            return -1

    def set_speed(self, speed):

        try:

            logging.info(f"Setting speed to {speed}")
            if speed == 0:
                self.channel1.off()
                self.channel2.off()
                self.channel3.off()

            elif speed == 1:
                self.channel1.on()
                self.channel2.off()
                self.channel3.off()

            elif speed == 2:
                self.channel1.on()
                self.channel2.on()
                self.channel3.off()

            elif speed == 3:
                self.channel1.on()
                self.channel2.off()
                self.channel3.on()
            
            else:
                logging.info(f"Received invalid speed {speed}.")

                return speed
            
            logging.info(f"Set speed to {speed}!")

            # Wait for fan to process the change before accepting a new change
            time.sleep(1)

            return speed
        
        except:

            logging.info(f"Couldnt set speed {speed}.")
            return -1
fan = Fan()

### MQTT
command_topic = "fan/set"
state_topic = "fan/speed"
avail_topic = "fan/availability"
topic_override_set = "fan/override/set"

client_id = 'rpi-fan-pymqtt'
client = mqtt_client.Client(client_id)

def on_connect(client, userdata, flags, rc):
    """
    Callback thats run whenever the device reconnects to the MQTT broker
    """
    
    if rc == 0:
        # if rc is 0 then it connected without error
        logging.debug("Connected to MQTT Broker!")

        # subscribe on topics when connected
        client.subscribe(command_topic)

    else:
        logging.critical("Failed to connect, return code %d\n", rc)
def on_message(client, userdata, message):
    """
    Callback thats run whenever the device receives a message from the MQTT broker
    This is run from the thread that is running the loop, so it will work even though the main thread is blocked by sending of sensor data in a while loop.
    """
    payload = int(message.payload.decode("utf-8"))
    logging.debug(f"received message = {payload}")

    # send to the fan
    result = fan.set_speed(payload)
client.on_connect = on_connect
client.on_message = on_message

def mqtt_broker_login_from_json(client):
    """
    Load mqtt broker details from json located in users home directory
    """

    userpath = os.path.expanduser('~')
    complete_path = os.path.join(userpath, "mqtt.json")

    # open json and return as an array
    with open(complete_path, 'r') as infile:
        json_contents = json.load(infile)

    # MQTT Broker
    client.username_pw_set(
        username=json_contents["username"],
        password=json_contents["password"]
        )
    client.connect(
        host=json_contents["broker"],
        port=json_contents["port"]
        )

    return client
client = mqtt_broker_login_from_json(client)

def publish(client, topic, value):
    """
    Publish a result to the MQTT broker and log if it went successfull
    """

    # publish it
    result = client.publish(topic, value)

    # first item in result array is the status, if this is 0 then the packet is send succesfully
    if result[0] == 0:
        # logging.debug(f"Send `{value}` to topic `{topic}`")
        pass

    # if not the message sending failed
    else:
        logging.critical(f"Failed to send message to topic {topic}")

### Flask
host = '0.0.0.0'
port = 5000
app = Flask(__name__)
def start_flask():
    app.run(host=host, port=port, debug=False, use_reloader=False)

@app.route('/set_speed', methods=['GET'])
def set_speed():
    """
    Sets speed, expects input between 0 - 3. 
    It will request fan object to trigger the new speed 
    opens up flask to receive non-manual signals from other sources

    :param string or int speed:
    :return string result:

    ------------------------------------------

    Flask set to port 5000 and device currently on internal ip 192.168.178.29

    example commands

    Speed 0-3
    > http://192.168.178.29:5000/set_speed?speed=0 # off
    > http://192.168.178.29:5000/set_speed?speed=1
    > http://192.168.178.29:5000/set_speed?speed=2
    > http://192.168.178.29:5000/set_speed?speed=3

    """

    logging.critical(f"Received http request {request.args}")

    # get arguments from a get request
    speed = int(request.args.get('speed'))

    if speed in [0, 1, 2, 3]:

        logging.critical(f"http set speed to {speed}")

        # first set speed directly in case assistant is down
        result = fan.set_speed(speed)

        # only now give command to hass that a manual override is requested
        publish(client=client, topic=topic_override_set, value=speed)

    # returns the current speed
    return f"Speed is set to {result}"

def run():
    """
    The main process to set up Flask and MQTT loop
    """

    # run flask in a seperate thread so it doesnt block mqtt and other code
    thread = threading.Thread(target=start_flask)
    thread.start()

    # start loop that will process the actual collection and sending of the messages continuously in a seperate thread
    client.loop_start()

    # loop to publish sensor data
    msg_count = 0
    while True:

        # every second
        time.sleep(1)

        # publish
        publish(client=client, topic=state_topic, value=fan.get_speed())
        publish(client=client, topic=avail_topic, value="online")

        # finish off with adding to the message count
        msg_count += 1


if __name__ == '__main__':

    run()