#!/usr/bin/with-contenv bashio
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
SLUG_CAN_BRIDGE="3b081c96_can-mqtt-bridge"


# State file to track LibreCoach management
STATE_FILE="/data/.librecoach-state.json"
ADDON_VERSION=$(bashio::addon.version)

# Track component status for summary
BRIDGE_STATUS="not_started"

# Bridge Config (to pass to CAN bridge addon)
CAN_INTERFACE=$(bashio::config 'can_interface')
CAN_BITRATE=$(bashio::config 'can_bitrate')
MQTT_TOPIC_RAW=$(bashio::config 'mqtt_topic_raw')
MQTT_TOPIC_SEND=$(bashio::config 'mqtt_topic_send')
MQTT_TOPIC_STATUS=$(bashio::config 'mqtt_topic_status')
MQTT_USER=$(bashio::config 'mqtt_user')
MQTT_PASS=$(bashio::config 'mqtt_pass')
DEBUG_LOGGING=$(bashio::config 'debug_logging')

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
    local response=$(curl -s -X "$method" -H "$AUTH_HEADER" -H "Content-Type: application/json" -d "$data" "$SUPERVISOR$endpoint")
  else
    local response=$(curl -s -X "$method" -H "$AUTH_HEADER" "$SUPERVISOR$endpoint")
  fi

  echo "$response"
}

get_addon_logs() {
  local slug=$1
  local lines=${2:-50}  # Default to last 50 lines
  # Logs endpoint returns plain text, not JSON
  api_call GET "/addons/$slug/logs" | tail -n "$lines"
}

check_mqtt_integration() {
  bashio::log.info "Checking for MQTT integration..."

  # Call Home Assistant Core API to get list of loaded components
  local response
  response=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
    "http://supervisor/core/api/components" 2>/dev/null)

  if [ -z "$response" ]; then
    bashio::log.warning "   ⚠️  Unable to query Home Assistant Core API"
    return 1
  fi

  # Check if 'mqtt' is in the components array
  if echo "$response" | jq -r '.[] | select(. == "mqtt")' | grep -q "mqtt"; then
    bashio::log.info "   MQTT integration is configured"
    return 0
  else
    return 1
  fi
}

send_notification() {
  local title=$1
  local message=$2
  local notification_id=${3:-"librecoach_notification"}

  # Call Home Assistant Core API to create a persistent notification
  local payload
  payload=$(jq -n \
    --arg title "$title" \
    --arg message "$message" \
    --arg id "$notification_id" \
    '{
      "title": $title,
      "message": $message,
      "notification_id": $id
    }')

  curl -s -X POST \
    -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    "http://supervisor/core/api/services/persistent_notification/create" >/dev/null 2>&1
}

is_installed() {
  local slug=$1
  local response
  response=$(api_call GET "/addons/$slug/info")

  # Guard against empty responses (e.g. Supervisor starting up)
  if [ -z "$response" ]; then
    log_debug "API call returned empty response for $slug"
    return 1
  fi

  # Check if the API call was successful
  if ! echo "$response" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    log_debug "API call to check $slug installation failed"
    return 1
  fi

  # Check installation status
  # If "installed" field exists, use it
  local installed=$(echo "$response" | jq -r '.data.installed // empty')
  if [ -n "$installed" ]; then
    log_debug "$slug explicit installed status: $installed"
    [ "$installed" == "true" ]
    return $?
  fi

  # If no "installed" field, check if "version" field exists (indicates installed addon)
  local version=$(echo "$response" | jq -r '.data.version // empty')
  if [ -n "$version" ]; then
    log_debug "$slug has version $version, therefore is installed"
    return 0
  fi

  log_debug "$slug does not appear to be installed"
  return 1
}

is_running() {
  local slug=$1
  local state
  state=$(echo "$(api_call GET "/addons/$slug/info")" | jq -r '.data.state // "unknown"')
  [ "$state" == "started" ]
}

install_addon() {
  local slug=$1
  bashio::log.info "   > Installing $slug..."
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
      bashio::log.error "   2. Enable the 'confirm_nodered_takeover' option"
      bashio::log.error "   3. Save and restart the LibreCoach add-on"
      bashio::log.error ""
      bashio::log.error "   ⚠️  WARNING: This will replace your existing Node-RED flows with LibreCoach flows."
    fi

    return 1
  fi
}

start_addon() {
  local slug=$1
  bashio::log.info "   > Starting $slug..."
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
  bashio::log.info "   > Configuring $slug..."
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
  bashio::log.info "   > Restarting $slug..."
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
  bashio::log.info "   > Setting $slug to start on boot with watchdog..."
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

  bashio::log.info "   > Waiting for MQTT broker at $host:$port..."

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
  bashio::log.info "   > Waiting for Node-RED API to be ready..."
  
  local host="a0d7b954-nodered"
  local port=1880
  local retries=60
  
  while [ $retries -gt 0 ]; do
    local url="http://${host}:${port}/"
    log_debug "Checking for Node-RED API at $url"
    
    # Check if the port is open, without requiring auth yet.
    # A 401 error will still return 0 here, which is what we want.
    if curl -sS -m 3 "$url" >/dev/null 2>&1; then
      bashio::log.info "   Node-RED API port is open. Waiting for auth to initialize..."
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

deploy_nodered_flows() {
  bashio::log.info "   > Triggering Node-RED flow deployment..."
  
  local host="a0d7b954-nodered"
  if [ -f /tmp/nodered_host ]; then
    host=$(cat /tmp/nodered_host)
  fi
  local base_url="http://${host}:1880"
  
  # FETCH PHASE: Retry until Node-RED is fully ready
  local flows=""
  local retries=15
  local success=false
  local last_error=""

  bashio::log.info "   > Waiting for Node-RED to be ready for deployment..."
  while [ $retries -gt 0 ]; do
    # Capture both response and HTTP code
    local response
    local http_code
    response=$(curl -s -w "\n%{http_code}" --user "$MQTT_USER:$MQTT_PASS" -m 5 "${base_url}/flows" 2>&1)
    http_code=$(echo "$response" | tail -n1)
    flows=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
      if echo "$flows" | jq -e '.' >/dev/null 2>&1; then
        success=true
        break
      else
        last_error="Invalid JSON response"
      fi
    else
      last_error="HTTP $http_code"
    fi

    log_debug "Node-RED API not ready yet (${last_error}). Retrying in 3s... ($retries attempts left)"
    sleep 3
    ((retries--))
  done

  if [ "$success" = "false" ]; then
    bashio::log.error "   ❌ Failed to communicate with Node-RED API after 45 seconds."
    bashio::log.error "   Last error: ${last_error}"
    bashio::log.error "   URL: ${base_url}/flows"
    bashio::log.error "   User: ${MQTT_USER}"
    return 1
  fi

  bashio::log.info "   Node-RED API ready. Deploying flows..."

  # DEPLOY PHASE: Use "full" deployment for complete node restart
  # Use stdin to avoid "Argument list too long" error with large flows
  local deploy_response
  deploy_response=$(echo "$flows" | curl -s -w "\n%{http_code}" --user "$MQTT_USER:$MQTT_PASS" -m 10 -X POST \
    -H "Content-Type: application/json" \
    -H "Node-RED-Deployment-Type: full" \
    -d @- \
    "${base_url}/flows" 2>&1)

  local http_code=$(echo "$deploy_response" | tail -n1)
  local response_body=$(echo "$deploy_response" | sed '$d')

  if [ "$http_code" = "204" ] || [ "$http_code" = "200" ]; then
    bashio::log.info "   Node-RED flows deployed successfully"
    # Give MQTT nodes time to establish connections
    sleep 5
    return 0
  else
    bashio::log.warning "   ⚠️  Failed to deploy flows. HTTP $http_code"
    log_debug "Deploy response: $response_body"
    bashio::log.warning "   You may need to click Deploy manually."
    return 1
  fi
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
  mkdir -p /data
  cat > "$STATE_FILE" <<EOF
{
  "nodered_managed": true,
  "version": "$ADDON_VERSION",
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

# ========================
# Phase 0: Deployment
# ========================
bashio::log.info "Phase 0: Deploying Files"

# Ensure directory exists
mkdir -p "$PROJECT_PATH"

# Always deploy/update project files from bundled version
if [ "$(ls -A $PROJECT_PATH)" ]; then
    bashio::log.info "   Updating project files from bundled version..."
else
    bashio::log.info "   Deploying bundled project to $PROJECT_PATH..."
fi

# Deploy project files
rsync -a --delete "$BUNDLED_PROJECT/" "$PROJECT_PATH/"
# Ensure permissions are open (Node-RED runs as non-root)
chmod -R 755 "$PROJECT_PATH"
bashio::log.info "   Project files deployed"


# ========================
# Phase 1: Mosquitto MQTT Broker
# ========================
bashio::log.info "Phase 1: Installing Mosquitto MQTT Broker"

# 1. Mosquitto
if is_installed "$SLUG_MOSQUITTO"; then
  # Mosquitto is installed, ensure it's running
  bashio::log.info "   Mosquitto is already installed"
  if ! is_running "$SLUG_MOSQUITTO"; then
    start_addon "$SLUG_MOSQUITTO" || exit 1
  fi
else
  # Mosquitto is NOT installed. Install it.
  bashio::log.info "   Mosquitto not found. Installing..."
  install_addon "$SLUG_MOSQUITTO" || exit 1
  start_addon "$SLUG_MOSQUITTO" || exit 1
fi

# Ensure Mosquitto starts on boot
set_boot_auto "$SLUG_MOSQUITTO" || bashio::log.warning "   ⚠️  Could not set Mosquitto to auto-start"

# Always ensure librecoach user exists in Mosquitto for consistency
# Both Node-RED and CAN-MQTT Bridge will use these credentials
bashio::log.info "   Ensuring 'librecoach' user exists in Mosquitto..."
# MQTT_USER and MQTT_PASS are read from config at the top
MQTT_HOST="core-mosquitto"
MQTT_PORT=1883

# Create user in Mosquitto options
MOSQUITTO_OPTIONS=$(api_call GET "/addons/$SLUG_MOSQUITTO/info" | jq '.data.options')

# Remove existing user if present, then add it with current password
# Handle case where logins might be null
NEW_MOSQUITTO_OPTIONS=$(echo "$MOSQUITTO_OPTIONS" | jq --arg user "$MQTT_USER" --arg pass "$MQTT_PASS" '
    .logins = (.logins // []) | 
    .logins |= (map(select(.username != $user)) + [{"username": $user, "password": $pass}])
')

if [ -z "$NEW_MOSQUITTO_OPTIONS" ] || [ "$NEW_MOSQUITTO_OPTIONS" == "null" ]; then
    bashio::log.error "   ❌ Failed to generate Mosquitto configuration"
    exit 1
fi

api_call POST "/addons/$SLUG_MOSQUITTO/options" "{\"options\": $NEW_MOSQUITTO_OPTIONS}" > /dev/null
bashio::log.info "   Configured Mosquitto user: $MQTT_USER"
bashio::log.info "   Created MQTT user: $MQTT_USER (password: ${#MQTT_PASS} chars)"

# Restart Mosquitto to apply new user
if is_running "$SLUG_MOSQUITTO"; then
  restart_addon "$SLUG_MOSQUITTO" || exit 1
fi

# Verify MQTT is actually responding
wait_for_mqtt "$MQTT_HOST" "$MQTT_PORT" "$MQTT_USER" "$MQTT_PASS" || {
    bashio::log.fatal "❌ MQTT broker is not responding. Cannot continue."
    exit 1
}

# Restart Mosquitto again to trigger MQTT integration discovery in Home Assistant
bashio::log.info "   Restarting Mosquitto to trigger MQTT integration discovery..."
restart_addon "$SLUG_MOSQUITTO" || exit 1

# Give Mosquitto time to fully restart and publish updated service discovery
# This ensures the CAN bridge gets the correct credentials when it starts
sleep 10
bashio::log.info "   Mosquitto restarted"

# Re-verify MQTT credentials still work after second restart
bashio::log.info "   > Re-verifying MQTT credentials after restart..."
wait_for_mqtt "$MQTT_HOST" "$MQTT_PORT" "$MQTT_USER" "$MQTT_PASS" || {
    bashio::log.fatal "❌ MQTT credentials not working after restart. This shouldn't happen."
    exit 1
}
bashio::log.info "   MQTT credentials verified and service discovery updated"

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
5. Return to **Settings → Add-ons → LibreCoach** and click **START**

**Why?** The MQTT integration listens for device discovery messages and creates entities automatically.

_See LibreCoach addon logs for more details_" \
    "librecoach_mqtt_setup"

  # Also log to addon logs for those who check
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
  bashio::log.error "   5. Return to Settings → Add-ons → LibreCoach and click START"
  bashio::log.error ""
  bashio::log.error "   Check the notification in Home Assistant UI (🔔 bell icon)"
  bashio::log.error ""
  bashio::log.fatal "   ⏸️  Installation paused. Complete MQTT setup and start LibreCoach."
  bashio::log.fatal ""
  exit 1
fi

# If we get here, MQTT is configured - dismiss any previous notifications
curl -s -X POST \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notification_id": "librecoach_mqtt_setup"}' \
  "http://supervisor/core/api/services/persistent_notification/dismiss" >/dev/null 2>&1

bashio::log.info "   MQTT integration is configured"
bashio::log.info ""

# ========================
# Phase 2: CAN-MQTT Bridge
# ========================
bashio::log.info "Phase 2: Installing CAN-MQTT Bridge"

# Check if CAN-MQTT Bridge is installed
if ! is_installed "$SLUG_CAN_BRIDGE"; then
    bashio::log.info "   Installing CAN-MQTT Bridge addon..."
    if ! install_addon "$SLUG_CAN_BRIDGE"; then
        bashio::log.fatal "❌ Failed to install CAN-MQTT Bridge addon"
        bashio::log.fatal "   This addon is essential for LibreCoach to function."
        exit 1
    fi
else
    bashio::log.info "   CAN-MQTT Bridge addon already installed"
fi

# Configure CAN-MQTT Bridge with our settings
bashio::log.info "   Configuring CAN-MQTT Bridge..."

# CAN bridge uses host_network: true, so Docker internal DNS (core-mosquitto) doesn't work.
# Use the hassio gateway IP which is accessible from the host network.
CAN_BRIDGE_MQTT_HOST="172.30.32.1"

bashio::log.info "   > MQTT Configuration:"
bashio::log.info "     - Host: $CAN_BRIDGE_MQTT_HOST (hassio gateway for host_network addon)"
bashio::log.info "     - Port: $MQTT_PORT"
bashio::log.info "     - User: $MQTT_USER"
bashio::log.info "     - Password: [${#MQTT_PASS} characters]"

# Use jq to construct the JSON, handling special characters in passwords
CAN_BRIDGE_CONFIG=$(jq -n \
  --arg can_interface "$CAN_INTERFACE" \
  --arg can_bitrate "$CAN_BITRATE" \
  --arg mqtt_host "$CAN_BRIDGE_MQTT_HOST" \
  --argjson mqtt_port "$MQTT_PORT" \
  --arg mqtt_user "$MQTT_USER" \
  --arg mqtt_pass "$MQTT_PASS" \
  --arg mqtt_topic_raw "$MQTT_TOPIC_RAW" \
  --arg mqtt_topic_send "$MQTT_TOPIC_SEND" \
  --arg mqtt_topic_status "$MQTT_TOPIC_STATUS" \
  '{ 
    "options": { 
      "can_interface": $can_interface,
      "can_bitrate": $can_bitrate,
      "mqtt_host": $mqtt_host,
      "mqtt_port": $mqtt_port,
      "mqtt_user": $mqtt_user,
      "mqtt_pass": $mqtt_pass,
      "mqtt_topic_raw": $mqtt_topic_raw,
      "mqtt_topic_send": $mqtt_topic_send,
      "mqtt_topic_status": $mqtt_topic_status,
      "debug_logging": false,
      "ssl": false
    }
  }'
)

result=$(api_call POST "/addons/$SLUG_CAN_BRIDGE/options" "$CAN_BRIDGE_CONFIG")
if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    bashio::log.info "   CAN-MQTT Bridge configured"
else
    bashio::log.error "   ⚠️  Failed to configure CAN-MQTT Bridge: $(echo "$result" | jq -r '.message')"
fi

# Set CAN-MQTT Bridge to start on boot
set_boot_auto "$SLUG_CAN_BRIDGE"

# Start CAN-MQTT Bridge and verify it stays running
bashio::log.info "   Starting CAN-MQTT Bridge..."
result=$(api_call POST "/addons/$SLUG_CAN_BRIDGE/start" "")
if ! echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
    bashio::log.warning "   ⚠️  Failed to start CAN-MQTT Bridge: $(echo "$result" | jq -r '.message')"
    BRIDGE_STATUS="failed_to_start"
else
    # Wait a few seconds for bridge to initialize and potentially fail
    sleep 5

    # Check if bridge is actually running
    if is_running "$SLUG_CAN_BRIDGE"; then
        bashio::log.info "   CAN-MQTT Bridge started successfully"
        BRIDGE_STATUS="running"
    else
        # Bridge started but then stopped - fetch logs to show why
        bashio::log.warning "   ⚠️  CAN-MQTT Bridge started but then stopped"
        bashio::log.warning "   Bridge error logs:"
        bridge_logs=$(get_addon_logs "$SLUG_CAN_BRIDGE" 20)
        # Extract and display FATAL or error lines
        echo "$bridge_logs" | grep -E "(FATAL|ERROR|❌)" | while IFS= read -r line; do
            bashio::log.warning "      $line"
        done
        BRIDGE_STATUS="stopped_after_start"
    fi
fi

# ========================
# Phase 3: Node-RED
# ========================
bashio::log.info "Phase 3: Installing Node-RED"

CONFIRM_TAKEOVER=$(bashio::config 'confirm_nodered_takeover')
NODERED_ALREADY_INSTALLED=false

if is_installed "$SLUG_NODERED"; then
  bashio::log.info "   Node-RED is already installed."
  NODERED_ALREADY_INSTALLED=true
else
  # Try to install Node-RED
  bashio::log.info "   Node-RED not found. Installing..."
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
  if is_nodered_managed; then
    MANAGED_VERSION=$(get_managed_version)
    bashio::log.info "   Node-RED already managed by LibreCoach (version $MANAGED_VERSION)"
  else
    # Node-RED exists but not managed by LibreCoach - need permission
    if [ "$CONFIRM_TAKEOVER" != "true" ]; then
       bashio::log.warning ""
       bashio::log.warning "   ⚠️  EXISTING INSTALLATION DETECTED"
       bashio::log.warning "   LibreCoach needs to configure Node-RED to run the LibreCoach project."
       bashio::log.warning "   This will REPLACE your active Node-RED flows."
       bashio::log.warning "   "
       bashio::log.warning "   To proceed, you must explicitly grant permission:"
       bashio::log.warning "   1. Go to the LibreCoach add-on configuration."
       bashio::log.warning "   2. Enable 'confirm_nodered_takeover'."
       bashio::log.warning "   3. Restart LibreCoach."
       bashio::log.warning ""
       bashio::log.fatal "   ❌ Installation aborted to protect existing flows."
       exit 1
    else
       bashio::log.info "   ✅ Permission granted to take over Node-RED."
    fi
  fi
fi

# Configure Node-RED
NR_INFO=$(api_call GET "/addons/$SLUG_NODERED/info")
log_debug "NR_INFO response: $NR_INFO"
NR_OPTIONS=$(echo "$NR_INFO" | jq '.data.options // {}')
log_debug "NR_OPTIONS extracted: $NR_OPTIONS"
SECRET=$(echo "$NR_OPTIONS" | jq -r '.credential_secret // empty')

# Init command runs the script deployed to /share/.librecoach/
# The script uses MQTT_* environment variables set via env_vars
SETTINGS_INIT_CMD="bash /share/.librecoach/init-nodered.sh"

NEEDS_RESTART=false

# Define MQTT Env Vars for Node-RED
MQTT_ENV_VARS=$(jq -n \
  --arg user "$MQTT_USER" \
  --arg pass "$MQTT_PASS" \
  '[
  {"name": "MQTT_USER", "value": $user},
  {"name": "MQTT_PASS", "value": $pass},
  {"name": "MQTT_HOST", "value": "homeassistant"},
  {"name": "MQTT_PORT", "value": "1883"}
]')

if [ -z "$SECRET" ]; then
  bashio::log.info "   No credential_secret found. Generating one..."
  NEW_SECRET=$(openssl rand -hex 16)
  NEW_OPTIONS=$(echo "$NR_OPTIONS" | jq \
    --arg secret "$NEW_SECRET" \
    --arg initcmd "$SETTINGS_INIT_CMD" \
    --arg user "$MQTT_USER" \
    --arg pass "$MQTT_PASS" \
    --argjson env_vars "$MQTT_ENV_VARS" \
    '. + {"credential_secret": $secret, "ssl": false, "init_commands": [$initcmd], "env_vars": $env_vars, "users": [{"username": $user, "password": $pass, "permissions": "*"}]}')
  bashio::log.info "   > Node-RED user being configured: $MQTT_USER"
  log_debug "Node-RED options: $(echo "$NEW_OPTIONS" | jq -c '.users')"
  set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
  NEEDS_RESTART=true
else
  CURRENT_INIT_CMD=$(echo "$NR_OPTIONS" | jq -r '.init_commands[0] // empty')
  CURRENT_USER=$(echo "$NR_OPTIONS" | jq -r --arg user "$MQTT_USER" '(.users // [])[] | select(.username == $user) | .username')
  
  # Check if config needs updating (init command changed, user missing, or env vars different)
  if [ "$CURRENT_INIT_CMD" != "$SETTINGS_INIT_CMD" ] || [ -z "$CURRENT_USER" ] || [ "$(echo "$NR_OPTIONS" | jq '.env_vars')" != "$MQTT_ENV_VARS" ]; then
    bashio::log.info "   > Updating Node-RED configuration (init commands / users / env_vars)..."
    NEW_OPTIONS=$(echo "$NR_OPTIONS" | jq \
      --arg initcmd "$SETTINGS_INIT_CMD" \
      --arg user "$MQTT_USER" \
      --arg pass "$MQTT_PASS" \
      --argjson env_vars "$MQTT_ENV_VARS" \
      ' 
      . + {"init_commands": [$initcmd], "env_vars": $env_vars} |
      .users = (.users // []) |
      .users |= (map(select(.username != $user)) + [{"username": $user, "password": $pass, "permissions": "*"}])
    ')
    set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
    NEEDS_RESTART=true
  else
    bashio::log.info "   Node-RED configuration is up to date"
  fi
fi

# Verify Node-RED configuration was applied
NR_VERIFY=$(api_call GET "/addons/$SLUG_NODERED/info" | jq -r '.data.options.users // "null"')
bashio::log.info "   > Node-RED users configured: $NR_VERIFY"

# Ensure Node-RED starts/restarts to apply init commands
if [ "$NEEDS_RESTART" = "true" ]; then
  if is_running "$SLUG_NODERED"; then
    bashio::log.info "   > Restarting Node-RED to apply new configuration..."
    restart_addon "$SLUG_NODERED" || exit 1
  else
    bashio::log.info "   > Starting Node-RED with new configuration..."
    start_addon "$SLUG_NODERED" || exit 1
    
    # Force a restart after fresh start to fix race condition:
    # On first boot, Node-RED's initialization may interfere with init_commands.
    # A restart ensures init_commands run cleanly on an initialized volume.
    bashio::log.info "   > Performing initialization restart to ensure init_commands take effect..."
    sleep 5
    restart_addon "$SLUG_NODERED" || exit 1
  fi
else
  if ! is_running "$SLUG_NODERED"; then
    start_addon "$SLUG_NODERED" || exit 1
  fi
fi

# After starting/restarting, wait for the API to be available.
# This ensures the init_command has run and flows are loaded before we proceed.
if ! wait_for_nodered_api; then
    bashio::log.fatal "   ❌ Node-RED API did not become available. Cannot deploy flows."
    exit 1
fi

# Now, trigger a flow deployment. This is the equivalent of clicking the
# "Deploy" button in the UI and forces MQTT nodes to activate their connection.
if ! deploy_nodered_flows; then
    bashio::log.warning "   ⚠️  Flow deployment failed. MQTT nodes may not connect."
    bashio::log.warning "   You may need to open Node-RED and click 'Deploy' manually."
fi

# Ensure Node-RED starts on boot
set_boot_auto "$SLUG_NODERED" || bashio::log.warning "   ⚠️  Could not set Node-RED to auto-start"

# Mark/update Node-RED as managed by LibreCoach (updates version on upgrades)
mark_nodered_managed

# ========================
# Installation Summary
# ========================
echo ""
bashio::log.info "╔════════════════════════════════════════════════════════════╗"
bashio::log.info "║          LibreCoach Installation Summary                  ║"
bashio::log.info "╔════════════════════════════════════════════════════════════╗"
bashio::log.info ""
bashio::log.info "  MQTT Integration ................ ✅ Configured"
bashio::log.info "  Mosquitto MQTT Broker ........... ✅ Running"
if [ "$BRIDGE_STATUS" = "running" ]; then
    bashio::log.info "  CAN-MQTT Bridge ................. ✅ Running"
elif [ "$BRIDGE_STATUS" = "stopped_after_start" ]; then
    bashio::log.warning "  CAN-MQTT Bridge ................. ⚠️  FAILED"
    bashio::log.warning "    └─ Bridge stopped after startup (MQTT auth failure likely)"
    bashio::log.warning "    └─ Check MQTT credentials in LibreCoach configuration"
    bashio::log.warning "    └─ View full error: Settings → Add-ons → CAN-MQTT Bridge → Logs"
elif [ "$BRIDGE_STATUS" = "failed_to_start" ]; then
    bashio::log.warning "  CAN-MQTT Bridge ................. ⚠️  FAILED TO START"
    bashio::log.warning "    └─ Check if CAN hardware is connected"
else
    bashio::log.warning "  CAN-MQTT Bridge ................. ⚠️  UNKNOWN STATUS"
fi
bashio::log.info "  Node-RED ........................ ✅ Configured"
bashio::log.info ""
if [ "$BRIDGE_STATUS" = "running" ]; then
    bashio::log.info "  🎉 All components installed successfully!"
else
    bashio::log.warning "  ⚠️  Installation completed with warnings - see above"
fi
bashio::log.info ""
bashio::log.info "╚════════════════════════════════════════════════════════════╝"
bashio::log.info ""
bashio::log.info "🚐 See the Overview Dashboard for new LibreCoach entities"
bashio::log.info "🚐 Visit https://LibreCoach.com for more information"
bashio::log.info ""
bashio::log.info "   ✅ LibreCoach setup complete."
bashio::log.info "   You only need to restart this addon when updating LibreCoach."