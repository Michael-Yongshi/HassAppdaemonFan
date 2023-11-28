/*
Connects with wifi
Connects with MQTT

Waits for mqtt message command to set fan speed
Sends MQTT message of the fan speed
 */

///////////////////////////////////////////////////////////////////////////////////////////
// Libraries
///////////////////////////////////////////////////////////////////////////////////////////
#include "secrets.h" 

////////////// Wifi
#include <SPI.h>
#include <WiFiNINA.h>

////////////// MQTT
#include <PubSubClient.h>

///////////////////////////////////////////////////////////////////////////////////////////
// Constants
///////////////////////////////////////////////////////////////////////////////////////////

////////////// Wifi
const char ssid[] = SECRET_WIFI_SSID;        // your network SSID (name)
const char pass[] = SECRET_WIFI_PASS;    // your network password (use for WPA, or use as key for WEP)
int status = WL_IDLE_STATUS;     // the WiFi radio's status

////////////// MQTT
const char mqtt_broker[] = SECRET_MQTT_BROKER;
const int mqtt_port = 1883;

const char mqtt_user[] = SECRET_MQTT_USER;
const char mqtt_password[] = SECRET_MQTT_PASS;

const char outTopicFan[] = "fan/speed";
const char inTopicFan[] = "fan/set";
const char testTopic[] = "test";

////////////// Pins
const int outPin1 = 4;
const int outPin2 = 7;
const int outPin3 = 8;

///////////////////////////////////////////////////////////////////////////////////////////
// Global Variables
///////////////////////////////////////////////////////////////////////////////////////////

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

int current_speed = 1;
int set_speed = 1;

///////////////////////////////////////////////////////////////////////////////////////////
// Functions
///////////////////////////////////////////////////////////////////////////////////////////

void mqtt_callback(char* topic, byte* payload, unsigned int length) {

  Serial.print("Message arrived on Topic:");
  Serial.println(topic); 
  Serial.print("Raw Payload: ");
  Serial.println((char *)payload);
  
  Serial.print("String Payload: ");
  payload[length] = 0; // this is needed to signal the end of a char string, which a mqtt message often is
  char* charPayload = (char *)payload;
  String strPayload = String(charPayload);
  Serial.println(strPayload);

  Serial.print("Integer Payload: ");
  int intPayload = strPayload.toInt();
  Serial.println(intPayload);
  
  if  (intPayload >= 0 && intPayload <= 3) {
    set_speed = intPayload;
  } else {
  Serial.println("Error, received unexpected value!");
  }

  mqttClient.publish(testTopic, "test of ard_fan");

}

///////////////////////////////////////////////////////////////////////////////////////////
// Set up
///////////////////////////////////////////////////////////////////////////////////////////
void setup() {

  //Initialize serial:
  Serial.begin(9600);


  ////////////// Wifi 
  // check for the WiFi module:
  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("Communication with WiFi module failed!");
    // don't continue
    while (true);
  }

  String fv = WiFi.firmwareVersion();
  if (fv < WIFI_FIRMWARE_LATEST_VERSION) {
    Serial.println("Please upgrade the firmware");
  }
 
  // set hostname
  WiFi.setHostname("ard-fan");
  
  // attempt to connect to WiFi network:
  while (status != WL_CONNECTED) {
    Serial.print("Attempting to connect to WPA SSID: ");
    Serial.println(ssid);
    // Connect to WPA/WPA2 network:
    status = WiFi.begin(ssid, pass);

    // wait 10 seconds for connection:
    delay(10000);
  }

  // you're connected now, so print out the data:
  Serial.println("You're connected to the network");

  
  ////////////// MQTT
  mqttClient.setServer(mqtt_broker, mqtt_port);
  mqttClient.setCallback(mqtt_callback);
  mqttClient.connect("Arduino_Fan", mqtt_user, mqtt_password);

  if (mqttClient.connected()) {
    Serial.println("MQTT connection established!");
  }
  else {
    Serial.println("MQTT connection failed! Error code = ");
  }

  bool result = mqttClient.subscribe(inTopicFan);
  Serial.println(result);

  // Pins for relays
  pinMode(outPin1, OUTPUT);
  pinMode(outPin2, OUTPUT);
  pinMode(outPin3, OUTPUT);

  Serial.println("Set up completed!");

}


///////////////////////////////////////////////////////////////////////////////////////////
// Loop
///////////////////////////////////////////////////////////////////////////////////////////
void loop() {

//  if (!mqttClient.connected()) {
//    reconnect();
//  }
  mqttClient.loop();

  // set speed according to received mqtt message

  if (!current_speed == set_speed) {
    if (set_speed == 1) {
    Serial.println("Set fan to low!");
    digitalWrite(outPin1,HIGH);
    digitalWrite(outPin2,LOW);
    digitalWrite(outPin3,LOW);
    } else if (set_speed == 2) {
    Serial.println("Set fan to medium!");
    digitalWrite(outPin1,HIGH);
    digitalWrite(outPin2,HIGH);
    digitalWrite(outPin3,LOW);
    } else if (set_speed == 3) {
    Serial.println("Set fan to high!");
    digitalWrite(outPin1,HIGH);
    digitalWrite(outPin2,HIGH);
    digitalWrite(outPin3,HIGH);
    } else if (set_speed == 0) {
    Serial.println("Turn fan off!");
    digitalWrite(outPin1,LOW);
    digitalWrite(outPin2,LOW);
    digitalWrite(outPin3,LOW);
    }
 
    current_speed = set_speed;
  }
  
}
