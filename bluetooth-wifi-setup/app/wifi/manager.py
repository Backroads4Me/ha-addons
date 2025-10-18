
import re
import subprocess
import time

from ..utils.logger import mLOG
from .supervisor import SupervisorAPI
from .config import WPAConf, Wpa_Network, AP
from .utils import WifiUtil

class NetworkManager:

    def __init__(self,wifiMgr):
        self.mgr = wifiMgr
        self.supervisor_api = SupervisorAPI()

    def scan(self):
        mLOG.log("Starting WiFi scan via iwlist")
        interface = self.mgr.supervisor_api.interface  # Use the dynamically discovered interface
        access_points = []
        try:
            # Execute the iwlist command
            result = subprocess.run(["iwlist", interface, "scan"], capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                mLOG.log(f"iwlist scan failed: {result.stderr}", level=mLOG.CRITICAL)
                return []

            # Parse the output
            networks = result.stdout.split("Cell ")
            for network in networks[1:]:
                ssid_match = re.search(r'ESSID:"(.*)"', network)
                quality_match = re.search(r'Quality=(\d+)/(\d+)', network)
                encryption_match = re.search(r'Encryption key:(on|off)', network)

                if ssid_match:
                    ssid = ssid_match.group(1)
                    if not ssid or '\\x00' in ssid:
                        continue

                    signal_strength = 0
                    if quality_match:
                        quality = int(quality_match.group(1))
                        total = int(quality_match.group(2))
                        # Convert quality to a 0-5 scale, assuming max quality is around 70
                        signal_strength = min(5, int(quality / (total / 5)) if total > 0 else 0)

                    encrypted = False
                    if encryption_match:
                        encrypted = (encryption_match.group(1) == 'on')

                    access_points.append({
                        'ssid': ssid,
                        'signal': signal_strength,
                        'encrypt': encrypted
                    })
            mLOG.log(f"Scan found {len(access_points)} networks")
        except FileNotFoundError:
            mLOG.log("'iwlist' command not found. Please ensure 'wireless-tools' is installed.", level=mLOG.CRITICAL)
        except Exception as e:
            mLOG.log(f"An error occurred during iwlist scan: {e}", level=mLOG.CRITICAL)
        
        return access_points
    
    def request_deletion(self,ssid):
        """
        Delete network configuration via Supervisor API.
        Note: Supervisor manages entire interface config, so deletion means removing from known networks list.
        User will need to enter password to connect again.
        """
        # With Supervisor API, we don't manage individual connection profiles
        # Just remove from our internal known networks list
        network_names = self.mgr.wpa.get_network_name(ssid)
        if network_names is not None:
            for network_name in network_names:
                if network_name in self.mgr.wpa.wpa_supplicant_ssids:
                    del self.mgr.wpa.wpa_supplicant_ssids[network_name]
                    mLOG.log(f"Removed {ssid} from known networks list")
        # The phone app will call (AP2s) to get the updated list
        
    



    def request_connection(self,ssid,pw):
        """  notes on pw:
            - blank:  connecting to known network: just call "up"
            - the string "NONE":  new network - connecting to OPEN: call connect with blank password
            - some text:  new network, possibly hidden: call connect with password
        """
        ssid_in_AP,ssid_in_wpa = self.mgr.where_is_ssid(ssid)
        known_network = self.mgr.wpa.getNetwork(ssid)
        mLOG.log(f'requesting connection with ssid:{ssid} in AP:{ssid_in_AP}  in wpa:{ssid_in_wpa} with pw: {pw}')
        if ssid_in_AP:
            if ssid_in_wpa and (known_network is not None):
                if len(pw) > 0:
                    #known network - changing pw 
                    self.connect(known_network,pw)
                else:
                    #just connect to known network (internally will use stored password)
                    self.connect(known_network,"")
            else:
                # connecting to a new network
                usePw = pw
                if pw == "NONE":
                    #user is expecting to connect to an open network
                    # this catches the case where user is trying to connect to a locked network where the password is actually "NONE"
                    for ap in self.mgr.list_of_APs:
                        #verify that ssid in the scanned AP list is an unlocked network - change "NONE" to blank ""
                        if ap.ssid == ssid and ap.locked == False:
                            usePw = ""
                new_network = Wpa_Network(ssid,usePw!="")
                if new_network is not None:
                    self.connect(new_network,usePw,True)  #is_new
        else: 
            #ssid is not in AP_list - user as entered the name of a hidden ssid
            if ssid_in_wpa and (known_network is not None):
                # note: this case should not happen since Network manager would have seen the known network with hidden ssid in the scan and placed it in the AP_list
                #if user has already connected in this session, disconnected and now reconnects
                #   pw = "" - so just bring connection up like a normal existing known network
                if pw == "" :
                    self.connect(known_network,"",False,True)
                #if network exists (it's in: ssid_in_wpa is true) 
                #but user is connecting for first time in this session, pw is some text
                # if user is trying to connect to a hidden open network - password will be blank in the iphone textbox 
                #     and it arrives here as pw: NONE - treat it as new network so create hidden network is called from connect:
                else:
                    # here we cannot catch a hidden ssid with password actually = "NONE" - NONE is always interpreted as an open network
                    usePw = "" if pw == "NONE" else pw 
                    self.connect(known_network,usePw,True,True) #is_new and is_hidden
                """if previous version of this ssid was open and is now locked, or vice-versa
                    may create a new network: we don;t want that - code is written for only one 
                    network per ssid.  So remove it before re creating it.
                """
            else:
                usePw = "" if pw == "NONE" else pw 
                new_network = Wpa_Network(ssid,usePw!="")
                self.connect(new_network,usePw,True,True)

        #at this point, if connection was made, wpa list was updated, connected_network and connected_AP is set 
        # and config was saved to file (by connect method).
        # return the connected AP message to ios where it will compared to previous connection to decide if attempt worked or not
        return(self.mgr.wpa.connected_AP)

    def connect(self,network,pw,is_new=False, is_hidden=False):
        """
        Connect to a WiFi network via Supervisor API.
        Handles:
            - New networks
            - Existing networks (reconnection)
            - Password changes
            - Hidden SSIDs
        """
        mLOG.log(f'Connecting to SSID:{network.ssid}, is_new:{is_new}, is_hidden:{is_hidden}')

        # Determine authentication mode
        auth_mode = "open" if pw == "" else "wpa-psk"

        # Call Supervisor API to configure and connect
        success, error = self.supervisor_api.update_interface(
            ssid=network.ssid,
            password=pw,
            auth_mode=auth_mode,
            hidden=is_hidden
        )

        if not success:
            mLOG.log(f"Connection failed: {error}", level=mLOG.INFO)
            return False

        mLOG.log(f'Successfully connected to {network.ssid}')

        # Update internal state - add to known networks if new
        if is_new:
            # Use SSID as network name (Supervisor doesn't use separate connection names)
            network.network_name = network.ssid
            self.mgr.wpa.wpa_supplicant_ssids[network.ssid] = network
            mLOG.log(f'Added {network.ssid} to known networks list')

        # Set as connected network (this also updates connected_AP)
        self.mgr.wpa.connected_network = network
        return True

    # Note: create_network() removed - Supervisor API handles network creation in update_interface()

    def remove_known_network(self,known_network):
        '''
        Remove a known network from the internal known networks list.
        With Supervisor API, we manage via the interface configuration.
        '''
        mLOG.log(f'Removing known network: {known_network.ssid}')

        # Remove from internal known networks directory
        if known_network.network_name in self.mgr.wpa.wpa_supplicant_ssids:
            del self.mgr.wpa.wpa_supplicant_ssids[known_network.network_name]

        # Return False for is_hidden (Supervisor API doesn't track this separately)
        return False

    def disconnect(self):
        '''Disconnect from current WiFi network via Supervisor API'''
        mLOG.log("Disconnecting from WiFi via Supervisor API")
        success, error = self.supervisor_api.disconnect_interface()
        if not success:
            mLOG.log(f"Disconnect failed: {error}", level=mLOG.INFO)
        else:
            mLOG.log("Successfully disconnected from WiFi")

class WpaSupplicant:

    def __init__(self,wifiMgr):
        self.mgr = wifiMgr

    def scan(self):
        """ typical result
        bssid / frequency / signal level / flags / ssid
        10:06:45:e5:01:a0	2462	-42	[WPA2-PSK-CCMP][WPS][ESS]	BELL671
        fa:b4:6a:09:02:e7	2462	-46	[WPA2-PSK-CCMP][WPS][ESS][P2P]	DIRECT-E7-HP ENVY 5000 series
        24:a4:3c:f0:44:05	2432	-55	[ESS]	Solar
        """
        found_ssids = []
        out = subprocess.run("wpa_cli -i wlan0 scan", 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        time.sleep(1)
        out = subprocess.run("wpa_cli -i wlan0 scan_results", 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        #this grabs the sign of the dbm strength
        #     this regex was taking ssid only up to first space:
        #     ssids = re.findall(r"[^	]+\s+\d+\s+(-?\d+)\s+([^	]+)\t+(\b[^	]+)", out,re.M)
        #this regex takes everything after the encryption brackets [xxx] - includes spaces in ssid
        ssids = re.findall(r"[^	]+\s+\d+\s+(-?\d+)\s+([^	]+)\t+(.+)", out,re.M)  
        for strength,encryption,ssid in ssids:
            if '\x00' not in ssid:
                try:
                    signal_strength = WifiUtil.signal(int(strength))
                except Exception as e:
                    mLOG.log(f'ERROR: {e}')
                    signal_strength = 0
                found_ssids.append({'ssid':ssid, 'signal':signal_strength, 'encrypt':'WPA' in encryption})
        return found_ssids

    def request_deletion(self,ssid): 
        """
            delete the network from network manager.
            use with care: once done, password that was stored with the network is gone
            User will need to enter password to connect again
        """
        # get the network
    
        try:
             network_to_delete = self.mgr.wpa.wpa_supplicant_ssids[ssid]
             self.remove_known_network(network_to_delete)
        except KeyError:
            # fails silently - no delete action is taken
            pass
        #IMPORTANT:
        #at this point, the netwrok still exists in the list of known networks wpa_supplicant_ssids
        # it is the responsibility of the phone app to call (AP2s) to get the list updated.
        #ALSO:  if SSID appears more than oncein the conf file, 
        #       only the last SSID (ast network number) will have been deleted


    def request_connection(self,ssid,pw):
        ssid_in_AP,ssid_in_wpa = self.mgr.where_is_ssid(ssid)
        mLOG.log(f'entering request - ssid:{ssid} in AP:{ssid_in_AP}  in wpa:{ssid_in_AP}')
        known_network = self.mgr.wpa.getNetwork(ssid)
        if ssid_in_AP:
            if ssid_in_wpa and (known_network is not None):
                mLOG.log(f'requesting known network {ssid}')
                if len(pw) > 0:
                    mLOG.log(f'entered password {pw} - calling change password')
                    if self.changePassword(known_network,pw):
                        self.connect(known_network)
                else:
                    mLOG.log(f'arrived with no password - nothing to change - connecting')
                    self.connect(known_network)
            else:
                mLOG.log(f'ssid was scanned {ssid} - new network with password: {pw}')
                new_network = self.add_network(ssid,pw)
                if new_network is not None:
                    self.connect(new_network,True)
        else:
            #ssid is not in AP_list - user as entered a hidden ssid
            if ssid_in_wpa and (known_network is not None):
                mLOG.log(f'hidden ssid {ssid} not scanned - but is a known network - calling change password always - password: {pw}')
                #change password stored (even if it might be right in the file) - ensure scan_ssid is set for it
                if self.changePassword(known_network,pw,True):
                        self.connect(known_network)
            else:
                mLOG.log(f'hidden ssid {ssid} not scanned and is Unknown: make new network and connect - paaword is: {pw} ')
                new_network = self.add_network(ssid,pw,True)
                if new_network is not None:
                    self.connect(new_network,True,True)

        #at this point, if connection was made, wpa list was updated, connected_network and connected_AP is set
        # and config was saved to file (by connect method).
        # return the connected AP message to ios where it will compared to previous connection to decide if attempt worked or not
        return(self.mgr.wpa.connected_AP)
    
    def connect(self,network,is_new=False, is_hidden=False):
        """ attempts connection to wpa_network passed
        if succesful, update the self.connected_network object then returns True
        if not - attempts to reconnect to previously self.connected_network ; if successful, returns False
        if cannot reconnect to previous: sets conected_object to empty Wpa_Network object, and returns false
        always save_config before returning - to reset the enabled falgs that wpa_cli creates 
        is_new: indicates the passed network came from the "other networks" list in ios and is not currently in the wpa list
            so add it if connection is successful, remove it from wpa_cli if not.
        is_hidden is only used when the network is new - it triggers adding the network to list_of_APs
        """

        mLOG.log(f'entering connect with network ssid:{network.ssid} number: {network.number}, is_new:{is_new}, is_hidden: {is_hidden}')
        connection_attempt = False
        #for testing
        # time.sleep(5)
        # self.mgr.wpa.connected_network = self.mgr.wpa.wpa_supplicant_ssids[network.ssid] # make it the connected network
        # return True

        #attempt to connect to the requested ssid
        ssid_network = str(network.number)
        mLOG.log(f'connecting to: {network.ssid} number:{ssid_network} new network is: {is_new}')
        connected = self.connect_wait(ssid_network)
        mLOG.log(f'requested ssid {network.ssid} connection status = {connected} ')
        if not connected:
            if is_new:
                #remove the network from the wpa_cli configuration on the pi -(but was not saved to file)
                out = subprocess.run(f"wpa_cli -i wlan0 remove_network {ssid_network}", 
                                    shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                mLOG.log(f'removing new network {network.ssid} from wpa_cli current configuration: {out}')
            else: # any password change / change of psk should not be saved - best way is to reload wpa_supplicant.conf file
                  # which at this point matches wpa list anyway (any previous successful connection would have persisted changes to that file via save_config.)
                out = subprocess.run(f"wpa_cli -i wlan0 reconfigure", 
                                    shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                mLOG.log(f'reloading supplicant conf file with wpa_cli: {out}')
            #attempt to reconnect to previously connected network - if there was one:
            if len(self.mgr.wpa.connected_network.ssid)>0:
                connected = self.connect_wait(str(self.mgr.wpa.connected_network.number))
                mLOG.log(f're-connection to initial network {self.mgr.wpa.connected_network.ssid} connection status = {connected} ')
                if  not connected:
                    self.mgr.wpa.connected_network = Wpa_Network('')

        else: #connection was succesful
            if is_new:
                self.mgr.wpa.wpa_supplicant_ssids[network.ssid] = network #add new network to wpa list
                mLOG.log(f'added {network.ssid} to wpa list')
                if is_hidden:
                    # the ssid was not seen in scan so not added to list_of_APs - doing so here makes it look like wpa_supplicant now has seen it
                    # this is not sent back to ios unless it asks for it.  
                    # ios manages its own list - it will show the hidden ssid in known networks for this session only.
                    self.mgr.list_of_APs.append( AP(network.ssid,0,network.locked,True) )  #note: signal does not matter - it will not be used.
                    mLOG.log(f'added {network.ssid} to AP list')

            self.mgr.wpa.connected_network = self.mgr.wpa.wpa_supplicant_ssids[network.ssid] # make it the connected network
            connection_attempt = True

        #if connected: 
            self.mgr.wpa.save_config()
            # if connection was established to new requested ssid or with change password/hidden ssid,
            # we need to save_config so wpa_supplicant.conf file reflects the current live configuration created with wpa_cli.
            # if the connectio_attempt was not successful, but we reconnected to the previous network,
            # wpa_cli select_network will have disabled all other networks in live wpa_cli configuration.  Since however,
            # the wpa_supplicant.conf file was reloaded upon connection_attempt failure, it is save to save_config 
            # (which re-enables all networks except those that were disabled on start of session)  - with the benefit that
            # wpa_cli live config is in in sync with the .conf file on disk.
        mLOG.log(f'Returning connection_attempt: {connection_attempt}')
        return connection_attempt

    def get_psk(self,ssid,pw):
        #SAME
        '''
        Note: this works for WPA/PSK encryption which requires a password of at least 8 characters and less than 63
        if pw = '' it returns the string psk=NONE - which is what wpa_supplicant expects when it is an open network
        always return the string psk=xxxxxxxxxxx...  when xxxxx is the encoded password or NONE
        '''
        psk = ""
        if pw == "NONE": 
            psk = 'psk=NONE' # for open network - ios will pass NONE as password
        if len(pw)>=8 and len(pw)<=63:
            #out = subprocess.run(f'wpa_passphrase {ssid} {pw}',
            out = subprocess.run(["wpa_passphrase",f'{ssid}',f'{pw}'],
                            capture_output=True,encoding='utf-8',text=True).stdout
            temp_psk = re.findall(r'(psk=[^	]+)\s+\}', out, re.DOTALL)
            if len(temp_psk)>0: 
                psk = temp_psk[0]
        mLOG.log(f'psk from get_psk: {psk}')
        return psk

    def changePassword(self,network,pw,hidden=False):
        #SAME
        """returns false if password length is illegal or  if error"""
        try:
            mLOG.log(f'changing Password for  {network.ssid} to  {pw}')
            psk = self.get_psk(network.ssid,pw)
            if len(psk) == 0:
                mLOG.log(f"Password {pw} has an illegal length: {len(psk)}")
                return False

            ssid_num = str(network.number)
            if ssid_num != '-1':
                if psk == "psk=NONE":
                    #change network to open
                    out = subprocess.run(f'wpa_cli -i wlan0 set_network {ssid_num} key_mgmt {psk[4:]}', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                    mLOG.log('set key_mgmt to NONE',out)
                else:
                    # wpa_cli set_network 4 key_mgmt WPA-PSK
                    out = subprocess.run(f'wpa_cli -i wlan0 set_network {ssid_num} key_mgmt WPA-PSK', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                    mLOG.log('set key_mgmt to WPA_PSK',out)
                    out = subprocess.run(f'wpa_cli -i wlan0 set_network {ssid_num} psk {psk[4:]}', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                    mLOG.log('set psk',out)
                if hidden:
                    out = subprocess.run(f'wpa_cli -i wlan0 set_network {ssid_num} scan_ssid 1', 
                                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                    mLOG.log(f'set hidden network with scan_ssid=1: {out}')

                out = subprocess.run(f'wpa_cli -i wlan0 enable_network {ssid_num}', 
                                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                mLOG.log(f'enabling network {out}')
                return True
            else:
                mLOG.log(f'network number for {network.ssid} not set {ssid_num}')
                return False

        except Exception as e:
            mLOG.log(f'Exception: {e}')
            return False
        
    def add_network(self,ssid,pw,hidden=False):
        #SAME
        #not use with Network Manager
        """
        creates a new network with wpa_cli and sets password, encoding and scan_ssid as needed.
        returns a new Wpa_Network with attributes set if successful, None otherwise
        note: it does not add the new_network to wpa list nor save the config.
        allow ios to send password = either NONE or blank (empty string) for open network
        """
        mLOG.log(f'adding network password:{pw}, ssid:{ssid}')
        if len(pw) == 0:
            psk = self.get_psk(ssid,'NONE') # forces open network
        else:
            psk = self.get_psk(ssid,pw)
        if len(psk) == 0:
                mLOG.log(f"Password {pw} has an illegal length: {len(pw)}")
                return None
        network_num=''
        try:
            #this returns the network number
            network_num = subprocess.run(f"wpa_cli -i wlan0 add_network", 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout.strip()
            mLOG.log(f'new network number = {network_num}')
            ssid_hex=''.join([x.encode('utf-8').hex() for x in ssid])
            out = subprocess.run(f'wpa_cli -i wlan0 set_network {network_num} ssid "{ssid_hex}"', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
            mLOG.log(f'coded ssid: {ssid_hex} - setting network ssid {out}')
            if psk == "psk=NONE":
                out = subprocess.run(f'wpa_cli -i wlan0 set_network {network_num} key_mgmt {psk[4:]}', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                mLOG.log(f'set network to Open {out}')
            else:
                out = subprocess.run(f'wpa_cli -i wlan0 set_network {network_num} psk {psk[4:]}', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                mLOG.log(f' set psk: {out}')
            if hidden:    
                out = subprocess.run(f'wpa_cli -i wlan0 set_network {network_num} scan_ssid 1', 
                                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                mLOG.log(f'set hidden network {ssid} scan_ssid=1: {out}')

            out = subprocess.run(f'wpa_cli -i wlan0 enable_network {network_num}', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
            mLOG.log(f'enabling network {out}')

            new_network = Wpa_Network(ssid,psk!='psk=NONE',False,int(network_num))
            mLOG.log(f'created temporary wpa_network {new_network.info()}')

            return new_network

        except Exception as e:
            mLOG.log(f'ERROR: {e}')
            #cleanup if network was added:
            if len(network_num) > 0:
                out = subprocess.run(f'wpa_cli -i wlan0 remove_network {network_num}', 
                            shell=True,capture_output=True,encoding='utf-8',text=True).stdout
            mLOG.log(f'cleaning up on error - removing network: {out}')
            return None

    def connect_wait(self, num, timeout=10):
        #SAME
        """ attempts to connect to network number (passed as a string)
        returns after 5 second + time out with False if connection not established, or True, as soon as it is."""
        p=subprocess.Popen(f"wpa_cli -i wlan0 select_network {num}", shell=True)
        p.wait()
        n=0
        time.sleep(5)
        while n<timeout:
            connected_ssid = subprocess.run(" iwgetid -r", shell=True,capture_output=True,encoding='utf-8',text=True).stdout.strip()
            if len(connected_ssid)>0:
                break
            mLOG.log(n)
            n+=1
            time.sleep(1)
        try:
            msg = f'Wait loop exited after {n+5} seconds with SSID: --{connected_ssid}--\n'
            mLOG.log(msg)
        except Exception as e:
            mLOG.log(f'exception: {e}')
        return len(connected_ssid) > 0

    def remove_known_network(self,known_network):
        #
        network_number_to_remove = known_network.number
        
        #check if network to remove is hidden:

        out = subprocess.run(f'wpa_cli -i wlan0 get_network {known_network.number} scan_ssid', 
                                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        is_hidden = (f'{out}' == "1")
        #this network is a hidden ssid - it will be removed (or will not added) from ap list 
        mLOG.log(f'out={out}| {known_network.ssid} to be removed is hidden?: {is_hidden}')
            
        #remove the network from Network Manager list of Connections on device
        #remove the network from the wpa_cli configuration on the pi -(but was not saved to file)
        out = subprocess.run(f"wpa_cli -i wlan0 remove_network {known_network.number}", 
                                    shell=True,capture_output=True,encoding='utf-8',text=True).stdout
                                    #remove the network from the known network directory
        del self.mgr.wpa.wpa_supplicant_ssids[known_network.ssid]
        #save this config to file:
        self.mgr.wpa.save_config()
        #at this point the network numbers may have changed.
        #best way is to reload wpa_supplicant.conf file
        # which at this point matches wpa list anyway (any previous successful connection would have persisted changes to that file via save_config.)
        out = subprocess.run(f"wpa_cli -i wlan0 reconfigure", 
                             shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        #network numbers should now be in order - retreive them
        self.mgr.wpa.retrieve_network_numbers()
        return is_hidden

    def disconnect(self):
        command_str = "wpa_cli -i wlan0 disconnect"
        out= subprocess.run(command_str, 
                                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        mLOG.log(f'disconnect" {out}')
        

class WifiManager:
    '''
    all methods operate on Wpa_Network objects and the list self.wpa.wpa_supplicant_ssids
    and maitain there status to match what the RPi wpa_cli configuration sees (stay in sync with it)
    This is also true for the Wpa_Netwrok that us currently connected: self.wpa.connected_network (all attributes always up to date)
    On the other hand list_of_Aps is only correct when fetched by ios request - in particular whether a Network is in the supplicant file or not.
    if for example, a new network is connected, it will appear in the self.wpa.wpa_supplicant_ssids list, 
        but in_supplicant attribute of corresponding AP in list of APs is not updated until the list is re-fetched.
        list_of_Aps is never updated unless it is re-fetch - with one exception:
            - if a hiiden ssid is connected to, it will be added to WPA_Conf list and shown to user as a known network.
            - if user comes back to reconnect - the test "is in AP_list" must return true - but it can't if hidden ssid is not added to it
            - hence, exceptionally for new hidden ssid with succesful connections - add the network to the AP_list
    '''

    def __init__(self):
        #Updated for Supervisor API
        self.wpa = WPAConf(self)
        self.list_of_APs=[]
        self.force_new_list = False #set this as a flag to btwifi to force resending the list of Aps to iphone
        self.useNetworkManager = self.network_manager_test()
        if self.useNetworkManager:
            self.operations = NetworkManager(self)
            self.supervisor_api = self.operations.supervisor_api  # Share the API instance
        else:
            self.operations = WpaSupplicant(self)
            self.supervisor_api = None

    def network_manager_test(self):
        #return true if Network manager is running (via Supervisor API)
        # For Home Assistant addons, we always use Supervisor API if available
        # Check if SUPERVISOR_TOKEN environment variable exists
        import os
        has_supervisor_token = bool(os.environ.get('SUPERVISOR_TOKEN', ''))
        if has_supervisor_token:
            mLOG.log("Network Manager (Supervisor API) is available")
            return True
        else:
            mLOG.log("Network Manager (Supervisor API) not available, falling back to wpa_supplicant")
            return False




    def where_is_ssid(self,ssid):
        '''
        this checks if the given ssid was found in scan (ie is in range) and if it is a known network
        returns tupple of boolean: ssid_is_in_AP_list (scanned), ssid_is_in wpa_list (known network)
        note: AP_list in_supplicant may be stale if other network connections occured - AP_list only correct at time it is run
              so always use wpa list to verify if ssid is in known networks - since wpa list is maintianed throughout.
        '''
        in_AP = len([ap for ap in self.list_of_APs if ap.ssid == ssid]) > 0
        in_wpa = self.wpa.isKnownNetwork(ssid)
        return (in_AP,in_wpa)


    def get_list(self):
        #CALLED from service
        #Updated for Supervisor API
        if self.useNetworkManager:
            self.wpa.get_NM_Known_networks(self.supervisor_api)  #this sets list of known networks and connected network if one is connected.
        else:
            self.wpa.get_wpa_supplicant_ssids()
        
        # This builds the list of AP with the flags defined in AP class.
        # Particular case where an SSID is in_supplicant - but the locked status of the AP seen by RPi and the lock status 
        # stored in the wpa_supplicant.conf file do not match:
        # - The network is shown as existing in_supplicant - when the user attemps to connect it will fail 
        #   and the password box will be shown (if going from open to locked).

        info_AP = self.operations.scan()  #loads the list of AP seen by RPi with info on signal strength and open vs locked
        current_ssid = self.wpa.connected_network.ssid
        mLOG.log(f'Info_AP {info_AP}')
        self.list_of_APs=[]
        
        for ap_dict in info_AP:
            try:
                ap = AP()
                ap.ssid = ap_dict['ssid']
                ap.signal = ap_dict['signal']
                ap.locked = ap_dict['encrypt']
                ap.connected = (ap.ssid == current_ssid)
                ap.in_supplicant = False
                known_network = self.wpa.getNetwork(ap.ssid)
                was_hidden = False  #used for known network as flag if they are removed
                if known_network is not None:
                    # for Network manager implementation key is network NAME which may be different than ssid
                    # for wp_supplicant - calling this always return the same as the ssid
                    #test for conflict: whereby the listed in network (in Network mgr or wpa conf file) is locked
                    #       and live network is showing unlocked (or vice-versa)
                    if known_network.locked != ap.locked:
                        #conflict exists - remove network from Netwrok manager or wpa conf file 
                        mLOG.log(f'info: {ap.ssid}: wpa locked:{known_network.locked} ap locked:{ap.locked}')
                        mLOG.log(f'known network {ap.ssid} in conflict - delete and move to unknown networks')
                        was_hidden = self.operations.remove_known_network(known_network)
                        #note: in_supplicant was set False above - so network automatically listed as unknown
                    else : 
                        ap.in_supplicant = True
                #normally was_hidden is left to be false and network (known or not) is added to list_of_Aps
                #if however the network was known and in conflict and is removed from known_list,
                # and if it had been a hidden network at the time - it is not added to the list as an unknown - to be seen and re-clicked by user
                #user will need to re-enter with correct locked/open status as a hidden network
                if not was_hidden:
                    self.list_of_APs.append(ap)
            except Exception as e:
                mLOG.log(f'ERROR: {e}')
        return self.list_of_APs

    def request_deletion(self,ssid):
         #CALLED from Service
         return self.operations.request_deletion(ssid)

    def request_connection(self,ssid,pw):
        #CALLED from Service
        return self.operations.request_connection(ssid,pw)

    def disconnect(self):
        #CALLED from Service
        self.operations.disconnect()
    

    def wifi_connect(self,up = True):
        #Warning: this will only work if .py file(s) are owned by root.  otherwise error message regarding permissions
        #this does not communicate back the result to ios app: app will display radio off/on even if command was denied.
        #The main.py file is copied to container root (/) and owned by root.
        cmd = "/bin/ip link set wlan0 up" if up else "/bin/ip link set wlan0 down"
        msg = "Bring WiFi up" if up else "Bring WiFi down"
        mLOG.log(msg)
        try : 
            r = subprocess.run(cmd, shell=True, text=True, timeout=10)
        except Exception as e:
            mLOG.log("error caught: " + e)
