#!/usr/bin/env python

from gi.repository import GLib  # pyright: ignore[reportMissingImports]
from pymodbus.client.sync import ModbusSerialClient as ModbusClient
import platform
import logging
import sys
import os
from time import sleep
import configparser  # for config/ini file
import _thread
import dbus

# import Victron Energy packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext", "velib_python"))
from vedbus import VeDbusService

# formatting
def _litres(p, v):
    return str("%.3f" % v) + "m3"

def _percent(p, v):
    return str("%.1f" % v) + "%"

def _n(p, v):
    return str("%i" % v)

class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)
        
def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()

# get values from config.ini file
try:
    config_file = (os.path.dirname(os.path.realpath(__file__))) + "/config.ini"
    if os.path.exists(config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
    else:
        print(
            'ERROR:The "'
            + config_file
            + '" is not found. Did you copy or rename the "config.sample.ini" to "config.ini"? The driver restarts in 60 seconds.'
        )
        sleep(60)
        sys.exit()

except Exception:
    exception_type, exception_object, exception_traceback = sys.exc_info()
    file = exception_traceback.tb_frame.f_code.co_filename
    line = exception_traceback.tb_lineno
    print(
        f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}"
    )
    print("ERROR:The driver restarts in 60 seconds.")
    sleep(60)
    sys.exit()


# Get logging level from config.ini
# ERROR = shows errors only
# WARNING = shows ERROR and warnings
# INFO = shows WARNING and running functions
# DEBUG = shows INFO and data/values
if "DEFAULT" in config and "logging" in config["DEFAULT"]:
    if config["DEFAULT"]["logging"] == "DEBUG":
        logging.basicConfig(level=logging.DEBUG)
    elif config["DEFAULT"]["logging"] == "INFO":
        logging.basicConfig(level=logging.INFO)
    elif config["DEFAULT"]["logging"] == "ERROR":
        logging.basicConfig(level=logging.ERROR)
    else:
        logging.basicConfig(level=logging.WARNING)
else:
    logging.basicConfig(level=logging.WARNING)

log = logging.getLogger("__name__")


# get type Tank #1
if "DEFAULT" in config and "type" in config["DEFAULT"]:
    type = int(config["DEFAULT"]["type"])
else:
    type = 0

# get capacity Tank #1
if "DEFAULT" in config and "capacity" in config["DEFAULT"]:
    capacity = float(config["DEFAULT"]["capacity"])
else:
    capacity = 100


# get standard Tank #1
if "DEFAULT" in config and "standard" in config["DEFAULT"]:
    standard = int(config["DEFAULT"]["standard"])
else:
    standard = 0    


# set variables
connected = 0
level = -999
remaining = None



class DepthSensor:
    def __init__(self):
        self.client = ModbusClient(
            method='rtu',
            port='/dev/ttyUSB0',  # linux
            baudrate=9600,
            timeout=3,
            parity='N',
            stopbits=1,
            bytesize=8
        )
        self.unit_id = 1
        self.tank_depth = 5.0
        self.tank_area = 1.0

        # Connect to the Modbus client
        if self.client.connect():
            log.warning("Connected to Modbus client")
            unit_response = self.client.read_holding_registers(0x0002, 1, unit=self.unit_id)

            if not unit_response.isError():
                unit_value = unit_response.registers[0]
                unit_mapping = {
                    0x0000: "MPa",
                    0x0001: "kPa",
                    0x0002: "Pa",
                    0x0003: "bar",
                    0x0004: "mbar",
                    0x0005: "kg/cm²",
                    0x0006: "psi",
                    0x0007: "mH₂O",
                    0x0008: "mmH₂O",
                    0x0009: "°C",
                    0x000A: "cmH₂O"
                }


                current_unit = unit_mapping.get(unit_value, "Unknown Unit")

                # Read scaling factor
                scaling_response = self.client.read_holding_registers(0x0003, 1, unit=self.unit_id)
                if not scaling_response.isError():
                    scaling_value = scaling_response.registers[0]
                    scaling_factors = {0x0000: 1, 0x0001: 0.1, 0x0002: 0.01, 0x0003: 0.001}
                    self.scaling_factor = scaling_factors.get(scaling_value, 1)
            else:
                log.error("Error reading unit value")

    def get_level(self):
        result = self.client.read_holding_registers(0x0004, 1, unit=self.unit_id)
        err = result.isError()
        if not err:
            raw_value = result.registers[0]
            if raw_value == 65534:
                return None
            else:
                level = raw_value * self.scaling_factor
                                    # Calculate percentage of tank filled
                level_percentage = (level / self.tank_depth) * 100  # in percentage
                    
                # Calculate total and remaining volume
                total_volume = self.tank_area * self.tank_depth  # in cubic meters
                current_volume = level * self.tank_area  # in cubic meters
                remaining_volume = total_volume - current_volume  # in cubic meters
                    
                # Convert remaining volume to liters
                remaining_volume_liters = remaining_volume * 1 #1000  # 1 m³ = 1000 liters
                    
                    
                # Prepare JSON output
                log.warning(f"Level: {level_percentage:.2f}%, Remaining Volume: {remaining_volume_liters:.2f} liters")


                return level_percentage, remaining_volume_liters, False

        else:
            log.error("Error reading data from GLT500.")
            return -1, -1, True




class DbusMqttLevelService:
    def __init__(
        self,
        servicename,
        deviceinstance,
        paths,
        depthsensor: DepthSensor,
        productname="DCP Tank Levels",
        customname="DCP Tank Levels",
        connection="DCP Tank Levels service"): 
        self._depthsensor = depthsensor 
        self._dbusservice = VeDbusService(servicename,dbusconnection())
        self._paths = paths
        self.last = -2

        logging.info("Starting DbusDcpLevelService")
        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path(
            "/Mgmt/ProcessVersion",
            "Unkown version, and running on Python " + platform.python_version(),
        )
        self._dbusservice.add_path("/Mgmt/Connection", connection)

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xFFFF)
        self._dbusservice.add_path("/ProductName", productname)
        self._dbusservice.add_path("/CustomName", customname)
        self._dbusservice.add_path("/FirmwareVersion", "0.0.1 (20241008)")
        # self._dbusservice.add_path('/HardwareVersion', '')
        self._dbusservice.add_path("/Connected", 1)

        self._dbusservice.add_path("/Status", 0)
        self._dbusservice.add_path("/FluidType", type)
        self._dbusservice.add_path("/Capacity", capacity)
        self._dbusservice.add_path("/Standard", standard)

        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path,
                settings["initial"],
                gettextcallback=settings["textformat"],
                writeable=True,
                onchangecallback=self._handlechangedvalue,
            )

        GLib.timeout_add(5000, self._update)  # pause 1000ms before the next request

    def _update(self):
        
        level, remaining, err = self._depthsensor.get_level()
        if err:
            return True
        current = level + remaining

        if self.last != current:
            self._dbusservice["/Level"] = (
                round(level, 1) if level is not None else None
            )
            self._dbusservice["/Remaining"] = (
                round(remaining, 3) if remaining is not None else None
            )

            log_message = "Level: {:.1f} %".format(level)
            log_message += (
                " - Remaining: {:.1f} m3".format(remaining) if remaining is not None else ""
            )
            log.info(log_message)

            self.last = current


        # increment UpdateIndex - to show that new data is available
        index = self._dbusservice["/UpdateIndex"] + 1  # increment index
        if index > 255:  # maximum value of the index
            index = 0  # overflow from 255 to 0
        self._dbusservice["/UpdateIndex"] = index
        return True

    def _handlechangedvalue(self, path, value):
        log.debug("someone else updated %s to %s" % (path, value))
        return True  # accept the change
    
def main():
    global level, remaining
    _thread.daemon = True  # allow the program to quit

    from dbus.mainloop.glib import (  # pyright: ignore[reportMissingImports]
        DBusGMainLoop,
    )

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    DBusGMainLoop(set_as_default=True)

    

    # wait to receive first data, else the JSON is empty and phase setup won't work
    i = 0
    depthsensor= DepthSensor()
    while level == -1:
        level, remaining, err = depthsensor.get_level()
        if i % 12 != 0 or i == 0:
            log.info("Waiting 5 seconds for receiving first data...")
        else:
            log.warning(
                "Waiting since %s seconds for receiving first data..." % str(i * 5)
            )
        sleep(1)
        i += 1



    paths_dbus = {
        "/Level": {"initial": None, "textformat": _percent},
        "/Remaining": {"initial": None, "textformat": _litres},
        "/UpdateIndex": {"initial": 0, "textformat": _n},
    }


    DbusMqttLevelService(
        servicename="com.victronenergy.tank.mqtt_tank_levels_"
        + str(config["MQTT"]["device_instance"]),
        deviceinstance=int(config["MQTT"]["device_instance"]),
        customname=config["MQTT"]["device_name"],
        paths=paths_dbus,
        depthsensor=depthsensor,
    )


    
    log.info(
        "Connected to dbus and switching over to GLib.MainLoop() (= event based)"
    )
    mainloop = GLib.MainLoop()
    mainloop.run()


if __name__ == "__main__":
    main()