#!/usr/bin/with-contenv bashio

run_orchestrator() {
set -e

bashio::log.info "================================================"
bashio::log.info "🚐 LibreCoach - System Starting"
bashio::log.info "================================================"

# ========================
# Configuration
# ========================
SUPERVISOR="http://supervisor"
AUTH_HEADER="Authorization: Bearer $SUPERVISOR_TOKEN"
PROJECT_PATH="/share/.librecoach"
BUNDLED_PROJECT="/opt/librecoach-project"

# Add-on Slugs
SLUG_MOSQUITTO="core_mosquitto"
SLUG_NODERED="a0d7b954_nodered"

# State file to track LibreCoach management
STATE_FILE="/data/.librecoach-state.json"
ADDON_VERSION=$(bashio::addon.version)

# Config values used by orchestrator (from config.yaml)
MQTT_USER=$(bashio::config 'mqtt_user')
MQTT_PASS=$(bashio::config 'mqtt_pass')
DEBUG_LOGGING=$(bashio::config 'debug_logging')
VICTRON_ENABLED=$(bashio::config 'victron_enabled')
BETA_ENABLED=$(bashio::config 'beta_enabled')
MICROAIR_ENABLED=$(bashio::config 'microair_enabled')

# ======================== 
# Orchestrator Helpers
# ======================== 
log_debug() {
  if [ "$DEBUG_LOGGING" = "true" ]; then
    # Log to stderr to avoid polluting stdout (which is captured by $())
    echo "[DEBUG] $1" >&2
  fi
}

api_call() {
  local method=$1
  local endpoint=$2
  local data=${3:-}

  log_debug "API Call: $method $endpoint"
  if [ -n "$data" ]; then
    log_debug "API Data: $data"
    local response=$(curl -s --connect-timeout 5 -m 30 -X "$method" -H "$AUTH_HEADER" -H "Content-Type: application/json" -d "$data" "$SUPERVISOR$endpoint")
  else
    local response=$(curl -s --connect-timeout 5 -m 30 -X "$method" -H "$AUTH_HEADER" "$SUPERVISOR$endpoint")
  fi

  echo "$response"
}

check_mqtt_integration() {
  bashio::log.info "   Checking for MQTT integration..."

  # Wait up to 10 minutes for HA Core to fully boot (120 retries * 5s)
  # HA Core can take several minutes to start on standard hardware after a host reboot.
  local retries=120
  local logged_wait=false

  while [ $retries -gt 0 ]; do
    local response
    response=$(api_call GET "/core/api/components")

    if [ -n "$response" ] && ! echo "$response" | grep -q -E "502|Bad Gateway|Gateway|Error" >/dev/null 2>&1; then
      # Only valid JSON array expected here. If it's valid JSON and contains "mqtt", we're good.
      if echo "$response" | jq -e 'if type == "array" then index("mqtt") else false end' >/dev/null 2>&1; then
        if [ "$logged_wait" = "true" ]; then
          bashio::log.info "   MQTT integration found"
        fi
        return 0
      fi
    fi

    if [ "$logged_wait" = "false" ]; then
      bashio::log.info "   Home Assistant is still starting. Waiting for MQTT component..."
      logged_wait=true
    fi

    sleep 5
    ((retries--))
  done

  bashio::log.warning "   ⚠️  Timed out waiting for Home Assistant to start"
  return 1
}

send_notification() {
  local title=$1
  local message=$2
  local notification_id=${3:-"librecoach_notification"}

  local payload
  payload=$(jq -n \
    --arg title "$title" \
    --arg message "$message" \
    --arg id "$notification_id" \
    '{"title": $title, "message": $message, "notification_id": $id}')

  api_call POST "/core/api/services/persistent_notification/create" "$payload" >/dev/null 2>&1
}

dismiss_notification() {
  local notification_id=$1
  api_call POST "/core/api/services/persistent_notification/dismiss" \
    "{\"notification_id\": \"$notification_id\"}" >/dev/null 2>&1
}

is_installed() {
  local slug=$1
  local response
  response=$(api_call GET "/addons/$slug/info")

  if [ -z "$response" ]; then
    log_debug "Empty response for $slug"
    return 1
  fi

  if ! echo "$response" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    log_debug "API call failed for $slug"
    return 1
  fi

  # Check version field — present means installed
  local version
  version=$(echo "$response" | jq -r '.data.version // empty')
  if [ -n "$version" ]; then
    log_debug "$slug is installed (version $version)"
    return 0
  fi

  log_debug "$slug is not installed"
  return 1
}

is_running() {
  local slug=$1
  local state
  state=$(api_call GET "/addons/$slug/info" | jq -r '.data.state // "unknown"')
  [ "$state" == "started" ]
}

install_addon() {
  local slug=$1
  bashio::log.info "   Installing $slug"
  local result
  result=$(api_call POST "/store/addons/$slug/install")
  if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    bashio::log.info "   Installed $slug"
  else
    local error_msg=$(echo "$result" | jq -r '.message')
    bashio::log.error "   ❌ Failed to install $slug: $error_msg"

    # Special handling for Node-RED already installed
    if [[ "$slug" == "$SLUG_NODERED" ]] && [[ "$error_msg" == *"already installed"* ]]; then
      bashio::log.error ""
      bashio::log.error "   Node-RED is already installed on your system."
      bashio::log.error "   To use it with LibreCoach, you must grant permission:"
      bashio::log.error ""
      bashio::log.error "   1. Go to the LibreCoach add-on Configuration tab"
      bashio::log.error "   2. Enable the 'Allow Node-RED Overwrite' option"
      bashio::log.error "   3. Scroll down and click 'Save'"
      bashio::log.error ""
      bashio::log.error "   ⚠️  WARNING: This will replace your existing Node-RED flows with LibreCoach flows."
    fi

    return 1
  fi
}

start_addon() {
  local slug=$1
  bashio::log.info "   Starting $slug"
  local result
  result=$(api_call POST "/addons/$slug/start")

  if ! echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
      bashio::log.error "   ❌ Failed to start $slug. API Response: $(echo "$result" | jq -r '.message // "Unknown error"')"
      return 1
  fi

  local retries=30
  while [ $retries -gt 0 ]; do
    if is_running "$slug"; then
      bashio::log.info "   $slug is running"
      return 0
    fi
    sleep 2
    ((retries--))
  done
  bashio::log.warning "   ⚠️  $slug started but state is not 'started' yet"
}

set_options() {
  local slug=$1
  local json=$2
  bashio::log.info "   Configuring $slug"
  log_debug "Configuration JSON: $json"
  local result
  result=$(api_call POST "/addons/$slug/options" "{\"options\": $json}")
  if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    bashio::log.info "   Configured $slug"
  else
    bashio::log.error "   ❌ Failed to configure $slug: $(echo "$result" | jq -r '.message')"
    return 1
  fi
}

restart_addon() {
  local slug=$1
  #bashio::log.info "   Restarting $slug"
  local result
  result=$(api_call POST "/addons/$slug/restart")

  if ! echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
      bashio::log.error "   ❌ Failed to restart $slug. API Response: $(echo "$result" | jq -r '.message // "Unknown error"')"
      return 1
  fi

  local retries=30
  while [ $retries -gt 0 ]; do
    if is_running "$slug"; then
      bashio::log.info "   $slug is running"
      return 0
    fi
    sleep 2
    ((retries--))
  done
  bashio::log.error "   ❌ $slug failed to restart in time"
  return 1
}

set_boot_auto() {
  local slug=$1
  local result
  result=$(api_call POST "/addons/$slug/options" '{"boot":"auto","watchdog":true}')
  if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    bashio::log.info "   $slug will start on boot with watchdog enabled"
  else
    bashio::log.warning "   ⚠️  Failed to set boot option for $slug: $(echo "$result" | jq -r '.message')"
    return 1
  fi
}

wait_for_mqtt() {
  local host=$1
  local port=$2
  local user=$3
  local pass=$4

  bashio::log.info "   Waiting for MQTT broker at $host:$port"

  local auth_args=""
  [ -n "$user" ] && auth_args="$auth_args -u $user"
  [ -n "$pass" ] && auth_args="$auth_args -P $pass"

  local retries=30
  while [ $retries -gt 0 ]; do
    if timeout 2 mosquitto_pub -h "$host" -p "$port" $auth_args -t "librecoach/test" -m "test" -q 0 2>/dev/null; then
      bashio::log.info "   MQTT broker is ready"
      return 0
    fi
    sleep 2
    ((retries--))
  done

  bashio::log.error "   ❌ MQTT broker not responding"
  return 1
}

wait_for_nodered_api() {
  bashio::log.info "   Waiting for Node-RED API to be ready"
  
  local host="a0d7b954-nodered"
  local port=1880
  local retries=60
  
  while [ $retries -gt 0 ]; do
    local url="http://${host}:${port}/"
    log_debug "Checking for Node-RED API at $url"
    
    # Check if the port is open, without requiring auth yet.
    # A 401 error will still return 0 here, which is what we want.
    if curl -sS -m 3 "$url" >/dev/null 2>&1; then
      bashio::log.info "   Node-RED API port is open. Waiting for auth to initialize"
      # Give Node-RED a moment to initialize the user auth system
      sleep 5
      return 0
    fi

    sleep 3
    ((retries--))
  done

  bashio::log.error "   ❌ Node-RED API did not become available at $url"
  return 1
}


# ======================== 
# State Management
# ======================== 
is_nodered_managed() {
  if [ ! -f "$STATE_FILE" ]; then
    return 1
  fi
  
  local managed=$(jq -r '.nodered_managed // false' "$STATE_FILE")
  [ "$managed" = "true" ]
}

mark_nodered_managed() {
  local current_hash=$1
  [ -z "$current_hash" ] && current_hash=$(get_flows_hash)

  mkdir -p /data
  cat > "$STATE_FILE" <<EOF
{
  "nodered_managed": true,
  "version": "$ADDON_VERSION",
  "flows_hash": "$current_hash",
  "prevent_flow_updates": $PREVENT_FLOW_UPDATES,
  "last_update": "$(date -Iseconds)"
}
EOF
  bashio::log.info "   Marked Node-RED as managed by LibreCoach"
}

get_managed_version() {
  if [ ! -f "$STATE_FILE" ]; then
    echo ""
    return
  fi
  jq -r '.version // ""' "$STATE_FILE"
}

get_flows_hash() {
  if [ -f "/opt/librecoach-project/flows.json" ]; then
    md5sum "/opt/librecoach-project/flows.json" | cut -d' ' -f1
  else
    echo "unknown"
  fi
}

get_managed_hash() {
  if [ ! -f "$STATE_FILE" ]; then
    echo ""
    return
  fi
  jq -r '.flows_hash // ""' "$STATE_FILE"
}

get_managed_preserve_mode() {
  if [ ! -f "$STATE_FILE" ]; then
    echo ""
    return
  fi
  jq -r '.prevent_flow_updates // ""' "$STATE_FILE"
}

# Ensure this addon starts on boot
api_call POST "/addons/self/options" '{"boot":"auto","watchdog":true}' > /dev/null

# ========================
# Deployment
# ========================
bashio::log.info "Deploying Files"

# Ensure directory exists
mkdir -p "$PROJECT_PATH"

# Always deploy/update project files from bundled version
if [ "$(ls -A $PROJECT_PATH)" ]; then
    bashio::log.info "   Updating project files from bundled version"
else
    bashio::log.info "   Deploying bundled project to $PROJECT_PATH"
fi

# Deploy project files
rsync -a --delete "$BUNDLED_PROJECT/" "$PROJECT_PATH/"

# Select the appropriate init script based on configuration
PREVENT_FLOW_UPDATES=$(bashio::config 'prevent_flow_updates')

if [ "$PREVENT_FLOW_UPDATES" = "true" ]; then
    bashio::log.info "   ✅ Flow updates PREVENTED. Using preserve-mode init script."
    cp "$PROJECT_PATH/init-nodered-preserve.sh" "$PROJECT_PATH/init-nodered.sh"
else
    bashio::log.info "   Flow updates allowed. Using standard init script."
    cp "$PROJECT_PATH/init-nodered-overwrite.sh" "$PROJECT_PATH/init-nodered.sh"
fi

# Inject the addon slug for the suicide check
OWNER_SLUG=$(api_call GET "/addons/self/info" | jq -r '.data.slug // empty')
sed -i "s/REPLACE_ME/$OWNER_SLUG/g" "$PROJECT_PATH/init-nodered.sh"

# Ensure permissions are open (Node-RED runs as non-root)
chmod -R 755 "$PROJECT_PATH"
bashio::log.info "   Project files deployed"


# ========================
# Mosquitto MQTT Broker
# ========================
bashio::log.info "Mosquitto MQTT Broker"

if is_installed "$SLUG_MOSQUITTO"; then
  # Mosquitto is installed, ensure it's running
  bashio::log.info "   Mosquitto is already installed"
  if ! is_running "$SLUG_MOSQUITTO"; then
    start_addon "$SLUG_MOSQUITTO" || exit 1
  fi
else
  # Mosquitto is NOT installed. Install it.
  bashio::log.info "   Mosquitto not found. Installing"
  install_addon "$SLUG_MOSQUITTO" || exit 1
  start_addon "$SLUG_MOSQUITTO" || exit 1
fi

# Ensure Mosquitto starts on boot
  bashio::log.info "   Setting Mosquitto to start on boot with watchdog"
set_boot_auto "$SLUG_MOSQUITTO" || bashio::log.warning "   ⚠️  Could not set Mosquitto to auto-start"

# Ensure librecoach MQTT user exists in Mosquitto
bashio::log.info "   Ensuring '$MQTT_USER' user exists in Mosquitto"
MQTT_HOST="core-mosquitto"
MQTT_PORT=1883

MOSQUITTO_OPTIONS=$(api_call GET "/addons/$SLUG_MOSQUITTO/info" | jq '.data.options')
NEW_MOSQUITTO_OPTIONS=$(echo "$MOSQUITTO_OPTIONS" | jq --arg user "$MQTT_USER" --arg pass "$MQTT_PASS" '
    .logins = (.logins // []) |
    .logins |= (map(select(.username != $user)) + [{"username": $user, "password": $pass}])
')

if [ -z "$NEW_MOSQUITTO_OPTIONS" ] || [ "$NEW_MOSQUITTO_OPTIONS" == "null" ]; then
    bashio::log.error "   ❌ Failed to generate Mosquitto configuration"
    exit 1
fi

# Only update config and restart if the librecoach user/password changed
if [ "$NEW_MOSQUITTO_OPTIONS" != "$MOSQUITTO_OPTIONS" ]; then
  api_call POST "/addons/$SLUG_MOSQUITTO/options" "{\"options\": $NEW_MOSQUITTO_OPTIONS}" > /dev/null
  bashio::log.info "   Configured Mosquitto user: $MQTT_USER"
  if is_running "$SLUG_MOSQUITTO"; then
    bashio::log.info "   Restarting Mosquitto to apply new configuration"
    restart_addon "$SLUG_MOSQUITTO" || exit 1
  fi
else
  bashio::log.info "   Mosquitto user already configured"
  # Ensure Mosquitto is running (may not be after a reboot)
  if ! is_running "$SLUG_MOSQUITTO"; then
    start_addon "$SLUG_MOSQUITTO" || exit 1
  else
    bashio::log.info "   $SLUG_MOSQUITTO is running"
  fi
fi

# Verify MQTT is responding with configured credentials
wait_for_mqtt "$MQTT_HOST" "$MQTT_PORT" "$MQTT_USER" "$MQTT_PASS" || {
    bashio::log.fatal "❌ MQTT broker is not responding. Cannot continue."
    exit 1
}
bashio::log.info "   MQTT credentials verified"

# Validate MQTT Integration
bashio::log.info "   Validating MQTT integration..."

if ! check_mqtt_integration; then
  # Send persistent notification to Home Assistant UI
  send_notification \
    "⚠️ LibreCoach: MQTT Integration Required" \
    "**LibreCoach installation is paused!**

✅ Mosquitto broker is installed and running
⚠️ But MQTT integration needs to be configured

**Quick Setup (30 seconds):**

1. Go to **Settings → Devices & Services**
2. Look for **MQTT** in the 'Discovered' section
3. Click **ADD** on the MQTT card
4. Click **SUBMIT** to use Mosquitto broker
5. Return to **Settings → Add-ons → LibreCoach** and click **RESTART**

**Why?** The MQTT integration listens for device discovery messages and creates entities automatically.

_See LibreCoach addon logs for more details_" \
    "librecoach_mqtt_setup"

  # Also log to addon logs
  bashio::log.error ""
  bashio::log.error "╔════════════════════════════════════════════════════════════╗"
  bashio::log.error "║   ⚠️  MQTT INTEGRATION REQUIRED  ⚠️                        ║"
  bashio::log.error "╚════════════════════════════════════════════════════════════╝"
  bashio::log.error ""
  bashio::log.error "   ✅ Mosquitto broker is installed and running"
  bashio::log.error "   ⚠️  But MQTT integration needs to be configured"
  bashio::log.error ""
  bashio::log.error "   Quick Setup (takes 30 seconds):"
  bashio::log.error ""
  bashio::log.error "   1. Go to Settings → Devices & Services"
  bashio::log.error "   2. Look for MQTT in the 'Discovered' section"
  bashio::log.error "   3. Click ADD on the MQTT card"
  bashio::log.error "   4. Click SUBMIT to use Mosquitto broker"
  bashio::log.error "   5. Return to Settings → Add-ons → LibreCoach and click RESTART"
  bashio::log.error ""
  bashio::log.error "   Check the notification in Home Assistant UI (🔔 bell icon)"
  bashio::log.error ""
  bashio::log.fatal "   ⏸️  Installation paused. Complete MQTT setup and start LibreCoach."
  bashio::log.fatal ""
  exit 1
fi

# MQTT is configured - dismiss any previous setup notifications
dismiss_notification "librecoach_mqtt_setup"
bashio::log.info "   MQTT integration is configured"

# Legacy cleanup: disable old CAN-MQTT Bridge add-on if present
SLUG_CAN_BRIDGE="3b081c96_can-mqtt-bridge"
if is_installed "$SLUG_CAN_BRIDGE"; then
    bashio::log.info "Migrating from standalone CAN-MQTT Bridge"
    is_running "$SLUG_CAN_BRIDGE" && api_call POST "/addons/$SLUG_CAN_BRIDGE/stop" "" >/dev/null 2>&1
    api_call POST "/addons/$SLUG_CAN_BRIDGE/options" '{"boot":"manual","watchdog":false}' >/dev/null 2>&1
    bashio::log.info "CAN-MQTT Bridge disabled. The vehicle_bridge now handles CAN."
    bashio::log.info "You may uninstall can-mqtt-bridge from Settings → Add-ons."
fi

# Publish config toggles as retained MQTT messages for Node-RED
mqtt_pub() { mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASS" -r -q 1 "$@"; }
mqtt_pub -t "librecoach/config/victron_enabled" -m "$VICTRON_ENABLED"
mqtt_pub -t "librecoach/config/beta_enabled" -m "$BETA_ENABLED"
mqtt_pub -t "librecoach/config/microair_enabled" -m "$MICROAIR_ENABLED"
bashio::log.info "   Published config toggles to MQTT"

# ========================
# LibreCoach BLE Integration
# ========================

bashio::log.info "Bluetooth Integration"

INTEGRATION_SRC="/opt/librecoach_ble"
INTEGRATION_DST="/config/custom_components/librecoach_ble"

# Write config file for the integration to read at runtime.
# Always written regardless of toggle — the integration handles enable/disable dynamically via MQTT.
MICROAIR_PASSWORD=$(bashio::config 'microair_password')
MICROAIR_EMAIL=$(bashio::config 'microair_email')

jq -n \
    --argjson enabled "$MICROAIR_ENABLED" \
    --arg password "$MICROAIR_PASSWORD" \
    --arg email "$MICROAIR_EMAIL" \
    --arg slug "$OWNER_SLUG" \
    '{
        microair_enabled: $enabled,
        microair_password: $password,
        microair_email: $email,
        addon_slug: $slug
    }' > /config/.librecoach-ble-config.json

# Install/update integration files (only restart if code actually changed)
NEEDS_HA_RESTART=false

# Define a hash function that ignores HA runtime files (.translations) and OS hidden files
get_integration_hash() {
    local dir=$1
    # Only hash explicit extension types and ignore all hidden paths or pycache
    (cd "$dir" && find . -type f \( -name "*.py" -o -name "*.json" -o -name "*.png" \) \
        -not -path "*/__pycache__/*" -not -path "*/.*" -exec md5sum {} + | sort -k 2 | md5sum | cut -d' ' -f1)
}

BUNDLED_HASH=$(get_integration_hash "$INTEGRATION_SRC")

if [ -d "$INTEGRATION_DST" ]; then
    INSTALLED_HASH=$(get_integration_hash "$INTEGRATION_DST")

    if [ "$BUNDLED_HASH" != "$INSTALLED_HASH" ]; then
        bashio::log.info "   Updating librecoach_ble integration"
        log_debug "BLE hash mismatch (Bundled: $BUNDLED_HASH, Installed: $INSTALLED_HASH)"
        rm -rf "$INTEGRATION_DST"
        cp -r "$INTEGRATION_SRC" "$INTEGRATION_DST"
        NEEDS_HA_RESTART=true
    else
        bashio::log.info "   librecoach_ble is up to date"
        log_debug "BLE hashes match: $INSTALLED_HASH"
    fi
else
    bashio::log.info "   Installing librecoach_ble integration"
    mkdir -p /config/custom_components
    cp -r "$INTEGRATION_SRC" "$INTEGRATION_DST"
    NEEDS_HA_RESTART=true
fi

# Add to configuration.yaml if not present
if ! grep -q "librecoach_ble:" /config/configuration.yaml 2>/dev/null; then
    bashio::log.info "   Adding librecoach_ble to configuration.yaml"
    echo -e "\nlibrecoach_ble:" >> /config/configuration.yaml
    NEEDS_HA_RESTART=true
fi

if [ "$NEEDS_HA_RESTART" = "true" ]; then
    bashio::log.warning "   ⚠️  LibreCoach Bluetooth Integration state changed"
    bashio::log.warning "   ⚠️  Restarting Home Assistant Core to apply changes"
    bashio::log.warning "   ⚠️  It is normal to briefly lose connection to Home Assistant."
    bashio::log.warning "   ⚠️  Please wait a few minutes and refresh your browser if necessary."

    api_call POST "/core/restart" >/dev/null 2>&1

    # Wait for HA to come back (10s initial delay + up to ~2 min polling)
    bashio::log.info "   Waiting for Home Assistant to finish restarting"
    sleep 10
    retries=30
    while [ $retries -gt 0 ]; do
        if curl -s --connect-timeout 3 -m 5 -H "$AUTH_HEADER" "$SUPERVISOR/core/api/" 2>/dev/null | grep -q "API running"; then
            bashio::log.info "   Home Assistant is back online"
            break
        fi
        sleep 3
        ((retries--))
    done

    if [ $retries -eq 0 ]; then
        bashio::log.warning "   ⚠️  HA restart taking longer than expected"
        bashio::log.warning "   BLE integration will load after HA finishes"
    fi
fi

bashio::log.info "   LibreCoach Bluetooth integration ready"

# ========================
# Node-RED
# ========================
bashio::log.info "Node-RED"

CONFIRM_TAKEOVER=$(bashio::config 'confirm_nodered_takeover')
NODERED_ALREADY_INSTALLED=false

if is_installed "$SLUG_NODERED"; then
  bashio::log.info "   Node-RED is already installed."
  NODERED_ALREADY_INSTALLED=true
else
  # Try to install Node-RED
  bashio::log.info "   Node-RED not found. Installing"
  if ! install_addon "$SLUG_NODERED"; then
    # Installation failed - check if it's because it's already installed
    nr_check=$(api_call GET "/addons/$SLUG_NODERED/info")
    # Check if addon is actually installed (by checking for version field)
    nr_version=$(echo "$nr_check" | jq -r '.data.version // empty')
    if [ -n "$nr_version" ]; then
      bashio::log.info "   Node-RED was already installed (detection issue)"
      NODERED_ALREADY_INSTALLED=true
    else
      # Different error, exit
      exit 1
    fi
  fi
fi

# If Node-RED was already installed, check if we need takeover permission
# Skip takeover check if already managed by LibreCoach
if [ "$NODERED_ALREADY_INSTALLED" = "true" ]; then
  # Migration: if state file doesn't exist but Node-RED's init_commands already
  # point to LibreCoach, a previous version was managing it. Auto-create state file
  # so upgrades don't re-prompt for takeover permission.
  if ! is_nodered_managed; then
    nr_init_check=$(api_call GET "/addons/$SLUG_NODERED/info" | jq -r '.data.options.init_commands[0] // empty')
    if [[ "$nr_init_check" == *"librecoach"* ]]; then
      bashio::log.info "   Migrating: previous LibreCoach version detected (init_commands present). Creating state file."
      mark_nodered_managed "$(get_flows_hash)"
    fi
  fi

  if is_nodered_managed; then
    MANAGED_VERSION=$(get_managed_version)
    bashio::log.info "   Node-RED already managed by LibreCoach (version $MANAGED_VERSION)"
  else
    # Node-RED exists but not managed by LibreCoach - need permission
    if [ "$PREVENT_FLOW_UPDATES" = "true" ]; then
       bashio::log.info "   ✅ Flow update prevention enabled - implicitly allowing Node-RED management."
    elif [ "$CONFIRM_TAKEOVER" != "true" ]; then
       bashio::log.warning ""
       bashio::log.warning "   ⚠️  EXISTING INSTALLATION DETECTED"
       bashio::log.warning "   LibreCoach needs to configure Node-RED to run the LibreCoach project."
       bashio::log.warning "   This will REPLACE your active Node-RED flows."
       bashio::log.warning "   "
       bashio::log.warning "   To proceed, you must explicitly grant permission:"
       bashio::log.warning "   1. Go to the LibreCoach add-on configuration tab."
       bashio::log.warning "   2. Enable 'Allow Node-RED Overwrite'."
       bashio::log.warning "   3. Scroll down and click 'Save'."
       bashio::log.warning "   4. Restart the LibreCoach add-on."
       bashio::log.warning ""
       send_notification \
         "⚠️ LibreCoach: Node-RED Setup Required" \
         "**LibreCoach setup is paused — action required!**

An existing Node-RED installation was detected. LibreCoach needs to replace your Node-RED flows with the LibreCoach project flows.

**To proceed:**
1. Go to **Settings → Add-ons → LibreCoach**
2. Open the **Configuration** tab
3. Enable **Allow Node-RED Overwrite**
4. Click **Save**
5. **Restart** the LibreCoach add-on

⚠️ This will replace your existing Node-RED flows." \
         "librecoach_nodered_takeover"
       bashio::log.warning "   ⏸️  Setup paused. LibreCoach will not restart automatically."
       bashio::log.warning "   After granting permission and saving, restart the add-on."
       return 1
    else
       bashio::log.info "   ✅ Permission granted to take over Node-RED."
    fi
  fi
fi

# Save previous state before marking managed (needed for flow update detection later)
PREVIOUS_FLOWS_HASH=$(get_managed_hash)
PREVIOUS_PRESERVE_MODE=$(get_managed_preserve_mode)
FLOWS_HASH=$(get_flows_hash)

# Mark Node-RED as managed now, before configuration steps that may fail and trigger a watchdog
# restart. Without this, a failed restart_addon call causes the next run to see Node-RED as
# installed-but-unmanaged and incorrectly prompt for takeover permission.
mark_nodered_managed "$FLOWS_HASH"

# Configure Node-RED
NR_INFO=$(api_call GET "/addons/$SLUG_NODERED/info")
log_debug "Node-RED Info API called."
NR_OPTIONS=$(echo "$NR_INFO" | jq '.data.options // {}')
EXISTING_SECRET=$(echo "$NR_OPTIONS" | jq -r '.credential_secret // empty')
log_debug "Existing credentials secret extracted."

# Because Home Assistant add-ons cannot mount volumes during installation, LibreCoach
# deploys its project files to `/share/.librecoach`. We then inject a bash script into
# Node-RED's `init_commands` array. When Node-RED boots, it runs this script to copy
# the project files from the `/share` drive into its own protected `/config` volume.
SETTINGS_INIT_CMD="bash /share/.librecoach/init-nodered.sh"

# LibreCoach requires credential_secret to be "librecoach" for flows_cred.json decryption
LIBRECOACH_SECRET="librecoach"

NEEDS_RESTART=false

# Backup existing credential_secret if it exists and differs from ours
if [ -n "$EXISTING_SECRET" ] && [ "$EXISTING_SECRET" != "$LIBRECOACH_SECRET" ]; then
  BACKUP_FILE="$PROJECT_PATH/.backup_credential_secret"
  bashio::log.info "   Backing up existing Node-RED credential_secret to $BACKUP_FILE"
  echo "$EXISTING_SECRET" > "$BACKUP_FILE"
  chmod 600 "$BACKUP_FILE"
fi

if [ -z "$EXISTING_SECRET" ] || [ "$EXISTING_SECRET" != "$LIBRECOACH_SECRET" ]; then
  bashio::log.info "   Setting credential_secret to 'librecoach' for flows_cred.json compatibility"
  NEW_OPTIONS=$(echo "$NR_OPTIONS" | jq \
    --arg secret "$LIBRECOACH_SECRET" \
    --arg initcmd "$SETTINGS_INIT_CMD" \
    '. + {"credential_secret": $secret, "ssl": false, "init_commands": [$initcmd]} | del(.users)')
  set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
  NEEDS_RESTART=true
else
  CURRENT_INIT_CMD=$(echo "$NR_OPTIONS" | jq -r '.init_commands[0] // empty')
  HAS_USERS=$(echo "$NR_OPTIONS" | jq -r 'if .users then "true" else "false" end')

  # Check if config needs updating (init command changed or users auth still present)
  if [ "$CURRENT_INIT_CMD" != "$SETTINGS_INIT_CMD" ] || [ "$HAS_USERS" = "true" ]; then
    if [ -z "$CURRENT_INIT_CMD" ]; then
      bashio::log.warning "   ⚠️  Node-RED init command is missing. Restoring."
    else
      bashio::log.info "   Updating Node-RED configuration (init commands)"
    fi
    NEW_OPTIONS=$(echo "$NR_OPTIONS" | jq \
      --arg initcmd "$SETTINGS_INIT_CMD" \
      '. + {"init_commands": [$initcmd]} | del(.users)')
    set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
    NEEDS_RESTART=true
  else
    bashio::log.info "   Node-RED configuration is up to date"
  fi
fi

# Check if flows file has changed (requiring a restart to pick up)
if [ "$PREVENT_FLOW_UPDATES" != "true" ] && [ "$NEEDS_RESTART" = "false" ]; then
  if [ -n "$PREVIOUS_FLOWS_HASH" ] && [ "$PREVIOUS_FLOWS_HASH" != "$FLOWS_HASH" ]; then
    log_debug "Flow hash changed from $PREVIOUS_FLOWS_HASH to $FLOWS_HASH"
    NEEDS_RESTART=true
  fi
fi

# Detect preserve-mode transition: if preserve was previously enabled and is now disabled,
# run the full Node-RED verification — ensure the init command is present, using the correct
# (overwrite) init script, and restart Node-RED to replace preserved flows with bundled flows.
if [ "$PREVIOUS_PRESERVE_MODE" = "true" ] && [ "$PREVENT_FLOW_UPDATES" != "true" ]; then
  bashio::log.info "   Flow preservation was disabled. Verifying Node-RED configuration."

  # Re-check init command — user may have removed it while in preserve mode
  CURRENT_INIT_CMD=$(api_call GET "/addons/$SLUG_NODERED/info" | jq -r '.data.options.init_commands[0] // empty')
  if [ "$CURRENT_INIT_CMD" != "$SETTINGS_INIT_CMD" ]; then
    bashio::log.warning "   ⚠️  Node-RED init command is missing. Restoring."
    # Re-read live options to avoid stale data from earlier set_options call
    NR_OPTIONS_LIVE=$(api_call GET "/addons/$SLUG_NODERED/info" | jq '.data.options // {}')
    NEW_OPTIONS=$(echo "$NR_OPTIONS_LIVE" | jq \
      --arg initcmd "$SETTINGS_INIT_CMD" \
      '. + {"init_commands": [$initcmd]} | del(.users)')
    set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
  else
    bashio::log.info "   Node-RED init command verified"
  fi

  bashio::log.info "   Restarting Node-RED to restore standard flows."
  NEEDS_RESTART=true
fi

# Ensure Node-RED starts/restarts to apply init commands
if [ "$NEEDS_RESTART" = "true" ]; then
  if is_running "$SLUG_NODERED"; then
    bashio::log.info "   Restarting Node-RED to apply new configuration"
    restart_addon "$SLUG_NODERED" || exit 1
  else
    bashio::log.info "   Starting Node-RED with new configuration"
    start_addon "$SLUG_NODERED" || exit 1
    
    # Force a restart after fresh start to fix race condition:
    # On first boot, Node-RED's initialization may interfere with init_commands.
    # A restart ensures init_commands run cleanly on an initialized volume.
    bashio::log.info "   Performing initialization restart to ensure init_commands take effect"
    sleep 5
    restart_addon "$SLUG_NODERED" || exit 1
  fi
else
  if ! is_running "$SLUG_NODERED"; then
    start_addon "$SLUG_NODERED" || exit 1
  fi
fi

# Wait for Node-RED to be available before proceeding.
# Flows are loaded automatically by Node-RED on startup via init_commands — no API deploy needed.
if wait_for_nodered_api; then
    # Re-publish config toggles now that Node-RED is online.
    # The initial publish (retained) may be missed if the broker cycled during startup.
    mqtt_pub -t "librecoach/config/victron_enabled" -m "$VICTRON_ENABLED"
    mqtt_pub -t "librecoach/config/beta_enabled" -m "$BETA_ENABLED"
    mqtt_pub -t "librecoach/config/microair_enabled" -m "$MICROAIR_ENABLED"
    bashio::log.info "   Re-published config toggles to MQTT"
else
    bashio::log.warning "   ⚠️  Node-RED API did not respond. It may still be starting."
fi

# Ensure Node-RED starts on boot
  bashio::log.info "   Setting Node-RED to start on boot with watchdog"
set_boot_auto "$SLUG_NODERED" || bashio::log.warning "   ⚠️  Could not set Node-RED to auto-start"

# Mark/update Node-RED as managed by LibreCoach (updates version on upgrades)
mark_nodered_managed "$FLOWS_HASH"

# ========================
# Installation Summary
# ========================
# ========================
bashio::log.info "╔════════════════════════════════════════════════════════════╗"
bashio::log.info "║           LibreCoach Installation Summary                  ║"
bashio::log.info "╠════════════════════════════════════════════════════════════╣"
bashio::log.info "║  MQTT Integration ................ Configured              ║"
bashio::log.info "║  Mosquitto MQTT Broker ........... Running                 ║"
bashio::log.info "║  Node-RED ........................ Running                 ║"
bashio::log.info "║  RV-C Bridge ..................... Starting                ║"
bashio::log.info "║  Bluetooth server ................ Starting                ║"
bashio::log.info "╠════════════════════════════════════════════════════════════╣"
bashio::log.info "║  All components installed successfully!                    ║"
bashio::log.info "║  Visit https://LibreCoach.com for more information         ║"
bashio::log.info "╚════════════════════════════════════════════════════════════╝"

} # end run_orchestrator

# Run orchestrator, capture result
# As a cont-init.d script, this runs once at startup before s6 services start.
# The vehicle_bridge Python process is managed by s6 as a longrun service.
if run_orchestrator; then
    bashio::log.info "Orchestrator complete. Vehicle bridge starting via s6."
else
    bashio::log.warning "Orchestrator encountered errors. Check logs above."
    bashio::log.warning "Fix the issue, then restart the addon from Settings → Add-ons → LibreCoach."
fi
