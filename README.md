# fronius_smart_meter_modbus_tcp_emulator
Emulate a Fronius  Modbus TCP Smart Meter 

Code is under develoment!

Just enter MQTT server data and send CONSUMPTION, TOTAL_IMPORT in Wh and TOTAL_EXPORT in Wh to the configured topics.

Was tested with fronius gen24 as primary counter and secandary counter

Install 
```
apt install python3 python3-pip git
pip3 install "paho-mqtt<2.0.0" pymodbus
git clone https://github.com/maggo1404/fronius_smart_meter_modbus_tcp_emulator.git
cp zaehler.service /etc/systemd/system
systemctl daemon-reload
systemctl enable zaehler
systemctl start zaehler
systemctl status zaehler
```
