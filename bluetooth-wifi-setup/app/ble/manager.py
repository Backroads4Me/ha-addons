
import signal
from time import sleep
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from ..utils.logger import mLOG
from ..utils.config import ConfigData
from ..crypto.manager import BTCryptoManager
from .core import Blue, Advertise
from .service import WifiSetService
from .service_framework import Application

BLE_SERVER_GLIB_TIMEOUT = 2500  # used for checking BLE Server timeout

class BLEManager:

    def __init__(self):
        signal.signal(signal.SIGTERM, self.graceful_quit)
        ConfigData.initialize()
        self.cryptoManager = BTCryptoManager()
        self.mainloop = GLib.MainLoop()
        self.counter = 0
        self.need_restart = False

    def quitBT(self):
        mLOG.log(f"quitting Bluetooth - need_restart is {self.need_restart}")
        self.cryptoManager.pi_info.saveInfo()
        sleep(1)
        try:
            if self.advert: 
                mLOG.log("calling advertisement de-registration")
                self.advert.unregister()
            if self.app: 
                mLOG.log("calling application de-registration")
                self.app.unregister()
            sleep(1)
        except Exception as ex:
            mLOG.log(ex)
        self.mainloop.quit()


    def graceful_quit(self,signum,frame):
        mLOG.log("stopping main loop on SIGTERM received")
        self.quitBT()

    def check_button(self):
        #placeholder -  return true if button was pressed
        return True
    
    def timeout_manager(self):
        #mLOG.log(f'checking timeout {ConfigData.START}')
        # global justTesting
        # if justTesting:
        #     wifiset_service.testDbusAppUser()
        #     justTesting = False
        # this is for testing restart only
        # if restart_count == 0:
        #     self.counter += 1
        #     if self.counter > 1 :
        #         self.advert.register_ad_error_callback("Maximum")
        #         return True

        if ConfigData.check_timeout():
            mLOG.log("BLE Server timeout - exiting...")
            self.quitBT()
            return False
        else:
            return True

    

    def start(self):
        mLOG.log("** Starting BTwifiSet - version 3 (HA Supervisor API")
        mLOG.log("** Version date: March 10 2025 **\n")
        mLOG.log(f'BTwifiSet timeout: {int(ConfigData.TIMEOUT/60)} minutes')
        mLOG.log("starting BLE Server")
        ConfigData.reset_timeout()
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        Blue.set_adapter()
        Blue.bus.add_signal_receiver(Blue.properties_changed,
                    dbus_interface = "org.freedesktop.DBus.Properties",
                    signal_name = "PropertiesChanged",
                    arg0 = "org.bluez.Device1",
                    path_keyword = "path")
                    
        self.app = Application(self)
        #added passing a reference to the session dbus so service can register the userapp dbus listener when needed
        # justTesting = True
        wifiset_service = WifiSetService(0,self.mainloop,self.cryptoManager)
        self.app.add_service(wifiset_service)
        self.app.register()
        self.advert = Advertise(0,self)
        print("registering")
        self.advert.register()
        # sleep(1)
        # print("de-registering")
        # self.advert.unregister()
        # sleep(1)
        # print("registering")
        # self.advert.register()

        try:
            GLib.timeout_add(BLE_SERVER_GLIB_TIMEOUT, self.timeout_manager)
            mLOG.log("starting main loop")
            self.mainloop.run()
        except KeyboardInterrupt:
            mLOG.log("stopping main loop on keyboard interrupt")
            self.cryptoManager.pi_info.saveInfo()
            sleep(1)
            self.quitBT()
