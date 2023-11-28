
from flask import Flask, request

from fan import Fan

# fan
fan = Fan()

# run flask
app = Flask(__name__)

# Define GET requests
@app.route('/get_speed', methods=['GET'])
def get_speed():
    """
    Check the current status of the ventilation speeds and returns result
    """

    speed = fan.get_speed()

    # returns the current speed
    return str(speed)

# Define POST requests
@app.route('/post_speed', methods=['POST'])
def post_speed():
    """
    Sets speed, expects input between 0 - 3
    
    :param string speed:

    :return string result:

    Code to set the speed of the fan by setting the two relays through GPIO output channels in a certain combination
    
    All channels off means fan off
    Only channel 1 means setting 1
    Channel 1 and 2 means setting 2
    Channel 1 and 3 means setting 3

    Always all channels are set, even if its not strictly necessary 
    i.e. switching from setting 1 to 3 could be done by just setting channel 3, 
    but lets make sure the other channels are forced to the correct channel either way is off just in case
    """

    # get parameters from arguments in the api call
    json = request.get_json()

    # make sure its a valid integer
    speed=int(json["speed"])

    result = fan.set_speed(speed)

    # returns the current speed
    return f"Speed is set to {result}"

if __name__ == '__main__':

    host = '0.0.0.0'
    port = 5000

    app.run(debug = False, host=host, port=port)
