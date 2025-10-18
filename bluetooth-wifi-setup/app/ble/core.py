
import dbus
import dbus.service

from ..utils.logger import mLOG
from ..wifi.utils import WifiUtil
from ..utils.config import ConfigData

# Define UUIDs and other constants
UUID_WIFISET = 'fda661b6-4ad0-4d5d-b82d-13ac464300ce'

def dbus_to_python(data):
    '''
        convert dbus data types to python native data types
    '''
    if isinstance(data, dbus.String):
        data = str(data)
    elif isinstance(data, dbus.Boolean):
        data = bool(data)
    elif isinstance(data, dbus.Int64):
        data = int(data)
    elif isinstance(data, dbus.Double):
        data = float(data)
    elif isinstance(data, dbus.Array):
        data = [dbus_to_python(value) for value in data]
    elif isinstance(data, dbus.Dictionary):
        new_data = dict()
        for key in data.keys():
            new_data[dbus_to_python(key)] = dbus_to_python(data[key])
        data = new_data
    return data

class Blue:
    adapter_name = ''
    bus = None
    adapter_obj = None
    counter = 1
    user_requested_endSession = False
    user_ended_session = False

    @staticmethod
    def set_adapter():
        try:
            found_flag = False
            Blue.bus = dbus.SystemBus()
            obj = Blue.bus.get_object('org.bluez','/')
            obj_interface=dbus.Interface(obj,'org.freedesktop.DBus.ObjectManager')
            all = obj_interface.GetManagedObjects()
            for item in all.items(): #this gives a list of all bluez objects
                # mLOG.log(f"BlueZ Adapter name: {item[0]}")
                # mLOG.log(f"BlueZ Adapter data: {item[1]}\n")
                # mLOG.log("******************************\n")
                if  (item[0] == '/org/bluez/hci0') or ('org.bluez.LEAdvertisingManager1' in item[1].keys() and 'org.bluez.GattManager1' in item[1].keys() ):
                    #this the bluez adapter1 object that we need
                    # mLOG.log(f"Found BlueZ Adapter name: {item[0]}\n")
                    found_flag = True
                    Blue.adapter_name = item[0]
                    Blue.adapter_obj = Blue.bus.get_object('org.bluez',Blue.adapter_name)
                    #turn_on the adapter - to make sure (on rpi it may already be turned on)
                    props = dbus.Interface(Blue.adapter_obj,'org.freedesktop.DBus.Properties')

                    props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))
                    props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(0))
                    props.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0))
                    props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(1))
                    props.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0))

                    break
            if not found_flag:
                mLOG.log("No suitable Bluetooth adapter found")
                #raise Exception("No suitable Bluetooth adapter found")
            
        except dbus.exceptions.DBusException as e:
            mLOG.log(f"DBus error in set_adapter: {str(e)}")
            raise
        except Exception as e:
            mLOG.log(f"Error in set_adapter: {str(e)}")
            raise


    @staticmethod
    def adv_mgr(): 
        return dbus.Interface(Blue.adapter_obj,'org.bluez.LEAdvertisingManager1')

    @staticmethod
    def gatt_mgr():
        return dbus.Interface(Blue.adapter_obj,'org.bluez.GattManager1')

    @staticmethod
    def properties_changed(interface, changed, invalidated, path):
        if interface != "org.bluez.Device1":
            return
        
        Blue.counter += 1

        try:
            pythonDict = dbus_to_python(changed)

            # Log important connection state changes (suppress RSSI noise)
            if 'Connected' in pythonDict:
                device = path.split('/')[-1]
                mLOG.log(f"Bluetooth device {device}: Connected = {pythonDict['Connected']}")

            if 'ServicesResolved' in pythonDict:
                device = path.split('/')[-1]
                status = "ready" if pythonDict['ServicesResolved'] else "disconnected"
                mLOG.log(f"Bluetooth device {device}: Services {status}")

            # Handle graceful disconnection detection
            # When phone app ends its session, it sends a graceful disconnect message which sets user_requested_endSession to True.
            # This is recognized here - code could be inserted to launch actions when the user disconnects.
            # Note: Phone app may disconnect without sending the graceful message (out of range, wrong password, etc.)
            # In that case disconnection is detected by ServicesResolved=False but user_requested_endSession is not set.
            Blue.user_ended_session = (
                Blue.user_requested_endSession and
                not pythonDict.get("ServicesResolved", True))  # Use .get() with default to avoid KeyError
            if Blue.user_ended_session:
                mLOG.log("User has notified BT session/disconnected")
                # ADD ANY ACTION ON USER ENDING SESSION HERE
                Blue.user_ended_session = False
                Blue.user_requested_endSession = False

        except Exception as e:
            # Log exceptions instead of silently swallowing them
            mLOG.log(f"Error in properties_changed: {e}", level=mLOG.DEV)        

class Advertise(dbus.service.Object):

    def __init__(self, index,bleMgr):
        self.bleMgr = bleMgr
        # Use configured device name, fallback to hostname if not set
        if ConfigData.DEVICE_NAME and ConfigData.DEVICE_NAME.strip():
            self.advertised_name = ConfigData.DEVICE_NAME.strip()
        else:
            self.hostname = WifiUtil.get_hostname().strip()
            self.advertised_name = self.hostname

        self.properties = dict()
        self.properties["Type"] = dbus.String("peripheral")
        self.properties["ServiceUUIDs"] = dbus.Array([UUID_WIFISET],signature='s')
        self.properties["IncludeTxPower"] = dbus.Boolean(True)
        self.properties["LocalName"] = dbus.String(self.advertised_name)
        mLOG.log(f"Advertising Bluetooth as: {self.advertised_name}")
        self.properties["Flags"] = dbus.Byte(0x06) 

        #flags: 0x02: "LE General Discoverable Mode"
        #       0x04: "BR/EDR Not Supported"
        self.path = "/org/bluez/advertise" + str(index)
        dbus.service.Object.__init__(self, Blue.bus, self.path)
        self.ad_manager = Blue.adv_mgr() 


    def get_properties(self):
        return {"org.bluez.LEAdvertisement1": self.properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.get_properties()["org.bluez.LEAdvertisement1"]

    @dbus.service.method("org.bluez.LEAdvertisement1", in_signature='', out_signature='')
    def Release(self):
        mLOG.log('%s: Released!' % self.path)

    def register_ad_callback(self):
        mLOG.log("GATT advertisement registered", level=mLOG.INFO)

    def register_ad_error_callback(self,error):
        #Failed to register advertisement: org.bluez.Error.NotPermitted: Maximum advertisements reached
        #now calling for restart if any error occurs here
        try:
            errorStr = f"{error}"
            if "Maximum" in errorStr:
                mLOG.log("Maximum advertisements reached. Waiting for a slot to become available.", level=mLOG.INFO)
                self.bleMgr.need_restart = False
            else:
                mLOG.log(f"Advertisement registration error: {errorStr} - calling for restart", level=mLOG.CRITICAL)
                self.bleMgr.need_restart = True
        except:
            pass

        if self.bleMgr.need_restart:
            mLOG.log(f"need_restart is set to {self.bleMgr.need_restart}", level=mLOG.CRITICAL)
            mLOG.log(f"Failed to register GATT advertisement {error}", level=mLOG.CRITICAL)
            mLOG.log("calling quitBT()", level=mLOG.CRITICAL)
            self.bleMgr.quitBT()

    def register(self):
        mLOG.log("Registering advertisement")
        self.ad_manager.RegisterAdvertisement(self.get_path(), {},
                                     reply_handler=self.register_ad_callback,
                                     error_handler=self.register_ad_error_callback)
        
    def unregister(self):
        mLOG.log(f"De-Registering advertisement - path: {self.get_path()}")
        self.ad_manager.UnregisterAdvertisement(self.get_path())
        try:
            dbus.service.Object.remove_from_connection(self)
        except Exception as ex:
            mLOG.log(ex)
