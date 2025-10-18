
import dbus
import dbus.service
from gi.repository import GLib

from ..utils.logger import mLOG
from .core import Blue

class Application(dbus.service.Object):
    def __init__(self,bleMgr):
        self.bleMgr = bleMgr
        self.path = "/"
        self.services = []
        self.next_index = 0
        dbus.service.Object.__init__(self, Blue.bus, self.path)
        self.service_manager = Blue.gatt_mgr()

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature = "a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()
        return response

    def register_app_callback(self):
        mLOG.log("GATT application registered")

    def register_app_error_callback(self, error):
        #failing to register will call for restart
        self.bleMgr.need_restart = True
        mLOG.log("Failed to register application: " + str(error))
        mLOG.log(f"app registration handler has set need_restart to {self.bleMgr.need_restart}")
        mLOG.log("calling quitBT()")
        self.bleMgr.quitBT()

    def register(self):
        #adapter = BleTools.find_adapter(self.bus)
        #service_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter),GATT_MANAGER_IFACE)
        self.service_manager.RegisterApplication(self.get_path(), {},
                reply_handler=self.register_app_callback,
                error_handler=self.register_app_error_callback)
        
    def unregister(self):
        mLOG.log(f"De-Registering Application - path: {self.get_path()}")
        try:
            for service in self.services:
                service.deinit()
        except Exception as exs:
            mLOG.log(f"exception trying to deinit service")
            mLOG.log(exs)
        try:
            self.service_manager.UnregisterApplication(self.get_path())
        except Exception as exa:
            mLOG.log(f"exception trying to unregister Application")
            mLOG.log(exa)
        try:
            dbus.service.Object.remove_from_connection(self)
        except Exception as exrc:
            mLOG.log(f"dbus exception trying to remove object from connection")
            mLOG.log(exrc)
        

class Service(dbus.service.Object):
    #PATH_BASE = "/org/bluez/example/service"
    PATH_BASE = "/org/bluez/service"

    def __init__(self, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, Blue.bus, self.path)

    def deinit(self):
        mLOG.log(f"De-init Service  - path: {self.path}")
        for characteristic in self.characteristics:
            characteristic.deinit()
        try:
            dbus.service.Object.remove_from_connection(self)
        except Exception as ex:
            mLOG.log(ex)

    def get_properties(self):
        return {
                "org.bluez.GattService1": {
                        'UUID': self.uuid,
                        'Primary': self.primary,
                        'Characteristics': dbus.Array(
                                self.get_characteristic_paths(),
                                signature='o'),
                        'Secure': dbus.Array([], signature='s')  # Empty array means no security required
                }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for characteristic in self.characteristics:
            result.append(characteristic.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return self.get_properties()["org.bluez.GattService1"]

class Characteristic(dbus.service.Object):

    def __init__(self, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.descriptors = []
        dbus.service.Object.__init__(self, Blue.bus, self.path)

    def deinit(self):
        mLOG.log(f"De-init Characteristic  - path: {self.path}")
        for descriptor in self.descriptors:
            descriptor.deinit()
        try:
            dbus.service.Object.remove_from_connection(self)
        except Exception as ex:
            mLOG.log(ex)

    def get_properties(self):
        return {
                "org.bluez.GattCharacteristic1": {
                        'Service': self.service.get_path(),
                        'UUID': self.uuid,
                        'Flags': self.flags,
                        'Descriptors': dbus.Array(
                                self.get_descriptor_paths(),
                                signature='o'),
                        'RequireAuthentication': dbus.Boolean(False),
                        'RequireAuthorization': dbus.Boolean(False),
                        'RequireEncryption': dbus.Boolean(False),
                }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_descriptor(self, descriptor):
        self.descriptors.append(descriptor)

    def get_descriptor_paths(self):
        result = []
        for desc in self.descriptors:
            result.append(desc.get_path())
        return result

    def get_descriptors(self):
        return self.descriptors

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return self.get_properties()["org.bluez.GattCharacteristic1"]

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        mLOG.log('Default ReadValue called, returning error')

    @dbus.service.method("org.bluez.GattCharacteristic1", in_signature='aya{sv}')
    def WriteValue(self, value, options):
        mLOG.log('Default WriteValue called, returning error')

    @dbus.service.method("org.bluez.GattCharacteristic1")
    def StartNotify(self):
        mLOG.log('Default StartNotify called, returning error')

    @dbus.service.method("org.bluez.GattCharacteristic1")
    def StopNotify(self):
        mLOG.log('Default StopNotify called, returning error')

    @dbus.service.signal("org.freedesktop.DBus.Properties", signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def add_timeout(self, timeout, callback):
        GLib.timeout_add(timeout, callback)

class Descriptor(dbus.service.Object):
    def __init__(self, index,uuid, flags, characteristic):
        self.path = characteristic.path + '/desc' + str(index)
        self.uuid = uuid
        self.flags = flags
        self.chrc = characteristic
        dbus.service.Object.__init__(self, Blue.bus, self.path)

    def deinit(self):
        mLOG.log(f"De-init Descriptor  - path: {self.path}")
        try:
            dbus.service.Object.remove_from_connection(self)
        except Exception as ex:
            mLOG.log(ex)

    def get_properties(self):
        return {
                "org.bluez.GattDescriptor1": {
                        'Characteristic': self.chrc.get_path(),
                        'UUID': self.uuid,
                        'Flags': self.flags,
                        'Secure': dbus.Array([], signature='s') 
                }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method("org.freedesktop.DBus.Properties", in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return self.get_properties()["org.bluez.GattDescriptor1"]

    @dbus.service.method("org.bluez.GattDescriptor1", in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        mLOG.log('Default ReadValue called, returning error')

    @dbus.service.method("org.bluez.GattDescriptor1", in_signature='aya{sv}')
    def WriteValue(self, value, options):
        mLOG.log('Default WriteValue called, returning error')
