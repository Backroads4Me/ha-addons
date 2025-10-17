
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import padding
from cryptography import exceptions as crypto_exceptions

from ..utils.logger import mLOG
from .utils import NonceCounter

class AndroidAES:
    @staticmethod
    def encrypt(plaintext, key,nonce_counter):
        # Generate a random 16-byte IV
        iv = nonce_counter.padded_bytes
        
        # Create a padder
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext) + padder.finalize()
        
        # Create an encryptor
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        # Encrypt the padded data
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        # print(''.join('{:02x}'.format(x) for x in ciphertext))
        #always return a 12 byte nonce (to match chachapoly implementation
        return nonce_counter.bytes + ciphertext

    @staticmethod
    def decrypt(ciphertext, key):
        # Extract the IV (first 12 bytes)
        iv = ciphertext[:12]
        iv += bytes.fromhex("00000000")  #cypher text arrives with 12 bytes nonce - pad it to 16
        ciphertext = ciphertext[12:]
        
        # Create a decryptor
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        
        # Decrypt the ciphertext
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Create an unpadder
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_data) + unpadder.finalize()
        return plaintext

class BTCrypto:
    """
    class to encrypt a string or decrypt a cypher (bytes) using ChaCha20Poly1305 
    initialise it with the password (read from disk)
    password is hashed here to make key
    always pass NonceCounter instance to encrypt or decrypt:
        encrypt will increment counter to get the next nonce for encryption
        decrypt will record last_nonce (received) if message is decoded correctly
    note: nonce_counter is single instance maintained by BtCryptoManager - which is instantiated at start

    Android vs iOS:
    iOS was developped first using the latest encryption (Chacha20Poly1305)
    Android: some of the older devices do not have access to ChaCha... so AES is used instead.
    Since iOS App is already published, ChaCha... needs to be supported.
    Since the code always react to a request from phone device, decrypt is always called first,
        follwed by an encrypted response (Notification).
    To support both encryption, when an encrypted message is received, both encryption are tried (iOS first):
        - if they both fail we raise an exception (as before android)
        - if one passes, the flag "useAES" is set accordingly.
        note:   the flag useAES is store with nonce counter - which is instantiated only once.  
                it cannot be sotred in BTCrypto since this class is re-instantiated everytime the encryption changes.
        - when the encryption is then used for the response, it selects the correct encryption based on this flag.
        - Note: the flag is set every time a decryption occur so the following encryption(s) always match.
    This will however cause problem if two devices of different type (one iOS, one Android) connect at the same time:
        Since notifications go to all devices registered, the device that is idle while the other request and encrypted action,
        will received an encrypted message it cannot decrypt, and assume that it's password is stale:
            - it will disconnect
            - it will erase the password from the device.
            - it will warn the user asking for the password.
                - if user enters the password, this will be sent to the RPi, and be accepted, but the response
                will go the the previous device, which will then see an undecryptable message and disconnect as well 
            - users will basically block each other until one stops entering the password.
    A notice will be provided on the blog to explain that multiple devices of diffrent types connecting at the same time is not suppported.
    """

    def __init__(self,pw):
        self.password = pw
        self.hashed_pw = self.makeKey256(pw)

    def makeKey256(self,key):
        m = hashes.Hash(hashes.SHA256())
        m.update(key.encode(encoding = 'UTF-8', errors = 'strict'))
        return m.finalize()
    
    def encryptForSending(self,message,nonce_counter):
        #none_counter of type NonceCounter
        mLOG.log(f'current nonce is: {nonce_counter.num_nonce}')
        nonce_counter.next_even()
        nonce = nonce_counter.bytes
        if nonce_counter.useAES:
            #mLOG.log(f'encrypting with AES')
            return AndroidAES.encrypt(message.encode('utf8'),self.hashed_pw,nonce_counter)
        else:
            #IOS uses chachapoly
            #mLOG.log(f'encrypting with ChaCha')
            chacha = ChaCha20Poly1305(self.hashed_pw)
            ct = chacha.encrypt(nonce, message.encode(encoding = 'UTF-8', errors = 'strict'),None)
            return nonce+ct 
        
    def decryptAES(self,cypher,nonce_counter):
        try:
            nonce_bytes = cypher[0:12]
            message = AndroidAES.decrypt(cypher,self.hashed_pw) 
            if not nonce_counter.useAES: mLOG.log(f'AES encryption detected') # only warn if changing encryption
            nonce_counter.useAES = True
            if nonce_counter.checkLastReceived(nonce_bytes) :return message
            #if nonce was stale return a blank message which will be ignored
            return b""
        except Exception as ex: 
            mLOG.log(f"crypto decrypt error (AES): {ex}")
            raise ex

    def decryptChaCha(self,cypher,nonce_counter):
        #combined message arrives with nonce (12 bytes first)
        #this returns the encode message as utf8 encoded bytes -> so btwifi characteristic can process them as before - including SEPARATOR 
        #raise the error after printing the message - so it is caught in the calling method

        #************ below is for ios chachapoly
        nonce_bytes = cypher[0:12]
        ct = bytes(cypher[12:])
        chacha = ChaCha20Poly1305(self.hashed_pw)
        try:
            message = chacha.decrypt(nonce_bytes, ct,None)
            if nonce_counter.useAES : mLOG.log(f'ChaCha encryption detected') #only warn if changing encryption
            nonce_counter.useAES = False
            #checkLastReceived updates the last receive dictionary if nonce is OK (ie not stale)
            if nonce_counter.checkLastReceived(nonce_bytes) : return message
            #if nonce was stale return a blank message which will be ignored
            return b""
        except crypto_exceptions.InvalidTag as invTag:
            mLOG.log("crypto Invalid tag - cannot decode")
            raise invTag
        except Exception as ex: 
            mLOG.log(f"crypto decrypt error(ChaCha): {ex}")
            raise ex
        
    def decryptFromReceived(self,cypher,nonce_counter):
        #always try the previous known encryption most use case only have one phone connected
        #mLOG.log(f"current decryption with  {'AES' if nonce_counter.useAES else 'ChaCha'}")
        if nonce_counter.useAES:
            mLOG.log("decrypting attempt with AES")
            try:
                encBytes = self.decryptAES(cypher,nonce_counter)
            except Exception as ex:
                try:
                    mLOG.log("decrypting attempt Failed with AES - trying ChachaPoly")
                    encBytes = self.decryptChaCha(cypher,nonce_counter)
                except:
                    raise ex
        else:
            mLOG.log("decrypting attempt with ChachaPoly")
            try:
                encBytes = self.decryptChaCha(cypher,nonce_counter)
            except Exception as ex2:
                try:
                    mLOG.log("decrypting attempt Failed with AES - trying AES")
                    encBytes = self.decryptAES(cypher,nonce_counter)
                except:
                    raise ex2
        return encBytes
