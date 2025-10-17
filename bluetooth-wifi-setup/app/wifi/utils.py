
import os
import re
import subprocess
import time

from ..utils.logger import mLOG

class WifiUtil:

    @staticmethod
    def signal(strength):
        #SAME
        ''' converts dbm strength (negative int) into scale from 0 to 5
        '''
        val = 5
        try:
            if int(strength)<-39:
                #python int function drops the decimal part: int(1.99) = 1
                #<40=5, 40-50 =5, 51-60 = 4, 60-70: 3, 71-80: 2, 81-90: 1  smaller than -91 returns 0
                val = max(0,int( (100+int(strength))/10 ))
        except Exception as e:
                mLOG.log(f'ERROR: {e}')
                signal_strength = 0
        return val
    
    @staticmethod
    def freq_to_channel(freq_str):
     try:
        freq = int(freq_str)
     except:
         return 0
     if (freq == 2484): return 14
     #this returns 2.4GHZ channels
     if (freq < 2484):
        return int((freq - 2407) / 5)
     #this returns 5 GHZ channels
     return int(freq/5 - 1000)
    
    @staticmethod
    def scan_for_channel():
        #each ssid is dictionary with keys: frequency,signalStrength,channel,ssid
        #note: signalStrength is in dbm (less negative is stronger)
        found_ssids = []
        result = subprocess.run("wpa_cli -i wlan0 scan", 
                            shell=True,capture_output=True,encoding='utf-8',text=True)
        if result.stderr: mLOG.log(f"scan error: {result.stderr}")
        time.sleep(1)
        result = subprocess.run("wpa_cli -i wlan0 scan_results", 
                            shell=True,capture_output=True,encoding='utf-8',text=True)
        if result.stderr: mLOG.log(f"scan error results: {result.stderr}")
        out = result.stdout
        mLOG.log(f"scan results:{out}")
        #this regex gtes frequency , signalstrength, ssid name
        ssids = re.findall(r"[^\s]+\s+(\d+)\s+(-?\d+)\s+[^\s]+\t+(.+)", out,re.M) 
        try:
            for freq,strength,ssid in ssids:
                channel = WifiUtil.freq_to_channel(freq)
                found_ssids.append({"ssid":ssid,"frequency":int(freq),"signalStrength":int(strength),"channel":int(channel)})
        except:
            pass
        return found_ssids


    @staticmethod
    def get_hostname():
        result = subprocess.run("hostname", 
                                shell=True,capture_output=True,encoding='utf-8',text=True)
        return result.stdout

    @staticmethod
    def get_ip_address():
        #returns dictionary 
        result = subprocess.run("ip addr show wlan0", 
                                shell=True,capture_output=True,encoding='utf-8',text=True)
        out = result.stdout
        err = result.stderr
        if err: mLOG.log(f"ip error: {err}")
        if "not found" in err:
            return {"ip4":"Error - linux command: ip (not installed on your system)\nto install - run in terminal: apt install iproute2","ip6":""}
        elif err:
            return {"ip4":f"Error:{err}","ip6":""}
        else:
            ip4 = re.findall(r"^\s+inet\s+([\d+.]+)", out,re.M)  
            ip6 = re.findall(r"^\s+inet6+\s+([a-zA-Z0-9:]+.+)", out,re.M)
            ip4_msg = ""
            for ip in ip4:
                ip4_msg += ip + "\n"
            ip4_msg = ip4_msg[:-1]
            ip6_msg = ""
            for ip in ip6:
                ip6_msg += "\n" + ip 
            if not ip4_msg: ip4_msg = "not connected or available"
            if not ip6_msg: ip6_msg = "not connected or available"
            mLOG.log(f'ip4: {ip4_msg}')
            mLOG.log(f"ip6: {ip6_msg}")
            return {"ip4":ip4_msg,"ip6":ip6_msg}


    @staticmethod
    def get_mac():
        dir = "/sys/class/net"
        devices = []
        try:
            entries = os.listdir(dir)
        except:
            entries = []
        for dev in entries:
            if dev == "lo": continue
            kind = "wireless" if os.path.isdir(f"{dir}/{dev}/wireless") else "ethernet"
            try:
                with open(f"{dir}/{dev}/address") as address:
                    mac = address.read().strip()
            except:
                mac = "not available"
            devices.append({"device":dev,"kind":kind,"mac":mac})

        """
        Devices:
            hci0	B4:27:EC:70:B5:50
            """
        result = subprocess.run("hcitool dev", 
                            shell=True,capture_output=True,encoding='utf-8',text=True)
        out = result.stdout
        if result.stderr: mLOG.log(f"bluetooth cli error:{result.stderr}")
        btdevs = re.findall(r"(\w+)\s+([0-9A-Za-z:]+)", out,re.M)
        for btdev in btdevs:
            try:
                devices.append({"device":btdev[0],"kind":"bluetooth","mac":btdev[1]})
            except:
                pass
        return devices

    @staticmethod
    def get_other_info():
        oth = WifiUtil.otherInfo()
        if oth is None:
            return None
        else:
            try :
                return {"other":str(oth)}
            except:
                return None

    #To send other information to the iphone - modify the function below as needed:
    @staticmethod
    def otherInfo():
        #1. remove this line:
        #info = None
        info = subprocess.run("free", 
                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        if (info):
            try:
                lines = info.strip().split('\n')
                headers = lines[0].split()
                mem_values = lines[1].split()
                info = "Memory     total          Used\n"
                info += f"                {mem_values[1]}     {mem_values[2]}\n\n"
            except:
                info = ""
        else:
            info = ""

        try:
            info += subprocess.run("vcgencmd measure_temp", 
                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        except:
            info += ""
            
        #print(f"OtherInfo\n{info}")
        # 2. add code that generate a string representing the info you want
        #IMPORTANT: you must return a string (not an object!)
        """
        if the info can be obtained from a bash call - you can use this:
        
        info = subprocess.run("enter bash command here", 
                shell=True,capture_output=True,encoding='utf-8',text=True).stdout

        If the returned data from the command requires user input for paging,
            ensure that a no-pager option of some type is used - other wise the system will hang.
        """
        
        return info
