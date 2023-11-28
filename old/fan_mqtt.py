import logging
import time

from paho.mqtt import client as mqtt_client

from fan import Fan

# fan
fan = Fan()

# MQTT stuff
broker = '192.168.178.37'
port = 1883
client_id = 'rpi-fan-pymqtt'
username = "mqttpublisher"
password = "publishmqtt"

def run():

    # set up logging
    logging.basicConfig(level=logging.DEBUG)

    # set up mqtt client
    client = connect_mqtt()

    # start loop, this will process the actual collection and sending of the messages
    client.loop_start()

    # publish sensor data every second    
    msg_count = 0
    
    while True:
        # every second
        time.sleep(1)
        
        topic = "fan/speed"

        # get fan speed
        value = fan.get_speed()

        # publish
        publish(client, topic, value)

        # finish off with adding to the message count
        msg_count += 1

def connect_mqtt():

    def on_connect(client, userdata, flags, rc):

        if rc == 0:
            logging.info("Connected to MQTT Broker!")
        else:
            logging.critical("Failed to connect, return code %d\n", rc)

    # Set Connecting Client ID
    client = mqtt_client.Client(client_id)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.connect(broker, port)

    return client

def publish(client, topic, value):

        # publish it
        result = client.publish(topic, value)

        # first item in result array is the status, if this is 0 then the packet is send succesfully
        if result[0] == 0:
            logging.info(f"Send `{value}` to topic `{topic}`")
        
        # if not the message sending failed
        else:
            logging.critical(f"Failed to send message to topic {topic}")


if __name__ == '__main__':
    run()
