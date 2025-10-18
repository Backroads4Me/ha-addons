
import dbus
import dbus.service

from ..utils.logger import mLOG


class BTDbusSender(dbus.service.Object):
    """
    DBus service for sending button signals to the iOS app.
    This allows communication of button clicks and other UI events
    from the phone app to user applications via DBus.
    """
    def __init__(self):
        bus_name = dbus.service.BusName('com.normfrenette.bt', bus=dbus.SessionBus())
        dbus.service.Object.__init__(self, bus_name, '/com/normfrenette/bt')

    @dbus.service.signal('com.normfrenette.bt')
    def send_signal_on_dbus(self, msg):
        mLOG.log(f'bt sending button signal: {msg}')

    def send_signal(self, msg):
        self.send_signal_on_dbus(msg)
