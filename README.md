# dbus-dcp-tank

**First off, a big thanks to [LundSoftwares](https://github.com/LundSoftwares) for the basis of the code in this repo**

This repo is very much work in progress, and is open source primarily to be installable with SetupHelper

### Disclaimer
I'm not responsible for the usage of this script. Use on own risk! 

### Purpose
The script reads sensor data from a Gamicos GLT500 depth sensor (https://www.gamicos.com/Products/GLT500-Pressure-Level-Sensor) connected to a Cerbo over RS485, and publishes the information on the dbus as the service com.victronenergy.tank.dcp_tank_level with the VRM instances from the Config file.

### Install
1. Copy the ```dbus-dcp-tank``` folder to ```/data/etc``` on your Venus OS device
2. Run ```bash /data/etc/dbus-dcp-tank/install.sh``` as root

The daemon-tools should start this service automatically within seconds.

### Uninstall
Run ```/data/etc/dbus-dcp-tank/uninstall.sh```

### Restart
Run ```/data/etc/dbus-dcp-tank/restart.sh```

### Debugging

The logs can be checked with ```tail -n 100 -F /data/log/dbus-dcp-tank/current | tai64nlocal```

The service status can be checked with svstat: ```svstat /service/dbus-dcp-tank```

This will output somethink like ```/service/dbus-dcp-tank: up (pid 5845) 185 seconds```


### Compatibility
Currently testing with Cerbo GX Mk2, Venus OS version v3.42
