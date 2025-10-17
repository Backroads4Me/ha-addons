
import re
import subprocess

from ..utils.logger import mLOG
from .supervisor import SupervisorAPI
from .utils import WifiUtil

class Wpa_Network:
    '''
    object describing the network in the wpa_supplicant_file - as it is saved on disk
    it should be managed to always represent what is saved on disk.
    Note: conflict is not saved on disk per se:
        it is a flag that indicates that the lock status what is saved on disk is different 
        than what is seen by the rpi scan 
            i.e.: ssid is locked on disk file but an ssid of the same name is braodcasting as open network.

    Conflicts:
    A conflict exists when a known network stored in the RPi has a given encryption status (ex: Locked/psk) 
        but the current scan shows a different encryption status (ex: open) 
        the ios app will received the scanned value (here open) - but the known network will attempt to connect 
        using the sotred information (in this case locked: psk - password).
    this basically means that the status of the network was changed on the router since the user last connected to it.
    Rather than try to manage all cases of conflicts - the code does simply this:
        - if a conflict between scann vs stored network is found 
            - the stored network is deleted
            - the network is added to the list of unknown networks for the user to reconnect, 
                at which point it will be shown a password box on the ios app, adn the user can enter the password
                (or if open, the connection will be establish by simply clicking on it.)
            - special case for hidden ssid:  hidden ssid once connected to are part of the known networks and can be scanned.
                If found to be in conflict - the known network is deleted from the RPi, 
                but it will continue to appear in thge unknown network list - since it was scanned,
                for as long as the app is connected by bluetooth to the RPi.
                If user exists app and restart - it will no longer be found and will have to be re-connected to by entering both ssid and password
                like any hidden ssid.

    '''
    def __init__(self,ssid,locked=True,disabled=False,number=-1,network_name = ""):
        self.ssid = ssid
        self.locked = locked
        self.disabled = disabled
        self.number=number  #not use in network manager version
        self.network_name = network_name if (network_name != "") else ssid
        #print(self.network_name, ssid)
        '''
        for Network Manager implementations, the name given to the network may not be exactly the same as the ssid exposed by the router.
        In some cases,  Network manager may add a number for example.
        The class WPAConf maintains a directory wpa_supplicants_ssid where:
            - for wpa_supplicant implementations:
                - the key is the ssid name (from the wpa_supplicant.conf file)
                - the value is this Wpa_Network object
            - for Network manager implementations:
                - the key is the network NAME given by Network Manager (which may be different from the ssid)
                - the value is this Wpa_Network object
        by storing the network name in the object, the object can be passed around and operations 
            that need the network name for network manager can be performed without having to seach for the ssid 
            in all the values of the directory to find the key (network name)
        Note: for wpa_supplicant implementations - store the ssid in the network name.
        '''

    def info(self):
        return f'ssid:{self.ssid} locked:{self.locked} disabled:{self.disabled} num:{self.number}'

class AP:
    ''' 
    object describing a single AP various attributes as discovered via scanning. may or may not be in list of known networks to RPi.
    and one method to print the object for transmission via bluetooth to iphone app
    '''
    def __init__(self,ssid='',signal=0,locked=False,in_supplicant=False,connected=False):
        self.ssid = ssid  # name of ssid (if advertized)
        self.signal = signal  # signal strength converted to scalle 0 to 5
        self.locked = locked    # True indicates SSID uses psk encoding - need password / False means open network
        self.in_supplicant = in_supplicant # True indicates this AP SSID is already in the wpa_supplicant list / known network
        self.connected = connected # True means this is the SSID to which the RPi is currently connected.

    def msg(self):
        #note: empty AP will return 0000
        return f'{self.signal}{int(self.locked)}{int(self.in_supplicant)}{int(self.connected)}{self.ssid}'

class WPAConf:
    '''
    Originally created for wpa_supplicant (RPI) - some parts are re-used for Network Manager implementation
    It is meant to hold information about Known Networks (typically in wpa_supplicant.conf file) and which is connected/disabled.

    This class reflects the wpa_supplicant.conf file on disk.
    It holds a list of "networks" listed in the file.
    It should be maintained to match what is on this - so if changes are made with wpa_cli:
        - either reload from this (use get_wpa_supplicant_ssids)
        - or modify/add the wpa_supplicant_network objects held in the wpa__supplicant_ssids dictionary
    '''
    def __init__(self, mgr):
        self.mgr = mgr
        self._connected_network = Wpa_Network('')  #blank ssid means AP is not connected
        self._connected_AP = AP() # holds AP/signal info on currently connected network
        self.wpa_supplicant_ssids = {}  #key: ssid  value: Wpa_Network
    

    @property
    def connected_AP(self):
        return self._connected_AP.msg()

    @property
    def connected_network(self):
        """Wpa_Network to which RPi is wifi connected"""
        return self._connected_network
    
    @connected_network.setter
    def connected_network(self,new_connected_network):
        '''
        new_connected_network must be a Wpa_Network object - it can be an empty Wpa_Network('')
        '''
        if not isinstance(new_connected_network,Wpa_Network):
            mLOG.log('invalid passed parameter - connected_network unchanged')
            return
        new_connected_network.disabled = False #a network previously disabled in wpa_supplicant.conf will no longer be if connected to.

        self._connected_network = new_connected_network #if blank ssid - means RPi not connected to any network
        #get AP/signal_info on connected network AP(self,ssid='',signal=0,locked=False,in_supplicant=False,connected=False)
        if len(self._connected_network.ssid)>0:
            signal_strength = 3  # Default value
            try:
                if hasattr(self, 'mgr') and self.mgr.useNetworkManager:
                    # Use Supervisor API
                    interface_info = self.mgr.supervisor_api.get_interface_info()
                    if interface_info and 'wifi' in interface_info and 'signal' in interface_info['wifi']:
                        signal_quality = interface_info['wifi']['signal']  # This is 0-100
                        signal_strength = max(0, min(5, int(signal_quality / 20)))
                    else:
                        mLOG.log("Could not get signal strength from Supervisor", level=mLOG.INFO)
                else:
                    # Use wpa_cli for non-supervisor setups
                    data = subprocess.run("wpa_cli -i wlan0 signal_poll", shell=True, capture_output=True, encoding='utf-8', text=True).stdout
                    signal = re.findall(r'RSSI=(.*?)\s', data, re.DOTALL)
                    if signal:
                        mLOG.log(f'connected network signal strength: {int(signal[0])}')
                        signal_strength = WifiUtil.signal(int(signal[0]))
            except Exception as e:
                mLOG.log(f'ERROR getting signal strength: {e}')

            self._connected_AP = AP(self._connected_network.ssid,signal_strength,self._connected_network.locked,True,True)
        else:
            self._connected_AP = AP()  # empty/blank AP
        
    def getNetwork(self,ssid):
        #get the Wpa_Network object in wpa_supplicant_ssids based on ssid
        found = [network for network in self.wpa_supplicant_ssids.values() if network.ssid == ssid]
        return found[0] if len(found) > 0 else None
    
    def isKnownNetwork(self,ssid):
        return not (self.getNetwork(ssid) is None)
    
    def get_wpa_supplicant_ssids(self):
        #use for wpa_supplicant implementation only
        #(Network Manager uses: get_NM_Known_networks/  mcli_known_networks)
        """
        This gets the list of SSID already in the wpa_supplicant.conf.
        ssids - returns list of tupples ( SSID name , psk= or key_mgmt=NONE)
        this is coverted to a list of tupples (SSID name, Locked: Bool)  
            Locked = True if "psk", false - means open network because it had key_mgmt=NONE
        (returns tupple ( SSID name , psk= or key_mgmt=NONE)  ) psk means using wpa, key_mgmt=NONE means open)
        We do not handle WEP / untested. -> consider open - will never connect
        TODO: consider adding a warning back to ios regarding non-handling of WEP etc.
        """
        # first retrieve the networks listed in the wpa_conf file and their attributed numbers (network numbers)
        #at this point - all network re listed as open because we do not know their key_management
        self.wpa_supplicant_ssids = {}
        self.retrieve_network_numbers()  # this sets self.wpa_supplicant_ssids dict
        # now for each network - get the key management information
        for ssid in self.wpa_supplicant_ssids:
            num = self.wpa_supplicant_ssids[ssid].number
            out = subprocess.run(f"wpa_cli -i wlan0 get_network {num} key_mgmt", shell=True,capture_output=True,encoding='utf-8',text=True).stdout
            self.wpa_supplicant_ssids[ssid].locked = "WPA-PSK" in out
        #get the ssid to which pi is currently connected
        current_ssid = subprocess.run("/sbin/iwgetid --raw", 
                        shell=True,capture_output=True,encoding='utf-8',text=True).stdout.strip()
        if current_ssid != "": mLOG.log(f'iwgetid says: WiFi Network {current_ssid} is connected')
        self._connected_network = Wpa_Network('')  #blank ssid means AP is not connected
        self._connected_AP = AP() # holds AP/signal info on currently connected network
        if len(current_ssid)>0:
            try:
                self.connected_network = self.wpa_supplicant_ssids[current_ssid] # this sets the connected network
            except:
                pass #connected network is not in wpa_supplicant.  no point showing to user as we don't know password etc.
       

    def retrieve_network_numbers(self,ssid=''):
        #only use by wpa_supplicant application
        '''
        retrieves the current network numbers seen by wpa_cli on RPI
        if ssid is passed, returns its number
        '''
        network_number = -1
        out = subprocess.run("wpa_cli -i wlan0 list_networks", shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        mLOG.log(out)
        ssids = re.findall(r'(\d+)\s+([^\s]+)', out, re.DOTALL)  #\s+([^\s]+)
        #ssids is returned as: [('0', 'BELL671'), ('1', 'nksan')] - network number, ssid
        #no need to read network numbers as they are incremented started at 0
        #IMPORTANT:
        #   there could be more than one SSID of the same name in the conf file.
        #   this implementation keeps the last entry and its network number
        #   users of Mesh networks were complaining that two many entries were displayed with the  same name
        #TODO: further testing with mesh network to ensure that keeping only the last entry works OK.
        mLOG.log(f'Networks configured in wpa_supplicant.conf: {ssids}')
        try: 
            for num, listed_ssid in ssids:
                if listed_ssid == ssid:  # this is only when looking for the network number of a specific ssid
                    network_number = int(num)
                #if ssid does not exists - create a network with open (no password) status
                if listed_ssid not in self.wpa_supplicant_ssids.keys():
                    self.wpa_supplicant_ssids[listed_ssid] = Wpa_Network(ssid=listed_ssid, locked=False, disabled=False, number=int(num))
                else :
                    #if ssid already exists - just update the network number
                    self.wpa_supplicant_ssids[listed_ssid].number= int(num) #fails if listed_ssid not in WPA list
        except:
            pass

        return network_number


    def save_config(self):
        #use only by wpa_supplicant application
        '''
        this method saves the current status of the wpa_cli network configuration 
        - as modified by various wpa_cli commands used to add and connect to networks - 
        into the wpa_sipplucant.conf file.
        Since connecting to a network disables all others, this method re-enable all networks
        before saving, unless a network was listed as disabled in the wpa_supplicant.conf file initially,
            and was not connected to in this session (otherwise disabled falg was set to flase via connected_network property.)
        '''
        # enable all networks except those that were previously disabled in the wpa_supplicant.conf file
        for network in self.wpa_supplicant_ssids.values():
            if (network.number >=0) and ( not network.disabled):
                out = subprocess.run(f'wpa_cli -i wlan0 enable_network {network.number}', 
                                shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        # now save config to wpa_supplicant.conf file
        out = subprocess.run("wpa_cli -i wlan0 save_config", 
                        shell=True,capture_output=True,encoding='utf-8',text=True).stdout
        mLOG.log(f'Saved wpa config to file: {out}')

    @staticmethod
    def supervisor_known_networks(supervisor_api):
        """
        Query Supervisor API for current WiFi configuration.
        With Supervisor API, we track known networks internally since
        Supervisor manages the entire interface config (not individual profiles).
        This method primarily determines if we're currently connected.
        Returns: dict of known networks (may be empty if no connection history)
        """
        known_networks = {}

        # Get interface info from Supervisor
        interface_info = supervisor_api.get_interface_info()
        if interface_info:
            # Check if WiFi is configured
            wifi_config = interface_info.get('wifi', {})
            current_ssid = wifi_config.get('ssid', '')

            if current_ssid:
                # We have a configured network - add it to known networks
                # Determine if it's encrypted based on auth mode
                auth_mode = wifi_config.get('auth', 'open')
                is_encrypted = (auth_mode != 'open')

                # Use SSID as both key and network_name (Supervisor doesn't use separate connection names)
                known_networks[current_ssid] = Wpa_Network(current_ssid, is_encrypted, False, -1, current_ssid)
                mLOG.log(f'Found configured network: {current_ssid} (encrypted: {is_encrypted})')

        return known_networks


    def get_network_name(self,ssid):
        '''
        ssid published by router
        return array of network names (used by Network Manager) for that ssid if it exists in the list networks
        return None if it does not
        normally there should only be one...
        '''
        found = [network.network_name for network in self.wpa_supplicant_ssids.values() if network.ssid == ssid]
        return found if len(found) > 0 else None
    
    #def network_name_from_Network_Manager(ssid)
        

    def get_NM_Known_networks(self, supervisor_api=None):
        """
        Get known networks via Supervisor API.
        Equivalent to get_wpa_supplicant_ssids for wpa_supplicant implementation.
        """
        # If no supervisor_api provided, create one (for compatibility)
        if supervisor_api is None:
            supervisor_api = SupervisorAPI()

        # Query Supervisor for current configuration
        self.wpa_supplicant_ssids = WPAConf.supervisor_known_networks(supervisor_api)

        self._connected_network = Wpa_Network('')  # set blank ssid as default
        self._connected_AP = AP()  # empty default

        # Check if we're connected via Supervisor API
        interface_info = supervisor_api.get_interface_info()
        if interface_info:
            # Check connection state
            if interface_info.get('connected', False):
                wifi_config = interface_info.get('wifi', {})
                current_ssid = wifi_config.get('ssid', '')

                if current_ssid and current_ssid in self.wpa_supplicant_ssids:
                    self.connected_network = self.wpa_supplicant_ssids[current_ssid]
                    mLOG.log(f'WiFi Network {current_ssid} is connected')
                elif current_ssid:
                    mLOG.log(f'Connected to {current_ssid} but not in known networks list')
            else:
                mLOG.log('WiFi interface not connected')
