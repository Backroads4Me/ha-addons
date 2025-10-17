
import argparse
import time

from .logger import mLOG

class ConfigData:
    '''
    A timeout exists that will shutdown the BLE Server
        if it does not receive commands from the iphone app within this timeout period.
        - BLE_shutdown_time = xx, where xx is the number of minutes for the time out.
        - insert "never" if it nevers time out
    Note that every time a command is received from the ios iphone app
    - the time out period is reset to zero.
    '''
    START = 0  #time at which we start counting BLE Server usage.
    TIMEOUT = 0 #this is in seconds
    DEVICE_NAME = "BTBerryWifi" #default Bluetooth advertised name
    

    @staticmethod
    def initialize():
        parser = argparse.ArgumentParser(
            prog="btwifi",
            description="Configure WiFi over BLE")

        parser.add_argument("--timeout", help="Server timeout in minutes")
        parser.add_argument("--device-name", help="Bluetooth advertised device name")
        parser.add_argument("--syslog", help="Log messages to syslog", action='store_true')
        parser.add_argument("--console", help="Log messages to console", action='store_true')
        parser.add_argument("--logfile", help="Log messages to specified file")
        args = parser.parse_args()

        ConfigData.TIMEOUT = 15*60 if args.timeout is None else int(args.timeout)*60
        ConfigData.DEVICE_NAME = "BTBerryWifi" if args.device_name is None else args.device_name
        mLOG.initialize(args.syslog, args.console, args.logfile)

    @staticmethod
    def reset_timeout():
        ConfigData.START = time.monotonic()

    @staticmethod
    def check_timeout():
        '''retunrs True if timeout has elapsed'''
        if time.monotonic() - ConfigData.START > ConfigData.TIMEOUT:
            return True
        else:
            return False
