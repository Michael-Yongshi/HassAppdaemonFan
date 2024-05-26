# HassAppdeamonFan

## fan_shellies

Home Assistant code to schedule fan with override function in Appdeamon integration (Python) based on switching Shelly relays. It depends on the MQTT integration in Hass for setting some override topics. 

## fan_svenar

Home Assistant code to schedule fan with override function in Appdeamon integration (Python) based on Svenars ESPHome integration 'ESPcomfoair' (https://github.com/Mosibi/whr_930). It depends on the MQTT integration in Hass for setting some override topics. 


## automations

Overrides can be arranged using a 'with' or 'without' MQTT topic. This discerns situations where a command may already have gone to the shellies and this code only needs to account for managing override settings. Using the 'with' command it will in addition also send the associated command to the shellies (thus assuming this isn't already done)

# Installation

Only the logic in the 'fan_shellies' folder is extensively tested (n=2) and is running bugfree for some time now at two locations.

# Other code to reuse

Code can be reused to switch other types of processing fan commands, i.e. based on an RPI with 3 relays or an arduino. Some example code can be foundin the 'old' directory that can be used as inspiration. 

Most bugs within the logic were concerning time and timezones, modify with this in mind when forking this repo and using the files in the 'old' folder.
