import serial
import time

port = "/dev/ttyUSB1"

ser = serial.Serial(port, 9600, timeout=1)
ser.close()
ser.open()
ser.write(str.encode('ati'))
time.sleep(3)
read_val = ser.read(size=64)
print(read_val)
