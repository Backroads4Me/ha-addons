#!/usr/bin/with-contenv bashio
# CAN to MQTT Bridge Main Script

set -e

# Ensure we're running as s6 service
if [ -z "${S6_SERVICE_PATH+x}" ]; then
  bashio::log.warning "This script is designed to run as an s6 service"
fi

# Create health check file directory
mkdir -p /var/run/s6/healthcheck

# ========================
# Configuration Loading
# ========================
CAN_INTERFACE=$(bashio::config 'can_interface')
CAN_BITRATE=$(bashio::config 'can_bitrate')

# Try to use service discovery for MQTT broker
if bashio::services.available "mqtt"; then
    bashio::log.info "MQTT service discovered"
    MQTT_HOST=$(bashio::services "mqtt" "host")
    MQTT_PORT=$(bashio::services "mqtt" "port")
    MQTT_USER=$(bashio::services "mqtt" "username")
    MQTT_PASS=$(bashio::services "mqtt" "password")
else
    # Fall back to manual configuration
    bashio::log.info "Using manual MQTT configuration"
    MQTT_HOST=$(bashio::config 'mqtt_host')
    MQTT_PORT=$(bashio::config 'mqtt_port')
    MQTT_USER=$(bashio::config 'mqtt_user')
    MQTT_PASS=$(bashio::config 'mqtt_pass')
fi
MQTT_TOPIC_RAW=$(bashio::config 'mqtt_topic_raw')
MQTT_TOPIC_SEND=$(bashio::config 'mqtt_topic_send')
MQTT_TOPIC_STATUS=$(bashio::config 'mqtt_topic_status')
DEBUG_LOGGING=$(bashio::config 'debug_logging')
SSL=$(bashio::config 'ssl')
PASSWORD=$(bashio::config 'password')

# Security settings
MQTT_SSL_ARGS=""
if [ "$SSL" = "true" ]; then
    MQTT_SSL_ARGS="--cafile /etc/ssl/certs/ca-certificates.crt --tls-version tlsv1.2"
    bashio::log.info "SSL enabled for MQTT connections"
fi

# Password protection
if [ -n "$PASSWORD" ]; then
    bashio::log.info "Password protection enabled"
fi

# Global process tracking
CAN_TO_MQTT_PID=""
MQTT_TO_CAN_PID=""

# ========================
# Configuration Validation
# ========================
validate_config() {
    bashio::log.info "Validating configuration..."

    # Validate MQTT connection parameters
    if [[ -z "$MQTT_HOST" ]]; then
        bashio::log.fatal "MQTT host is required"
        return 1
    fi

    # Validate MQTT port
    if ! [[ "$MQTT_PORT" =~ ^[0-9]+$ ]] || [ "$MQTT_PORT" -lt 1 ] || [ "$MQTT_PORT" -gt 65535 ]; then
        bashio::log.fatal "Invalid MQTT port: $MQTT_PORT"
        return 1
    fi

    bashio::log.info "✅ Configuration validation passed"
    return 0
}


# ========================
# Health Check Function
# ========================
update_health_check() {
    local status=$1
    echo "$status" > /var/run/s6/healthcheck/status

    # Status is published only at startup and shutdown
}


# ========================
# Cleanup Function
# ========================
cleanup() {
    bashio::log.info "Shutdown signal received. Cleaning up..."
    
    # Kill background processes
    if [ -n "$CAN_TO_MQTT_PID" ] && kill -0 "$CAN_TO_MQTT_PID" 2>/dev/null; then
        bashio::log.info "Stopping CAN->MQTT bridge (PID: $CAN_TO_MQTT_PID)"
        kill -TERM "$CAN_TO_MQTT_PID" 2>/dev/null || true
    fi
    
    if [ -n "$MQTT_TO_CAN_PID" ] && kill -0 "$MQTT_TO_CAN_PID" 2>/dev/null; then
        bashio::log.info "Stopping MQTT->CAN bridge (PID: $MQTT_TO_CAN_PID)"
        kill -TERM "$MQTT_TO_CAN_PID" 2>/dev/null || true
    fi
    
    # Stop web server if running
    if [ -n "$WEB_SERVER_PID" ] && kill -0 "$WEB_SERVER_PID" 2>/dev/null; then
        bashio::log.info "Stopping web server (PID: $WEB_SERVER_PID)"
        kill -TERM "$WEB_SERVER_PID" 2>/dev/null || true
    fi
    
    # Publish offline status
    mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" \
                  ${MQTT_USER:+-u "$MQTT_USER"} ${MQTT_PASS:+-P "$MQTT_PASS"} \
                  -t "$MQTT_TOPIC_STATUS" -m "bridge_offline" -q 1 -r 2>/dev/null || true
    
    # Bring down CAN interface
    ip link set "$CAN_INTERFACE" down 2>/dev/null || true

    bashio::log.info "Cleanup completed"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT SIGQUIT

# ========================
# Startup Banner
# ========================
bashio::log.info "=== CAN to MQTT Bridge Starting ==="
bashio::log.info "CAN Interface: $CAN_INTERFACE @ ${CAN_BITRATE} bps"
bashio::log.info "MQTT Broker: $MQTT_HOST:$MQTT_PORT"
bashio::log.info "MQTT User: ${MQTT_USER:-'(none)'}"
bashio::log.info "Topics - Raw: $MQTT_TOPIC_RAW, Send: $MQTT_TOPIC_SEND, Status: $MQTT_TOPIC_STATUS"
bashio::log.info "Debug Logging: ${DEBUG_LOGGING}"
if [ "$DEBUG_LOGGING" = "true" ]; then
    bashio::log.info "Verbose debug logging is ENABLED"
else
    bashio::log.info "Verbose debug logging is disabled"
fi
echo

# ========================
# CAN Interface Initialization
# ========================
bashio::log.info "Initializing CAN interface..."

# Print current status for debugging
bashio::log.info "Current interface status:"
ip link show "$CAN_INTERFACE" 2>/dev/null || bashio::log.info "Interface $CAN_INTERFACE not found (this may be normal)"

# If the device is already up, bring it down first
if [ -f "/sys/class/net/$CAN_INTERFACE/operstate" ] && [ "$(cat "/sys/class/net/$CAN_INTERFACE/operstate")" = "up" ]; then
    bashio::log.info "Interface is up, bringing it down first"
    ip link set "$CAN_INTERFACE" down
fi

# Set up CAN interface with bitrate (exact copy from working add-on)
bashio::log.info "Setting up CAN interface with bitrate $CAN_BITRATE"
if ! ip link set "$CAN_INTERFACE" up type can bitrate "$CAN_BITRATE"; then
    bashio::log.fatal "Failed to set CAN interface up with bitrate $CAN_BITRATE"
    bashio::log.fatal "Please ensure CAN hardware is connected and recognized"
    exit 1
fi

# Bring interface up (second command from working add-on)
if ! ip link set "$CAN_INTERFACE" up; then
    bashio::log.fatal "Failed to bring CAN interface up"
    exit 1
fi

# Print final status for debugging
bashio::log.info "Final interface status:"
ip link show "$CAN_INTERFACE"

bashio::log.info "✅ CAN interface $CAN_INTERFACE initialized successfully at ${CAN_BITRATE} bps"

# ========================
# Configuration & MQTT Connection Test
# ========================
# Run configuration validation
if ! validate_config; then
    bashio::log.fatal "Configuration validation failed. Exiting."
    exit 1
fi

bashio::log.info "Testing MQTT connection..."

MQTT_AUTH_ARGS=""
[ -n "$MQTT_USER" ] && MQTT_AUTH_ARGS="$MQTT_AUTH_ARGS -u $MQTT_USER"
[ -n "$MQTT_PASS" ] && MQTT_AUTH_ARGS="$MQTT_AUTH_ARGS -P $MQTT_PASS"

if mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" $MQTT_AUTH_ARGS \
   -t "$MQTT_TOPIC_STATUS" -m "bridge_starting" -q 1 >/dev/null 2>&1; then
    bashio::log.info "✅ MQTT connection successful"
else
    bashio::log.fatal "❌ MQTT connection failed - check broker settings and credentials"
    exit 1
fi


# ========================
# Start Bridge Processes
# ========================

# CAN -> MQTT Bridge (simplified persistent connection)
bashio::log.info "Starting CAN->MQTT bridge..."
{
    while true; do
        candump -L "$CAN_INTERFACE" 2>/dev/null | awk '{print $3}' | \
        while IFS= read -r frame; do
            if [ -n "$frame" ]; then
                echo "$frame"
            fi
        done | mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" $MQTT_AUTH_ARGS \
                            -t "$MQTT_TOPIC_RAW" -q 1 -l

        bashio::log.warning "CAN->MQTT bridge disconnected, reconnecting in 30 seconds..."
        sleep 30
    done
} &
CAN_TO_MQTT_PID=$!
bashio::log.info "✅ CAN->MQTT bridge started (PID: $CAN_TO_MQTT_PID)"

# MQTT -> CAN Bridge (with error handling and reconnection)
bashio::log.info "Starting MQTT->CAN bridge..."
{
    while true; do
        [ "$DEBUG_LOGGING" = "true" ] && bashio::log.info "[DEBUG] Starting MQTT->CAN bridge connection"
        mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" $MQTT_AUTH_ARGS \
                      -t "$MQTT_TOPIC_SEND" -q 1 2>/dev/null | \
        while IFS= read -r message; do
            if [ -n "$message" ]; then
                [ "$DEBUG_LOGGING" = "true" ] && bashio::log.info "[DEBUG] MQTT->CAN received: $message"

                # Convert frame format if needed (from raw hex to ID#DATA format)
                if [[ "$message" =~ ^[0-9A-Fa-f]+$ ]] && [[ ${#message} -gt 8 ]]; then
                    # Extract CAN ID (first 8 characters) and data (remaining)
                    raw_can_id="${message:0:8}"
                    can_data="${message:8}"

                    # Pad CAN ID to 8 characters if needed for Extended Frame Format
                    if [ ${#raw_can_id} -lt 8 ]; then
                        # Pad with leading zeros to make it 8 chars (Extended Frame Format)
                        can_id=$(printf "%08s" "$raw_can_id")
                    else
                        can_id="$raw_can_id"
                    fi

                    # Validate data length (max 8 bytes = 16 hex chars)
                    if [ ${#can_data} -gt 16 ]; then
                        bashio::log.warning "[$(date '+%H:%M:%S')] Data too long (${#can_data} chars), truncating to 16 chars"
                        can_data="${can_data:0:16}"
                    fi

                    formatted_message="${can_id}#${can_data}"
                    [ "$DEBUG_LOGGING" = "true" ] && bashio::log.info "[DEBUG] Converted: $message -> $formatted_message"
                else
                    # Check if it's already in ID#DATA format but needs CAN ID padding
                    if [[ "$message" =~ ^[0-9A-Fa-f]+#[0-9A-Fa-f]*$ ]]; then
                        # Split existing ID#DATA format
                        existing_id="${message%#*}"
                        existing_data="${message#*#}"

                        # Pad CAN ID if it's 7 characters (common for Extended Frames)
                        if [ ${#existing_id} -eq 7 ]; then
                            padded_id="0${existing_id}"
                            formatted_message="${padded_id}#${existing_data}"
                            [ "$DEBUG_LOGGING" = "true" ] && bashio::log.info "[DEBUG] Padded CAN ID: $message -> $formatted_message"
                        else
                            formatted_message="$message"
                        fi
                    else
                        # Different format, use as-is
                        formatted_message="$message"
                    fi
                fi

                # Send with error logging
                if cansend_output=$(cansend "$CAN_INTERFACE" "$formatted_message" 2>&1); then
                    [ "$DEBUG_LOGGING" = "true" ] && bashio::log.info "[DEBUG] Successfully sent CAN frame: $formatted_message"
                else
                    bashio::log.error "Failed to send CAN frame: $formatted_message"
                    bashio::log.error "Error details: $cansend_output"
                    bashio::log.error "Original MQTT message: $message"
                fi
            fi
        done
        
        bashio::log.warning "MQTT->CAN bridge disconnected, reconnecting in 30 seconds..."
        sleep 30
    done
} &
MQTT_TO_CAN_PID=$!
bashio::log.info "✅ MQTT->CAN bridge started (PID: $MQTT_TO_CAN_PID)"

# ========================
# Announce Online Status
# ========================
sleep 2  # Give bridges time to start

# Use a single connection for status messages
{
    echo "bridge_online"
    sleep 1
} | mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" $MQTT_AUTH_ARGS \
                  -t "$MQTT_TOPIC_STATUS" -q 1 -r -l

# ========================
# Start Ingress Web Server
# ========================
if bashio::var.true "$(bashio::addon.ingress)"; then
    bashio::log.info "Starting ingress web server..."
    
    # Create simple status page
    mkdir -p /var/www
    cat > /var/www/index.html << EOF
<!DOCTYPE html>
<html>
<head>
    <title>CAN to MQTT Bridge</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        .status { padding: 10px; margin: 10px 0; border-radius: 4px; }
        .online { background-color: #d4edda; color: #155724; }
        .offline { background-color: #f8d7da; color: #721c24; }
        .card { background: white; border-radius: 8px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #333; }
    </style>
</head>
<body>
    <h1>CAN to MQTT Bridge</h1>
    <div class="card">
        <h2>Status</h2>
        <div id="status" class="status online">Bridge is online</div>
    </div>
    <div class="card">
        <h2>Configuration</h2>
        <p><strong>CAN Interface:</strong> ${CAN_INTERFACE}</p>
        <p><strong>CAN Bitrate:</strong> ${CAN_BITRATE} bps</p>
        <p><strong>MQTT Broker:</strong> ${MQTT_HOST}:${MQTT_PORT}</p>
    </div>
</body>
</html>
EOF

    # Start simple web server
    cd /var/www
    python3 -m http.server 8099 &
    WEB_SERVER_PID=$!
    bashio::log.info "✅ Web server started (PID: $WEB_SERVER_PID)"
fi

bashio::log.info "🚀 CAN-MQTT Bridge is now running!"
bashio::log.info "Monitoring bridge processes. Press Ctrl+C or stop the add-on to shutdown."

# ========================
# Process Monitoring
# ========================
while true; do
    # Check if either process died
    if ! kill -0 "$CAN_TO_MQTT_PID" 2>/dev/null; then
        bashio::log.error "CAN->MQTT process died unexpectedly (PID: $CAN_TO_MQTT_PID)"
        update_health_check "UNHEALTHY: CAN->MQTT process died"
        cleanup
        exit 1
    fi

    if ! kill -0 "$MQTT_TO_CAN_PID" 2>/dev/null; then
        bashio::log.error "MQTT->CAN process died unexpectedly (PID: $MQTT_TO_CAN_PID)"
        update_health_check "UNHEALTHY: MQTT->CAN process died"
        cleanup
        exit 1
    fi

    # Log process health every hour for basic monitoring
    if [ $(($(date +%s) % 3600)) -eq 0 ]; then
        bashio::log.info "Process monitor: CAN->MQTT (PID: $CAN_TO_MQTT_PID), MQTT->CAN (PID: $MQTT_TO_CAN_PID) - all healthy"
    fi

    # Update health check status (local file only)
    update_health_check "OK"

    # Wait before next check
    sleep 10
done