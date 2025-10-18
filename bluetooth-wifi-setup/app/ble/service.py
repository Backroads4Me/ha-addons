
import dbus
import dbus.service
import json

from ..utils.logger import mLOG
from ..wifi.manager import WifiManager
from ..wifi.utils import WifiUtil
from .service_framework import Service, Characteristic, Descriptor
from .core import Blue, UUID_WIFISET
from .dbus_sender import BTDbusSender

# Define UUIDs and other constants
SEPARATOR_HEX = b'\x1e'
SEPARATOR = SEPARATOR_HEX.decode()  # string representation can be concatenated or use in split function
NOTIFY_TIMEOUT = 1000  #in ms - used for checking notifications

UUID_WIFIDATA = 'e622b297-6bfe-4f35-938e-39abfb697ac3' # characteristic WifiData: may be encrypted - used for all wifi data and commands
UUID_INFO = '62d77092-41bb-49a7-8e8f-dc254767e3bf'    # characteristic InfoWifi: pass instructions - in clear

class Notifications:
    """
    version 2 prefixes messages with the intended module target
        example: wifi:READY2
    to maitain compatibility with version 1 of the app, there should not be a prefix
            example: READY
    notification maintains the variable wifiprefix which is set to 
            either "wifi" or blank "" depending of whether version1 of the iphone app
            is making the request, or version 2 is.
            This is detected via the type of AP list request APs versus AP2s (see registerSSID method)
    note: this only applies to setNotifications which sends simple messages (not multipart)
            foro json - it is only ever used in version2 so wifi: is always used
    """

    def __init__(self,cryptoMgr):
        self.cryptomgr = cryptoMgr # hold a reference to the cryptoMgr in wifiset service
        self.notifications = []  #array of (encoded) notifications to send - in bytes (not string)
        self.unlockingMsg = b''
        self.messageCounter = 1
        self.wifi_prefix = "wifi"
        #contains the current encoded unlocking messgae to test against 
        #   to detect if pi is unlocking after being locked - following user request
        #see notifications in wifiCharasteristic for handling.
        # 
        # 
        # msg_bytes = self.service.cryptomgr.encrypt(msg)

    def reset(self):
        self.notifications = []  #array of (encoded) notifications to send - in bytes (not string)
        self.unlockingMsg = b''
        self.messageCounter = 1
        self.wifi_prefix = "wifi"

    def setappVersionWifiPrefix(self,version):
        #version is either 1 or 2
        self.wifi_prefix = "" if version == 1 else "wifi"

    def makePrefix(self,target):
        #return prefix with ":" based on version
        if target == "wifi":
            return f"{self.wifi_prefix}:" if self.wifi_prefix else ""
        else:
            return f"{target}:"

    def setNotification(self,msg,target):
        """msg must encode in utf8 to less than 182 bytes or ios will truncate
            msg_to_send is in bytes
        """
        mLOG.log(f"sending simple notification: {self.makePrefix(target) + msg}, encrypted: {self.cryptomgr.crypto is not None}")
        msg_to_send = self.cryptomgr.encrypt(SEPARATOR + self.makePrefix(target) + msg)
        if msg == "Unlocking":
            self.unlockingMsg = msg_to_send
        else:
            self.unlockingMsg = b''
        self.notifications.append(msg_to_send)

    def make_chunks(self,msg,to_send):
        # returns a list of chunks , each a string
        bmsg = msg.encode(encoding = 'UTF-8', errors = 'replace') #inserts question mark if character cannot be encoded
        #truncate at 150 bytes
        btruncated = bmsg[0:130]
        #reconvert to string - ignoring the last bytes if not encodable because truncation cut the unicode not on a boundary
        chunk_str = btruncated.decode('utf-8',errors='ignore')
        #get the remainder (as a string)
        remainder = msg[len(chunk_str):]
        #add the chunked string to the list
        to_send.append(chunk_str)

        if remainder: 
            #if there is a remaninder - re-apply chunking on it, passing in the list of chunks (to_send) so far
            return(self.make_chunks(remainder,to_send))
        else:
            return list(to_send)

    def setJsonNotification(self,msgObject,target,never_encypt = False):
        #msgObject must be an array 
        #typically contains dictionaries - but could contain other json encodable objects
        #The total length of the json string can exceed 182 bytes in utf8 encoding
        #each chunk must have separator prefix to indicate it is a notification
        # all chucnk except last chunk must have separator suffix to indicate more to come
        json_str = json.dumps(msgObject)
        chunked_json_list = self.make_chunks(json_str,[])
       
        if len(chunked_json_list) == 1:
            #not multipart - send normal notification
            mLOG.log(f"sending simple notification: {target}:{chunked_json_list[0]}")
            encrypted_msg_to_send = self.cryptomgr.encrypt(SEPARATOR + f"{target}:{chunked_json_list[0]}")
            self.notifications.append(encrypted_msg_to_send)
            return
        
        #chunked_json_list = ["this is a test meassage ","in two parts."]
        self.messageCounter += 1
        total = len(chunked_json_list)
        mLOG.log(f"sending multi part message to: {target} - number of parts: {total}")
        for i in range(total):
            prefix = f"multi{target}:{self.messageCounter}|{i+1}|{total}|"
            chunk_to_send = SEPARATOR + prefix + chunked_json_list[i]
            mLOG.log(f"sending part {i+1}:\n{chunk_to_send}")
            #no longer need a separator at the end to indicate continuation
            # if i+1 < len(chunked_json_list):
            #     chunk_to_send += SEPARATOR
            try:
                if never_encypt:
                    encrypted = chunk_to_send.encode('utf8')
                else:
                    mLOG.log(f"about to encrypt: {chunk_to_send}")
                    encrypted = self.cryptomgr.encrypt(chunk_to_send)
                self.notifications.append(encrypted)
            except Exception as ex:
                mLOG.log(f"Error encrypting json notification: {ex}")

class WifiSetService(Service):

    def __init__(self, index,main_loop,cryptoMgr):
        self.mgr = WifiManager()
        self.cryptomgr = cryptoMgr
        self.AP_list = []  #msg: signal|locked|in_supplicant|conected|SSID
        self.all_APs_dict = {"allAPs":[]}  #used in version of ios app / to read all AP via json object
        self.notifications = Notifications(cryptoMgr)
        self.current_requested_ssid = ''
        self.current_requested_pw = ''
        self.main_loop = main_loop #this exists only so characteristics can set it as their mainloop
        Service.__init__(self, index, UUID_WIFISET, True)
        self.add_characteristic(WifiDataCharacteristic(0,self))
        self.add_characteristic(InfoCharacteristic(1,self))
        self.sender = None
        self.phone_quitting_message = {"ssid":"#ssid-endBT#", "pw":"#pw-endBT#"}
        self.cryptomgr.setPhoneQuittingMessage(self.phone_quitting_message["ssid"]+SEPARATOR+self.phone_quitting_message["pw"])
        # self.startSendingButtons()
        # self.startListeningToUserApp()
        
        

    def getLockInfo(self):
        #returns either MACid or LOCKNonceMACId
        #Nonce must be exactly 12 bytes
        self.cryptomgr.piInfo()

    def appMsgHandler(self,msg):
        """
        this receives messgaes sent by user app - to be sent to iphone app via bluetooth
        it only is needed if user has created text boxes/lists displays on the iphone (button app)
        currently - only implements sending the text as notification
        """
        mLOG.log(f"received from user app: {msg}")
        msg_arr = [].append(msg)
        self.notifications.setJsonNotification(msg_arr,"button")

    def startSendingButtons(self):
        self.sender = BTDbusSender()

    def startListeningToUserApp(self):
        dbus.SessionBus().add_signal_receiver(self.appMsgHandler,
                        bus_name='com.normfrenette.apptobt',
                        path ='/com/normfrenette/apptobt' )


    def testDbusAppUser(self):
        self.startSendingButtons()
        self.startListeningToUserApp()
        nc = 0
        while nc < 4:
            nc += 1
            # print("nc:",nc)
            data = ""
            if nc>1: data = f"data is {nc*1000}"
            button_dict = {"code":f"ButtonCode{nc}", "data":data}
            # print(button_dict)
            json_str = json.dumps(button_dict)
            self.sender.send_signal(json_str)
            time.sleep(.7)

    def register_SSID(self,val):
        ''' action taken when ios app writes to WifiData characteristic
        val is in the form [first_string,second_string, code] - see description in characteristic Write method
        ios sends either commands or request for connections to SSID:
            - commands: val[0] must be blank string. then val[1] contains the command
                -note: command can be json string (user defined buttons)
            - connection_request: val[0] must not be blank and is the requested SSID
                                  val[1] is the password - which can be left blank (or = NONE if open SSID)
        Notifications to ios are one of three 
            (all notifications will be pre-pended by SEPARATOR in notification callback "info_wifi_callback"  below as means 
             to differentiate notification from AP info read by ios)
            - READY: when list of requested AP is compiled and ready to be sent
            - AP.msg: in the form xxxxSSID - where x is integer - indicated connected ssid
            - FAIL: if a connection request resulted in the RPi not being able to connect to any wifi AP
                    note: if a requested SSID could not be connected to, but RPi was able to reconnect to previous AP,
                          the connected AP info is sent back - it is up to ios to recognized that the requested connection has failed
                          and RPi is still connected to the previous AP.'
        mLOG.log(f'received from iphone: registering SSID {val}')
        #string sent must be SSID=xxxPW=yyy where xxx is the SSID and yyy is password
        #PW+ maybe omited
        if val[0] == '':  #this means we received a request/command from ios (started with SEP)
            #********** WIFI management:
            if val[1] == 'OFF':
                #call wifiwpa method to disconnect from current ssid
                self.mgr.wifi_connect(False)
            elif val[1] == 'ON':
                self.mgr.wifi_connect(True)
            elif val[1] == 'DISCONN':
                self.mgr.disconnect()
            elif val[1] == 'AP2s':
                #version2 sends AP2s and gets a json object back:
                #note: since version never reads APs one by one, self.AP_list is always empty
                #sets the wifi prefix for notification using version 2
                self.notifications.setappVersionWifiPrefix(2)
                mLOG.log("Client requested WiFi network list (AP2s)")
                returned_list = self.mgr.get_list() #go get the list
                temp_AP_list = []
                for ap in returned_list:
                    temp_AP_list.append(ap.msg())
                self.notifications.setNotification('READY2',"wifi")
                mLOG.log(f'READY to send AP List as Json object\n AP List: {temp_AP_list}')
                self.all_APs_dict = {"allAps":temp_AP_list}
                self.notifications.setJsonNotification(self.all_APs_dict,"wifi")
            elif val[1] == 'APs':
                #version 1 of the phone app sends this code: APs
                #after receiving notification READY - it reads the list one by one - with chracteristic read.
                #sets the wifi prefix for notification using version 1
                self.notifications.setappVersionWifiPrefix(1)
                mLOG.log("Client requested WiFi network list (APs)")
                returned_list = self.mgr.get_list() #go get the list
                self.AP_list = []
                for ap in returned_list:
                    self.AP_list.append(ap.msg())
                self.notifications.setNotification('READY',"wifi")
                mLOG.log(f'READY: AP List for ios: {self.AP_list}')
                #this is needed for compatibility with verison 1 of the iphone app
                # ap_connected = self.mgr.wpa.connected_AP
                # if ap_connected != "0000":
                #     self.notifications.setNotification(ap_connected)
            elif val[1].startswith("DEL-"):
                # ssid comes after the first four characters
                ssid_to_delete = val[1][4:]
                self.mgr.request_deletion(ssid_to_delete)
                self.notifications.setNotification('DELETED',"wifi")
                
            
            #*********** LOCK Management:
            elif val[1] == "unknown":
                # this handles the LOCK request which will have been sent encrypted while pi is unlocked
                if self.cryptomgr.crypto:
                    mLOG.log(f"rpi is locked - sending encrypted: {self.cryptomgr.unknown_response}")
                else:
                    mLOG.log(f"RPi is unlocked - sending in clear: {self.cryptomgr.unknown_response}")
                #simulate response did not get there:
                # return
                self.notifications.setNotification(self.cryptomgr.unknown_response,"crypto")
            elif val[1] == "UnlockRequest":
                #notification: - must send response encrypted and then afterwards disable crypto
                self.notifications.setNotification('Unlocking',"crypto")
            elif val[1] == "CheckIn":
                self.notifications.setNotification('CheckedIn',"crypto")
            # *************** extra info: 
            elif val[1] == "infoIP": 
                ips = WifiUtil.get_ip_address()
                self.notifications.setJsonNotification(ips,"wifi")
            elif val[1] == "infoMac": 
                macs = WifiUtil.get_mac()
                self.notifications.setJsonNotification(macs,"wifi")
            elif val[1] == "infoAP": 
                ap = WifiUtil.scan_for_channel()
                self.notifications.setJsonNotification(ap,"wifi")
            elif val[1] == "infoOther": 
                othDict = WifiUtil.get_other_info()
                if othDict is not None:
                    try:
                        #set never_encrypt so it is sent in clear text regardless of crypto status
                        self.notifications.setJsonNotification(othDict,"wifi",True)
                    except:
                        pass
            elif val[1] == "infoAll": 
                ips = WifiUtil.get_ip_address()
                macs = WifiUtil.get_mac()
                ap = WifiUtil.scan_for_channel()
                oth = WifiUtil.get_other_info()
                self.notifications.setJsonNotification(ips,"wifi")
                self.notifications.setJsonNotification(macs,"wifi")
                self.notifications.setJsonNotification(ap,"wifi")
                if oth is not None:
                    try:
                        strDict = {"other":str(oth["other"])}
                        self.notifications.setJsonNotification(strDict,"wifi",True)
                    except:
                        pass

            # *************** Buttons:
            elif val[1] == "HasButtons":
                mLOG.log("setting up button sender")
                self.startSendingButtons()
            elif val[1] == "HasDisplays":
                mLOG.log("setting up User App listener")
                self.startListeningToUserApp()
            # any other "command"  is assumed to be a button click or similar - to send to user app via dbus
            # validate it here first before sending
            elif val[1] == "":
                #blank message would normally be a stale nonce when pi is locked or failed to decrypt
                mLOG.log("received message is blank - ignoring it")

            else:
                try:  #this fails with error if dict key does not exists (ie it is not a button click)
                    button_info_dict = json.loads(val[1])
                    if "code" in button_info_dict and "data" in button_info_dict:
                        self.sender.send_signal(val[1])
                    else:
                        mLOG.log(f'Invalid SSID string {val}')
                except: #this catch error on decoding json
                    mLOG.log(f'Invalid SSID string {val}')
                return
            
        #************ SSID connection management
       
        else:
            try:
                mLOG.log(f'received requested SSID for connection: {val}')
                self.current_requested_ssid = val[0]
                self.current_requested_pw = val[1]
                network_num = -1
                #if user is connecting to an existing network - only the SSID is passed (no password) 
                #   so network number is unknown (-1)
                if self.current_requested_ssid: 
                    #Add Specific Codes and corresponding calls here.
                    if self.current_requested_ssid == self.phone_quitting_message["ssid"] and self.current_requested_pw == self.phone_quitting_message["pw"]:
                        #user is ending BT session -  set up ending flag and wait for disconnection
                        Blue.user_requested_endSession = True
                        #return correct notification to signify to phone app to start disconnect process:
                        self.notifications.setNotification(f'3111{self.phone_quitting_message["ssid"]}',"wifi")
                        return
                    #normal code to connect to a ssid
                    mLOG.log(f'about to connect to ssid:{self.current_requested_ssid}, with password:{self.current_requested_pw}')
                    connected_ssid = self.mgr.request_connection(self.current_requested_ssid,self.current_requested_pw)
                    if len(connected_ssid)>0:
                        mLOG.log(f'adding {connected_ssid} to notifications')
                        self.notifications.setNotification(connected_ssid,"wifi")
                    else:
                        mLOG.log(f'adding FAIL to notifications')
                        self.notifications.setNotification('FAIL',"wifi")
            except Exception as ex:
                mLOG.log("EERROR - ",ex)
                

class InfoCharacteristic(Characteristic):
    def __init__(self, index,service):
        Characteristic.__init__(self, index,UUID_INFO,["read"], service)
        self.add_descriptor(InfoDescriptor(0,self))
        self.mainloop = service.main_loop

    def convertInfo(self,data):
        #this is only use for logging 
        msg = ""
        try: 
            prefix = data.decode("utf8")
        except:
            prefix = ""
        if prefix == "NoPassword": return "NoPassword"

        try:
            prefix = data[0:4].decode("utf8")
        except:
            prefix = ""
        if prefix == "LOCK" and len(data)>17:
            msg = prefix
            msg += str(int.from_bytes(data[4:16], byteorder='little', signed=False))
            msg += data[16:].hex()
            return msg
        if  len(data)>13:
            msg = str(int.from_bytes(data[0:12], byteorder='little', signed=False))
            msg += data[12:].hex()
        return msg


    def ReadValue(self, options):
        mLOG.log("Reading value on info chracteristic")
        value = []
        msg_bytes = self.service.cryptomgr.getinformation()
        for b in msg_bytes:
            value.append(dbus.Byte(b))
        mLOG.log(f'ios is reading PiInfo: {self.convertInfo(msg_bytes)}')
        return value


class InfoDescriptor(Descriptor):
    INFO_DESCRIPTOR_UUID = "2901"
    INFO_DESCRIPTOR_VALUE = "Pi Information"

    def __init__(self, index, characteristic):
        Descriptor.__init__(
                self, index, self.INFO_DESCRIPTOR_UUID,
                ["read"],
                characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.INFO_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))
        return value

class WifiDataCharacteristic(Characteristic):

    def __init__(self, index,service):
        self.notifying = False
        self.last_notification = -1
        Characteristic.__init__(self, index,UUID_WIFIDATA,["notify", "read","write"], service)
        self.add_descriptor(InfoWifiDescriptor(0,self))
        self.mainloop = service.main_loop


    def info_wifi_callback(self):
        '''
        mainloop checks here to see if there is something to "notify" iphone app
        note: ios expects to see the SEPARATOR prefixed to notification - otherwise notification is discarded
        why is Unlocking the pi done here?
            - when pi is locked and user request to unlock - pi will reply with "crypto:unlocking"
            - but this msg must be sent encrypted (iphone app expects it encrypted: only when received will it confirm unlock and stop encryting)
            therefore after msg is sent whit encryption, only then is crypto disabled on the pi.
        '''
        if self.notifying:
            while len(self.service.notifications.notifications)>0:
                thisNotification_bytes = self.service.notifications.notifications.pop(0)
                #notification is in bytes, already has prefix separator and may be encrypted
                needToUnlock = thisNotification_bytes == self.service.notifications.unlockingMsg
                value=[]
                for b in thisNotification_bytes:
                    value.append(dbus.Byte(b))
                self.PropertiesChanged("org.bluez.GattCharacteristic1", {"Value": value}, [])
                mLOG.log('notification sent')
                if needToUnlock:
                    self.service.cryptomgr.disableCrypto()
                    break 
                
        return self.notifying

    def StartNotify(self):
        mLOG.log(f'ios has started notifications for wifi info')
        self.service.notifications.reset()
        if self.notifying:
            return
        self.notifying = True
        self.service.user_ending_session = False
        self.add_timeout(NOTIFY_TIMEOUT, self.info_wifi_callback)

    def StopNotify(self):
        mLOG.log(f'ios has stopped notifications for wifi info')
        self.service.notifications.reset()
        self.notifying = False

    def ReadValue(self, options):
        #ios will read list of ap messages until empty
        value = []
        msg = SEPARATOR+'EMPTY' #ios looks for separator followed by empty to indicate list is over (EMPTY could be an ssid name...)
        #mLOG.log(f'ios reading from {self.service.AP_list}')  
        if len(self.service.AP_list)>0:
            msg = self.service.AP_list.pop(0)

        msg_bytes = self.service.cryptomgr.encrypt(msg)
        for b in msg_bytes:
            value.append(dbus.Byte(b))
        mLOG.log(f'ios is reading AP msg: {msg}')
        return value

    def WriteValue(self, value, options):
        #this is called by Bluez when the client (IOS) has written a value to the server (RPI)
        """
        messages are either:
             - SEP + command (for controling wifi on pi or asking for AP list)
             - ssid only (no SEP)
             - ssid + SEP + NONE : indicates an open network that does not need a password
             - ssid + SEP + password + SEP + code    code = CP: call change_password; =AD: call add_network
        returns [first_string,second_string]
        everything that arrives before SEP goes into first_string
        everything that arrives after SEP goes into second string
        for requests/commands:  first_string is empty and request is in second string
        if first_string is not empty: then it is an SSID for connection 
            which may or may not have a password in second string
        """
        received=['','']
        index = 0
        value_python_bytes = bytearray(value)
        value_d = self.service.cryptomgr.decrypt(value_python_bytes)
        bytes_arr = value_d.split(SEPARATOR_HEX)
        received = []
        for bb in bytes_arr:
            received.append(bb.decode("utf8"))
        # for val in value_d:
        #     if val == SEPARATOR_HEX:
        #         index += 1
        #     else:
        #         received[index]+=str(val)
        #case where only ssid has arrived (no password because known network)
        if len(received) == 1 : 
            received.append("") #ensure at least two elements in received
        mLOG.log(f'from iphone received SSID/PW: {received}')
        from ..utils.config import ConfigData
        ConfigData.reset_timeout()  # any data received from iphone resets the BLE Server timeout
        self.service.register_SSID(received)

class InfoWifiDescriptor(Descriptor):
    INFO_WIFI_DESCRIPTOR_UUID = "2901"
    INFO_WIFI_DESCRIPTOR_VALUE = "AP-List, Status, write:SSID=xxxPW=yyy"

    def __init__(self, index, characteristic):
        Descriptor.__init__(
                self, index, self.INFO_WIFI_DESCRIPTOR_UUID,
                ["read"],
                characteristic)

    def ReadValue(self, options):
        value = []
        desc = self.INFO_WIFI_DESCRIPTOR_VALUE

        for c in desc:
            value.append(dbus.Byte(c.encode()))
        return value
