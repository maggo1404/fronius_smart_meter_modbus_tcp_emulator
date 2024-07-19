#!/usr/bin/env python
"""
Simulates a Fronius Smart Meter for providing necessary 
information to inverters (e.g. Gen24). 
Necessary information is provied via MQTT and translated to MODBUS TCP

Based on
https://www.photovoltaikforum.com/thread/185108-fronius-smart-meter-tcp-protokoll

"""
###############################################################
# Import Libs
###############################################################
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock
from pymodbus.datastore import ModbusSparseDataBlock
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.transaction import ModbusRtuFramer, ModbusAsciiFramer
import threading
import struct
import time
import json
import getopt
import sys
import socket
import signal
import os

from pymodbus.server import StartTcpServer

from pymodbus.transaction import (
    ModbusAsciiFramer,
    ModbusBinaryFramer,
    ModbusSocketFramer,
    ModbusTlsFramer,
)


###############################################################
# Timer Class
###############################################################
class RepeatedTimer(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer     = None
        self.interval   = interval
        self.function   = function
        self.args       = args
        self.kwargs     = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False


###############################################################
# Configuration
###############################################################
mqttconf = {
            'username':"gas",
            'password':"gaspasswort",
            'address': "192.168.10.114",
            'port': 1883
}
MQTT_TOPIC_CONSUMPTION  = "deye/ac/active_power" #Import Watts
MQTT_TOPIC_TOTAL_IMPORT = "deye/total_energy_0" #Import Wh
MQTT_TOPIC_TOTAL_EXPORT = "deye/total_energy" #Export WH
MQTT_TOPIC_FREQ = "deye/ac/freq" #Net Freq
MQTT_TOPIC_L1_VOLT = "deye/ac/l1/voltage" #Export WH
MQTT_TOPIC_L1_CURRENT = "deye/ac/l1/current"
MQTT_TOPIC_L1_POWER = "deye/ac/l1/power"
MQTT_TOPIC_STATUS = "deye/logger_status" #Timestamp for Check MK 

corrfactor = 1 
i_corrfactor = int(corrfactor)

modbus_port = 502

###############################################################
# MQTT service
###############################################################
import paho.mqtt.client as mqtt
import paho.mqtt.subscribe as subscribe

lock = threading.Lock()

leistung = "0"
einspeisung = "0"
netzbezug = "0"
freq = "0"
l1_volt = "0"
l1_strom = "0"
l1_power = "0"
rtime = "online"


ti_int1 = "0"
ti_int2 = "0"
exp_int1 = "0"
exp_int2 = "0"
ep_int1 = "0"
ep_int2 = "0"

mqttc = mqtt.Client("SmartMeter",clean_session=False)
mqttc.username_pw_set(mqttconf['username'], mqttconf['password'])
mqttc.connect(mqttconf['address'], mqttconf['port'], 60)

mqttc.subscribe(MQTT_TOPIC_CONSUMPTION)
mqttc.subscribe(MQTT_TOPIC_TOTAL_IMPORT)
mqttc.subscribe(MQTT_TOPIC_TOTAL_EXPORT)
mqttc.subscribe(MQTT_TOPIC_STATUS)
mqttc.subscribe(MQTT_TOPIC_FREQ)
mqttc.subscribe(MQTT_TOPIC_L1_VOLT)
mqttc.subscribe(MQTT_TOPIC_L1_CURRENT)
mqttc.subscribe(MQTT_TOPIC_L1_POWER)

flag_connected = 0

def on_connect(client, userdata, flags, rc):
   global flag_connected
   flag_connected = 1
   print("MQTT connection.")


def on_disconnect(client, userdata, rc):
   global flag_connected
   flag_connected = 0
   print("Unexpected MQTT disconnection.")

mqttc.on_disconnect = on_disconnect
mqttc.on_connect = on_connect
mqttc.clean_session=False

def on_message(client, userdata, message):
    global leistung
    global einspeisung
    global netzbezug
    global rtime
    global freq
    global l1_volt
    global l1_strom
    global l1_power


    print("Received message '" + str(message.payload) + "' on topic '"
        + message.topic + "' with QoS " + str(message.qos))
    
    lock.acquire()

    if message.topic == MQTT_TOPIC_CONSUMPTION:
        if isfloat(message.payload):
            leistung = message.payload
    elif message.topic == MQTT_TOPIC_TOTAL_IMPORT:
        if isfloat(message.payload):
            netzbezug = message.payload
    elif message.topic == MQTT_TOPIC_TOTAL_EXPORT:
        if isfloat(message.payload):
            einspeisung = message.payload
    elif message.topic == MQTT_TOPIC_FREQ:
        if isfloat(message.payload):
            freq = message.payload
    elif message.topic == MQTT_TOPIC_L1_VOLT:
        if isfloat(message.payload):
            l1_volt = message.payload
    elif message.topic == MQTT_TOPIC_L1_CURRENT:
        if isfloat(message.payload):
            l1_strom = message.payload
    elif message.topic == MQTT_TOPIC_L1_POWER:
        if isfloat(message.payload):
            l1_power = message.payload
    elif message.topic == MQTT_TOPIC_STATUS:
        rtime = message.payload

    lock.release()

mqttc.on_message = on_message

mqttc.loop_start()

###############################################################
# Helper Function
###############################################################
def isfloat(num):
    try:
        float(num)
        return True
    except ValueError:
        return False

###############################################################
# Update Modbus Registers
###############################################################
def updating_writer(a_context):
    global leistung
    global einspeisung
    global netzbezug
    global rtime
    global freq
    global l1_volt
    global l1_strom
    global l1_power


    global ep_int1
    global ep_int2
    global exp_int1
    global exp_int2
    global ti_int1
    global ti_int2
    global i


    global flag_connected

    lock.acquire()
    #Considering correction factor
    print("Korrigierte Werte")

    float_netzbezug = float(netzbezug)
    netzbezug_corr = float_netzbezug*i_corrfactor
    print (netzbezug_corr)

    float_einspeisung = float(einspeisung)
    einspeisung_corr = float_einspeisung*i_corrfactor
    print (einspeisung_corr)

# freq
    float_freq = float(freq)
    print (float_freq)
    if float_freq == 0:
        freq_int1 = 0
        freq_int2 = 0
    else:
        float_freq_hex = hex(struct.unpack('<I', struct.pack('<f', float_freq))[0])
        float_freq_hex_part1 = str(float_freq_hex)[2:6] #extract first register part (hex)
        float_freq_hex_part2 = str(float_freq_hex)[6:10] #extract seconds register part (hex)
        freq_int1 = int(float_freq_hex_part1, 16) #convert hex to integer because pymodbus converts back to hex itself
        freq_int2 = int(float_freq_hex_part2, 16) #convert hex to integer because pymodbus converts back to hex itself

# l1_volt
    float_l1_volt = float(l1_volt)
    print (float_l1_volt)
    if float_l1_volt == 0:
        l1_volt_int1 = 0
        l1_volt_int2 = 0
    else:
        float_l1_volt_hex = hex(struct.unpack('<I', struct.pack('<f', float_l1_volt))[0])
        float_l1_volt_hex_part1 = str(float_l1_volt_hex)[2:6] #extract first register part (hex)
        float_l1_volt_hex_part2 = str(float_l1_volt_hex)[6:10] #extract seconds register part (hex)
        l1_volt_int1 = int(float_l1_volt_hex_part1, 16) #convert hex to integer because pymodbus converts back to hex itself
        l1_volt_int2 = int(float_l1_volt_hex_part2, 16) #convert hex to integer because pymodbus converts back to hex itself

# l1_strom
    float_l1_strom = float(l1_strom)
    print (float_l1_strom)
    if float_l1_strom == 0:
        l1_strom_int1 = 0
        l1_strom_int2 = 0
    else:
        float_l1_strom_hex = hex(struct.unpack('<I', struct.pack('<f', float_l1_strom))[0])
        float_l1_strom_hex_part1 = str(float_l1_strom_hex)[2:6] #extract first register part (hex)
        float_l1_strom_hex_part2 = str(float_l1_strom_hex)[6:10] #extract seconds register part (hex)
        l1_strom_int1 = int(float_l1_strom_hex_part1, 16) #convert hex to integer because pymodbus converts back to hex itself
        l1_strom_int2 = int(float_l1_strom_hex_part2, 16) #convert hex to integer because pymodbus converts back to hex itself

# l1_power
    float_l1_power = float(l1_power)
    print (float_l1_power)
    if float_l1_power == 0:
        l1_power_int1 = 0
        l1_power_int2 = 0
    else:
        float_l1_power_hex = hex(struct.unpack('<I', struct.pack('<f', float_l1_power))[0])
        float_l1_power_hex_part1 = str(float_l1_power_hex)[2:6] #extract first register part (hex)
        float_l1_power_hex_part2 = str(float_l1_power_hex)[6:10] #extract seconds register part (hex)
        l1_power_int1 = int(float_l1_power_hex_part1, 16) #convert hex to integer because pymodbus converts back to hex itself
        l1_power_int2 = int(float_l1_power_hex_part2, 16) #convert hex to integer because pymodbus converts back to hex itself


    #Converting current power consumption out of MQTT payload to Modbus register
    electrical_power_float = float(leistung) #extract value out of payload
    print (electrical_power_float)
    if electrical_power_float == 0:
        ep_int1 = 0
        ep_int2 = 0
    else:
        electrical_power_float = electrical_power_float * float(-1)
        electrical_power_hex = hex(struct.unpack('<I', struct.pack('<f', electrical_power_float))[0])
        electrical_power_hex_part1 = str(electrical_power_hex)[2:6] #extract first register part (hex)
        electrical_power_hex_part2 = str(electrical_power_hex)[6:10] #extract seconds register part (hex)
        ep_int1 = int(electrical_power_hex_part1, 16) #convert hex to integer because pymodbus converts back to hex itself
        ep_int2 = int(electrical_power_hex_part2, 16) #convert hex to integer because pymodbus converts back to hex itself

    #Converting total import value of smart meter out of MQTT payload into Modbus register
    total_import_float = int(netzbezug_corr)
    total_import_hex = hex(struct.unpack('<I', struct.pack('<f', total_import_float))[0])
    total_import_hex_part1 = str(total_import_hex)[2:6]
    total_import_hex_part2 = str(total_import_hex)[6:10]
    try:
        ti_int1  = int(total_import_hex_part1, 16)
    except ValueError:
        ti_int1  = 0
    try:
        ti_int2  = int(total_import_hex_part2, 16)
    except ValueError:
        ti_int2  = 0

    #Converting total export value of smart meter out of MQTT payload into Modbus register

    total_export_float = int(einspeisung_corr)
    total_export_hex = hex(struct.unpack('<I', struct.pack('<f', total_export_float))[0])
    total_export_hex_part1 = str(total_export_hex)[2:6]
    total_export_hex_part2 = str(total_export_hex)[6:10]
    try:
        exp_int1 = int(total_export_hex_part1, 16)
    except ValueError:
        ti_int1  = 0
    try:
        exp_int2 = int(total_export_hex_part2, 16)
    except ValueError:
        ti_int2  = 0

    print("updating the context")
    context = a_context[0]
    register = 3
    slave_id = 0x01
    address = 0x9C87
    values = [l1_strom_int1, l1_strom_int2,               #Ampere - AC Total Current Value [A]
              l1_strom_int1, l1_strom_int2,               #Ampere - AC Current Value L1 [A]
              0, 0,               #Ampere - AC Current Value L2 [A]
              0, 0,               #Ampere - AC Current Value L3 [A]
              l1_volt_int1, l1_volt_int2,               #Voltage - Average Phase to Neutral [V]
              l1_volt_int1, l1_volt_int2,               #Voltage - Phase L1 to Neutral [V]
              0, 0,               #Voltage - Phase L2 to Neutral [V]
              0, 0,               #Voltage - Phase L3 to Neutral [V]
              0, 0,               #Voltage - Average Phase to Phase [V]
              l1_volt_int1, l1_volt_int2,               #Voltage - Phase L1 to L2 [V]
              0, 0,               #Voltage - Phase L2 to L3 [V]
              0, 0,               #Voltage - Phase L1 to L3 [V]
              freq_int1, freq_int2,               #AC Frequency [Hz]
              ep_int1, 0,         #AC Power value (Total) [W] ==> Second hex word not needed
              l1_power_int1, 0,               #AC Power Value L1 [W]
              0, 0,               #AC Power Value L2 [W]
              0, 0,               #AC Power Value L3 [W]
              l1_power_int1, l1_power_int2,               #AC Apparent Power [VA]
              l1_power_int1, l1_power_int2,               #AC Apparent Power L1 [VA]
              0, 0,               #AC Apparent Power L2 [VA]
              0, 0,               #AC Apparent Power L3 [VA]
              0, 0,               #AC Reactive Power [VAr]
              0, 0,               #AC Reactive Power L1 [VAr]
              0, 0,               #AC Reactive Power L2 [VAr]
              0, 0,               #AC Reactive Power L3 [VAr]
              0, 0,	          #AC power factor total [cosphi]
              0, 0,               #AC power factor L1 [cosphi]
              0, 0,               #AC power factor L2 [cosphi]
              0, 0,               #AC power factor L3 [cosphi]
              exp_int1, exp_int2, #Total Watt Hours Exportet [Wh]
              0, 0,               #Watt Hours Exported L1 [Wh]
              0, 0,               #Watt Hours Exported L2 [Wh]
              0, 0,               #Watt Hours Exported L3 [Wh]
              ti_int1, ti_int2,   #Total Watt Hours Imported [Wh]
              0, 0,               #Watt Hours Imported L1 [Wh]
              0, 0,               #Watt Hours Imported L2 [Wh]
              0, 0,               #Watt Hours Imported L3 [Wh]
              0, 0,               #Total VA hours Exported [VA]
              0, 0,               #VA hours Exported L1 [VA]
              0, 0,               #VA hours Exported L2 [VA]
              0, 0,               #VA hours Exported L3 [VA]
              0, 0,               #Total VAr hours imported [VAr]
              0, 0,               #VA hours imported L1 [VAr]
              0, 0,               #VA hours imported L2 [VAr]
              0, 0                #VA hours imported L3 [VAr]
]

    context.setValues(register, address, values)
    lock.release()


###############################################################
# Config and start Modbus TCP Server
###############################################################
def run_updating_server():
    global modbus_port
    lock.acquire()
    datablock = ModbusSparseDataBlock({

        40001:  [21365, 28243],
        40003:  [1],
        40004:  [65],
        40005:  [70,114,111,110,105,117,115,0,0,0,0,0,0,0,0,0,         #Manufacturer "Fronius
                83,109,97,114,116,32,77,101,116,101,114,32,54,51,65,0, #Device Model "Smart Meter
                0,0,0,0,0,0,0,0,                                       #Options N/A
                0,0,0,0,0,0,0,0,                                       #Software Version  N/A
                48,48,48,48,48,48,48,49,0,0,0,0,0,0,0,0,               #Serial Number: 00000
                241],                                                  #Modbus TCP Address: 
        40070: [213],
        40071: [124],
        40072: [0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0,0,0,0,
                0,0,0,0],

        40196: [65535, 0],
    })

    slaveStore = ModbusSlaveContext(
            di=datablock,
            co=datablock,
            hr=datablock,
            ir=datablock,
        )

    a_context = ModbusServerContext(slaves=slaveStore, single=True)

    lock.release()

    ###############################################################
    # Run Update Register every 5 Seconds
    ###############################################################
    time = 5  # 5 seconds delay
    rt = RepeatedTimer(time, updating_writer, a_context)

    print("### start server, listening on " + str(modbus_port))
    address = ("", modbus_port)
    StartTcpServer(
            context=a_context,
            address=address,
            framer=ModbusSocketFramer,
#            allow_reuse_address=True,
        )

values_ready = False

#while not values_ready:
#      print("Warten auf Daten von MQTT Broker")
#      time.sleep(1)
#      lock.acquire()
#      if netzbezug  != '0' or einspeisung != '0':
#         print("Daten vorhanden. Starte Modbus Server")
#         values_ready = True
#      lock.release()
run_updating_server()
