
from threading import Timer

from ..utils.logger import mLOG
from .utils import PiInfo, NonceCounter
from .core import BTCrypto

class RequestCounter:

    def  __init__(self):
        self.kind = "normal"  # also use "garbled" and "lock_request"
        self.val = 0

    def _setCounterGarbled(self):
        self.kind = "garbled"
        self.val = 0

    def _setCounterRequest(self):
        self.kind = "lock_request"
        self.val = 0

    def incrementCounter(self,what_kind):
        #always increment counter before taking action/checking max
        #return True if maximum has been reached
        max_garbled = 2 #number of allowable tries
        max_request = 3 #number of allowable tries
        if self.kind == "normal": 
            if what_kind == "garbled": self._setCounterGarbled()
            if what_kind == "lock_request": self._setCounterRequest()
            return False
        self.val += 1
        if self.kind == "garbled": return self.val > max_garbled
        if self.kind == "lock_request": return self.val > max_request

    def resetCounter(self):
        self.kind = "normal"
        self.val = 0

    
class BTCryptoManager:
    """
    meant to be a singleton instantiated when code starts
    code is untested with multiple connections - but if multiple connections are allowed
    BTCryptoManager is available to all connections which implies:
        - if RPi is locked and requires encryption - it applies to all connection
        - if RPi is unlocked - all connections communicate in clear until any of the connection locks the RPI

    when RPi receives a crypted message while unlocked, or a garbled message while locked:
        - the decrypting method will automatically call the unknown() method - to process it and decide the response
            adn stores it in the unknown_response property
        - it will return unknown as decrypted message so Chracteristic can process it and call the register_ssid() on its service.
        - when the service sees this "unknown" - it fetches the response for the processed cypher in the
            unknown_response property and send it via notification.
    """

    def __init__(self):
        self.unknown_response = ""
        self.timer = None
        self.request_counter = RequestCounter()
        self.pi_info = PiInfo()
        self.nonce_counter = NonceCounter(self.pi_info.last_nonce)
        self.quitting_msg = ""
        if self.pi_info.locked and self.pi_info.password is not None: 
            self.crypto = BTCrypto(self.pi_info.password)
        else:
            self.crypto = None

    def setPhoneQuittingMessage(self,str):
        self.quitting_msg = str

    def startTimer(self):
        mLOG.log("starting timer")
        if self.timer is not None:
            self.timer.cancel()
        try:
            self.timer = Timer(20.0,self.closeBTConnection)
        except Exception as ex:
            mLOG.log(f"timer not started: {ex}")

    def closeBTConnection(self):
        mLOG.log("timer hit btdisconnect - no action implemented yet")
        pass

    def getinformation(self):
        if self.pi_info.password == None:
            mLOG.log("pi info has no password")
            return "NoPassword".encode()
        rpi_id_bytes = bytes.fromhex(self.pi_info.rpi_id)
        mLOG.log(f"pi info is sending nonce: {self.nonce_counter.num_nonce}")
        nonce_bytes = self.nonce_counter.num_nonce.to_bytes(12, byteorder='little')
        if self.pi_info.locked:
            x = "LOCK".encode() #defaults to utf8
            return x+nonce_bytes+rpi_id_bytes
        else:
            return  nonce_bytes+rpi_id_bytes
            
    
    def unknown(self,cypher,alreadyDecrypted = b""):
        """
        call this when a message is not recognized:
            - if RPi is unlocked - could be receiving an encrypyed lock request
            - any message that is not in the list
            - if RPI is locked - could be bluetooth connection garbled

        return string message that fit the request and the state - to be sent in Notification 
        """
        #check if receiving encrypted lock request
        if  not self.pi_info.locked:
            if self.pi_info.password is None: 
                self.unknown_response = "NoPassword"
                return
            #go to lock state to decrypt:
            self.pi_info.locked = True
            self.crypto = BTCrypto(self.pi_info.password)
            if alreadyDecrypted == b'\x1eLockRequest':
                msg = alreadyDecrypted
            else:
                try: 
                    #message is bytes
                    msg = self.crypto.decryptFromReceived(cypher,self.nonce_counter)
                except:
                    msg = b""

            if msg == b'\x1eLockRequest':  
                #decryption is correct - save lock state and return "locked" encrypted
                self.pi_info.saveInfo()
                self.request_counter.resetCounter()
                self.unknown_response = "Locked"
            else:
                #always reset pi to unlock mode unless message above was decoded as "LockRequest""
                #this ensures next password try will come back to this block (pi is not locked) 
                self.pi_info.locked = False
                self.crypto = None
                self.unknown_response = "Unlocked"
                reached_max_tries = self.request_counter.incrementCounter("lock_request")
                #in theory we RPi should not see a 4th request because iphone should close connection - but just in case:
                mLOG.log(f"unknown encrypted is not lock request: max tries is  {reached_max_tries}")
                if reached_max_tries:
                    #do not disconnect yet - normally App will send a disconect message in clear
                    #but start timer to catch rogue app DDOS this pi
                    self.startTimer()
                # else:  TODO: decide if a timer is needed when user still has tries left...
                #     self.startTimer()
                   
                
        #if this is called while pi is locked - it means messages is garbled (or an unknown key word)
        else:
            reached_max_tries = self.request_counter.incrementCounter("garbled")
            #in theory  RPi should not see a 3rd request because iphone should close connection - but just in case:
            if reached_max_tries:
                if self.timer is not None: 
                    self.timer.cancel()
                    self.timer = None
                self.closeBTConnection()
            else:
                self.startTimer()
                self.unknown_response = "Garbled" + str(self.request_counter.val)

        
    
    def disableCrypto(self):
        """
        this is called if user is already using encryption (RPI is locked)
        and has requested the correct bluetooth code : "UnLock"

        """
        if self.pi_info.locked:
            self.pi_info.locked = False
            self.crypto = None
            #always save when going to unlocked.
            self.pi_info.saveInfo()

    def saveChangedPassword(self,):
        """
        password cannot be changed through the app.
        only user with ssh credential/RPi password can change password
        when app implements ssh - then this can be implementated
            - password will have to arrive through the app's ssh channel (not yet implemented)
        """
        pass


    def encrypt(self,message):
        #message is a string
        #returns bytes ready to be sent
        if self.crypto == None: 
            return message.encode('utf8')
        else:
            cypher = self.crypto.encryptForSending(message,self.nonce_counter)
            self.pi_info.last_nonce = self.nonce_counter.num_nonce
            return b'\x1d'+cypher

    def decrypt(self,cypher,forceDecryption = False):
        #returns a string from the bytes received by bluetooth channel
        if self.crypto == None and not forceDecryption: 
            try:
                #check if it can be decoded  with utf8 (it should be unless iphone is sending encrypted messages and pi is unlocked)
                clear = cypher.decode() # defaults to utf8 adn strict error mode - should fail if encrypted msg
                self.unknown_response = ""
            except: 
                #probably - cannot decode because a phone is sending encrypted unaware that another has unlocked the pi
                #let the pi handle the message if the phone has correct password
                mLOG.log("While unlock received apparent encrypted msg - decrypting...")
                return self.decrypt(cypher,True)
            mLOG.log(f" received cleat text: {clear}")
            return cypher
        else:
            try:
                #if error in decrypting - it is caught below
                #if come here because pi is already locked, self.crypto is already set, if not - need to set it:
                if forceDecryption: self.crypto = BTCrypto(self.pi_info.password)
                #mLOG.log( f"decryption is using password {self.pi_info.password}")
                msg_bytes = self.crypto.decryptFromReceived(cypher,self.nonce_counter)
                #since this could be a retry message while in garbled process, which is now OK:
                if self.timer is not None:
                    self.timer.cancel
                    self.timer = None
                    self.request_counter.resetCounter()
                    self.unknown_response = ""
                if  msg_bytes.decode(errors="ignore") == self.quitting_msg:
                    self.nonce_counter.removeIdentifier(cypher[0:12])
                if forceDecryption: 
                    #special case: user is trying to lock the Pi (which is unlocked) and has correct password
                    #not exception caught on first pass (that called unkonwn) since aboved called decrypt again with forceDecryption
                    if msg_bytes == b'\x1eLockRequest':
                        mLOG.log("received LockRequest - processing ...")
                        #can't let unknown try to decrypt the same message twice - it will be stale...
                        # so pass the decrypted message to unknown as alreadyDecrypted
                        self.crypto = None
                        self.pi_info.locked = False
                        self.unknown(cypher,msg_bytes)
                        return b'\x1e'+"unknown".encode()  
                    else:    
                        self.pi_info.locked = False
                        self.crypto = None

                return msg_bytes
            except:
                #in case of inability to decode due to garbled channel or if lock - wrong password, 
                #automatically send to unknown() method - which will set the correct response in
                # in property unknown_response as a string 
                self.unknown(cypher)
                if forceDecryption: self.crypto = None
                """
                returning SEP + "unknown" to the calling method (WifiCharacteristic.WriteValue) 
                will pass back the code "unknown" to the WifiSetService.register_SSID method.
                This will serve as directive to WifiSetService.register_SSID method to return the content of 
                this class variable self.unknown_response as a notification back to the iphone app.
                """
                return b'\x1e'+"unknown".encode()
