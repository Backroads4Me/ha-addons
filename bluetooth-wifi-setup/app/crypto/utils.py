
import os
import json
import random
import subprocess
import re
from cryptography.hazmat.primitives import hashes

from ..utils.logger import mLOG

FILEDIR = f"{os.path.dirname(os.path.abspath(__file__))}/"

class PiInfo:
    PWFILE = FILEDIR+"crypto"
    INFOFILE = FILEDIR+"infopi.json"

    """
    variables and storing needs:
        - password - stores into file name crypto which makes it easy for use to read or update / can be None
    the folowing are stored as json (dict)
        - locked: Ture or False
        - rpi_id: create once to identify the hardware as best as possible (see RPiId class) / can be None
        - las_nonce: stored as integer (max 12 bytes see NonceCouter.MAXNONCE) defaults to 0
    """

    def __init__(self):
        self.password = self.getPassword()
        self.locked = False  # this is the permanent state saved to disk
        self.rpi_id = RPiId().rpi_id
        self.last_nonce = 0
        if not self.getInfoFromFile():
            if os.path.exists(PiInfo.INFOFILE):
                os.rename(PiInfo.INFOFILE, f"{PiInfo.INFOFILE}_corrupted")
                self.saveInfo()
        
    def getInfoFromFile(self):
        try:
            with open(PiInfo.INFOFILE, 'r', encoding="utf-8") as f:
                dict = json.load(f)
                self.locked = dict["locked"]
                self.last_nonce = dict["last_nonce"]
            return True  
        except FileNotFoundError:
            mLOG.log("file {PiInfo.INFOFILE} not created yet - using default values")
            return False
        except Exception as ex:
            mLOG.log(f"Error reading file {PiInfo.INFOFILE}: {ex}") 
            return False

    def saveInfo(self):
        try:
            dict = {"locked":self.locked, "last_nonce":self.last_nonce}
            with open(PiInfo.INFOFILE, "w", encoding='utf8') as f:
                json.dump(dict, f, ensure_ascii=False)
            return True
        except Exception as ex:
            mLOG.log(f"error writing to file {PiInfo.INFOFILE}: {ex}") 
            return False

    def getPassword(self):
        #if crypto file exists but password is empty string - return None as if file did not exist
        try:
            with open(PiInfo.PWFILE, 'r', encoding="utf-8") as f:
                pw = f.readline().rstrip()
                return pw if len(pw) > 0 else None     
        except Exception as ex:
            return None


class NonceCounter:
    # numNonce is a 96 bit unsigned integer corresponds to max integer of 79228162514264337593543950335 (2 to the 96 power minus 1)
    MAXNONCE = 2 ** 64 -1
    '''
    maintains and increment a nonce of 12 bytes - 96 bit 
    the 4 most significant bytes are used for the connected ipHone identifier
    the least significant 8 bytes are the actual message counter.
    RPi always sends a nonce with identifier = 0
    if increment goes above max value for 64 bit
    looped is set to True, and counter restarts at zero
    Note: the logic to handle a looped counter has not yet been written.
        this event should not happen in the btwifiset usage.

    fot init: last_nonce is the 64 bit message counter saved on disk when previous session ended (infopi.json)

    Last received mangement:
        - iphone use 4 bytes of 12 bytes nonce as identifier.
        - RPi keeps track of last received for each connected Iphone (there can be more than one) 
            usinf last_received_dict
        - when iPhone disconnects - it should send a disconnect message - if RPi is Locked - the identifier is included:
            when ipHone announces disconnection - remove key in dictionary
    '''
    def __init__(self,last_nonce):
        #last_nonce is normally saved on disk as Long
        self.num_nonce = last_nonce+2  #num_nonce is the RPi message counter
        self.looped = False
        self.last_received_dict = {}  #key is iphone identifier, value is last received 8 bytes message counter from iphone Nonce
        self._useAES = False #assume using chacha as default

    def removeIdentifier(self,x_in_bytes):
        identifier_bytes = x_in_bytes[8:]
        key = str(int.from_bytes(identifier_bytes, byteorder='little', signed=False))
        mLOG.log(f"Removing identifier form nonce dict: {key}")
        self.last_received_dict.pop(key, None)

    def checkLastReceived(self,x_in_bytes):
        '''
        checks last received
            if x_in_bytes passed in here is less or equal to current last receive - do nothing and return None
            otherwise, update and return the numerical value

        return True if nonce is good, false if it is stale
        '''
        try:
            message_counter_bytes = x_in_bytes[0:8]
            identifier_bytes = x_in_bytes[8:]
            message_counter = int.from_bytes(message_counter_bytes, byteorder='little', signed=False)
            identifier_str = str(int.from_bytes(identifier_bytes, byteorder='little', signed=False))
            mLOG.log(f"nonce received: {message_counter} - for identifier: {identifier_str}")
            #if first time seeing this identifier - just accept the nonce as is 
            if identifier_str not in self.last_received_dict:
                self.last_received_dict[identifier_str] = message_counter
                mLOG.log("this is a new identifier - added to last_received_dict")
                return True
            else :
                if message_counter <= self.last_received_dict[identifier_str]:
                    mLOG.log(f"stale nonce: last received = {self.last_received_dict[identifier_str]} - ignoring message")
                    return False
                else:
                    mLOG.log(f"updating last received to {message_counter}")
                    self.last_received_dict[identifier_str] = message_counter
                    return True
        except Exception as ex:
            mLOG.log(f"last receive check error: {ex}")
            return False

    def increment(self):
        if self.num_nonce >= NonceCounter.MAXNONCE:
            self.num_nonce = 0
            self.looped = True
        else:
            self.num_nonce += 1

    def next_even(self):
        self.increment()
        if self.num_nonce % 2 > 0:
            self.increment()
        return self.num_nonce

    @property
    def bytes(self):
        #signed is False by default
        # mapping num_nonce to 12 bytes means the 4 most significant bytes are always 0
        return self.num_nonce.to_bytes(12, byteorder='little')
    
    @property
    def padded_bytes(self):
        #used for Android AES encryption
        #signed is False by default
        # mapping num_nonce to 16 bytes means the 8 most significant bytes are always 0
        return self.num_nonce.to_bytes(16, byteorder='little')

    @property
    def useAES(self):
        return self._useAES

    @useAES.setter
    def useAES(self, value):
        self._useAES = value

class RPiId:
    # FILERPIID = "rpiid"

    def __init__(self):
        self.rpi_id = self.createComplexRpiID()

    def createComplexRpiID(self):
        cpuId = self.getNewCpuId()
        wifiId = self.getMacAddressNetworking()
        btId = self.getMacAdressBluetooth()
        complexId = cpuId if cpuId is not None else ""
        complexId += wifiId if wifiId is not None else ""
        complexId += btId if btId is not None else ""
        if complexId == "" :
            mLOG.log("no identifier found for this RPi - generating random id")
            complexId = str(int.from_bytes(random.randbytes(12), byteorder='little', signed=False))
        # print(cpuId,wifiId,btId)
        # print(complexId)
        # print(self.hashTheId(complexId))
        return self.hashTheId(complexId)

    def hashTheId(self,id_str):
        #return the hex representeion of the hash
        m = hashes.Hash(hashes.SHA256())
        m.update(id_str.encode(encoding = 'UTF-8', errors = 'strict'))
        hash_bytes = m.finalize()
        hash_hex = hash_bytes.hex()
        return hash_hex

    
    def getNewCpuId(self):
        out = subprocess.run(r'cat /proc/cpuinfo | grep "Serial"grep "Revision"grep "Hardware"', shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        matches = re.findall(r"^(Hardware|Revision|Serial)\s+:\s(.+)", out,re.M)  
        use_id = "".join([x[1] for x in matches])
        if len(use_id) ==0: return None
        return use_id

    #don't use /etc/machine-id - it is generated on install - i.e if user re-istalls on a card it will change
    def getCpuId(self):
        #first look for a cpu serial 
        str = subprocess.run("cat /proc/cpuinfo | grep Serial", shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        if len(str) > 0 :
            #this stirps the leading zeros if any
            cpu_id = re.findall(r':\s*(\S+)', str)
        if len(cpu_id) == 1:
            return cpu_id[0] if len(cpu_id[0]) > 0 else None
        else: 
            return None
    
    def getAdapterAddress(self,adapter):
        try:
            with open(f"{adapter}/address", 'r', encoding="utf-8") as f:
                found_id = f.read().rstrip('\n')
                return None if (found_id ==  "00:00:00:00:00:00" or found_id == "") else found_id
        except Exception as e:
            return None
    
    def getMacAddressNetworking(self):
        """
        look for ethernet adpater first and use address, if not look for wireless adapter and get address
        this is less robust since if user has removable adapters - they could change in which case
        user would need to re-establish password for RPI which display different MAC/ID
        - full blown RPi will have internet adapter on board.
        - smaller Rpi lie "zero" may have only wifi - or nothing
        """

        found_id = None

        #shortcut - most RPi have either eth0 or wlan0 - so try these two first
        eth0 = "/sys/class/net/eth0"
        wlan0 = "/sys/class/net/wlan0"
        #since this was written to allow the user to set a wifi SSID and password via bluetooth
        #in most cases we can expect the wlan0 adapter to exists - so always use that first
        if os.path.isdir(wlan0):
            found_id = self.getAdapterAddress(wlan0)
        if found_id is not None: return found_id
        if os.path.isdir(eth0):
            found_id = self.getAdapterAddress(eth0)
        if found_id is not None: return found_id
        

        #for differnet linux OS - name maybe different - use this to find ethernet and wifi adapters if they exists
        interfaces = [ f.path for f in os.scandir("/sys/class/net") if f.is_dir() ]
        wireless_interfaces = []
        ethernet_interfaces = []
        #wireless devices have the empty directory "wireless" in their directory, ethernet devices do not
        for interface in interfaces:
            if os.path.isdir(f"{interface}/wireless"):
                wireless_interfaces.append(interface)
            else:
                ethernet_interfaces.append(interface)
        
        for interfaces in (ethernet_interfaces, wireless_interfaces):
            interfaces.sort()
            for interface in interfaces:
                    found_id = self.getAdapterAddress(interface)
            if found_id is not None: return found_id

        return None

    def getMacAdressBluetooth(self):
        """
        although we are garanteed to find a mac address for bluetooth - it is not garanteed that this mac address will not change
        """
        str = subprocess.run("bluetoothctl list", shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        #this finds all interfaces but ignores lo
        mac = re.findall(r'^Controller\s+([0-9A-Fa-f:-]+)\s+', str)
        if len(mac) == 1:
            if len(mac[0]) > 0 : 
                return mac[0]
        
        return None
