
import dbus
import subprocess
from time import sleep

from app.utils.logger import mLOG
from app.ble.manager import BLEManager

if __name__ == "__main__":
    NEED_RESTART = True
    restart_count = 0

    def btRestart():
        mLOG.log(f"Restarting bluetooth service via D-Bus (restart count: {restart_count})")
        try:
            bus = dbus.SystemBus()
            systemd1 = bus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
            manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
            manager.RestartUnit('bluetooth.service', 'fail')
            mLOG.log("Bluetooth service restart command sent via D-Bus.")
            sleep(2)  # Give it a moment for the service to restart
        except Exception as e:
            mLOG.log(f"Failed to restart bluetooth via D-Bus: {e}", level=mLOG.CRITICAL)

        # Check status after attempting restart
        cmd = "systemctl --no-pager status bluetooth"
        mLOG.log("checking bluetooth status after restart")
        try:
            s = subprocess.run(cmd, shell=True, capture_output=True, encoding='utf-8', text=True, timeout=10)
            if s.stdout:
                mLOG.log(s.stdout)
            if s.stderr:
                mLOG.log(s.stderr, level=mLOG.INFO) # Status might print to stderr on some systems
        except Exception as e:
            mLOG.log(f"An unexpected error occurred while checking bluetooth status: {e}", level=mLOG.CRITICAL)

    while NEED_RESTART:
        NEED_RESTART = False
        blemgr = BLEManager()
        blemgr.start()
        mLOG.log(f"ble manager has exited with need restart = {NEED_RESTART}")
        restart_count += 1
        #allow only two restart of bluetooth (from advertisement error: maximum exceeded)
        # in case we get one for failed app register and one for failed advert register
        NEED_RESTART = NEED_RESTART and (restart_count < 3)
        if NEED_RESTART: btRestart()

    mLOG.log("btwifiset says: So long and thanks for all the fish")
