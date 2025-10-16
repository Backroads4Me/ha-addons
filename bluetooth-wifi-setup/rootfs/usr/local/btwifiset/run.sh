#!/usr/bin/with-contenv bashio
# Copyright 2025 Ted Lanham
# Licensed under the MIT License

set -e

CONFIG_PATH=/data/options.json

# Read configuration
TIMEOUT=$(bashio::config 'bluetooth_timeout')
LOG_LEVEL=$(bashio::config 'log_level')
DEVICE_NAME=$(bashio::config 'device_name')
KEEP_ALIVE=$(bashio::config 'keep_alive')
ENCRYPTION_ENABLED=$(bashio::config 'encryption_enabled')
PASSWORD=$(bashio::config 'password' '')

bashio::log.info "Starting Bluetooth WiFi Setup addon..."
bashio::log.info "Timeout: ${TIMEOUT} minutes"
bashio::log.info "Log level: ${LOG_LEVEL}"
bashio::log.info "Device name: ${DEVICE_NAME}"

# Check for Bluetooth adapter via sysfs
if ! ls /sys/class/bluetooth/hci* > /dev/null 2>&1; then
    bashio::log.error "No Bluetooth adapter found!"
    bashio::log.error "Please ensure your system has a Bluetooth adapter and BlueZ is accessible."
    exit 1
fi

# Check for WiFi adapter
if [ ! -d /sys/class/net/wlan0 ]; then
    bashio::log.warning "WiFi adapter wlan0 not found!"
    bashio::log.warning "The addon may not function correctly without a WiFi adapter."
fi

# Check if NetworkManager is accessible via D-Bus
if ! dbus-send --system --print-reply --dest=org.freedesktop.NetworkManager /org/freedesktop/NetworkManager org.freedesktop.DBus.Introspectable.Introspect > /dev/null 2>&1; then
    bashio::log.error "NetworkManager is not accessible via D-Bus!"
    bashio::log.error "This addon requires NetworkManager D-Bus API to configure WiFi."
    exit 1
fi

# Map log level to Python logging level
case "${LOG_LEVEL}" in
    debug)
        PYTHON_LOG_LEVEL="10"
        ;;
    info)
        PYTHON_LOG_LEVEL="20"
        ;;
    warning)
        PYTHON_LOG_LEVEL="30"
        ;;
    error)
        PYTHON_LOG_LEVEL="40"
        ;;
    *)
        PYTHON_LOG_LEVEL="20"
        ;;
esac

# Handle keep_alive option
if [ "${KEEP_ALIVE}" = "true" ]; then
    bashio::log.warning "Keep-alive mode enabled. Addon will not auto-shutdown."
    bashio::log.warning "This may pose a security risk. Disable when not needed."
    TIMEOUT=999999
fi

# Create password file if encryption is enabled
if [ "${ENCRYPTION_ENABLED}" = "true" ] && [ -n "${PASSWORD}" ]; then
    echo "${PASSWORD}" > /tmp/crypto
    bashio::log.info "Encryption enabled with custom password"
elif [ "${ENCRYPTION_ENABLED}" = "true" ]; then
    hostname > /tmp/crypto
    bashio::log.info "Encryption enabled with hostname as password"
fi

# Start the Python script
bashio::log.info "Starting BLE server..."

cd /usr/local/btwifiset

exec python3 /usr/local/btwifiset/btwifiset.py \
    --timeout "${TIMEOUT}" \
    --console
