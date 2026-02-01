#!/bin/bash
# Node-RED initialization script for LibreCoach
# This script runs inside the Node-RED container on startup via init_commands
# Environment variables MQTT_USER, MQTT_PASS, MQTT_HOST, MQTT_PORT are set by run.sh

set -e

PROJECT_DIR="/config/projects/librecoach-node-red"
SOURCE_DIR="/share/.librecoach"

# Create project directories
mkdir -p "$PROJECT_DIR/rvc"

# Copy RVC decoder data
cp -r "$SOURCE_DIR/rvc/." "$PROJECT_DIR/rvc/"

# Copy package.json to config directory for Node-RED dependencies
cp "$SOURCE_DIR/package.json" /config/package.json

# Configure flows.json with MQTT broker credentials
# Updates the mqtt-broker node with connection details from environment
jq --arg user "${MQTT_USER:-librecoach}" \
   --arg pass "${MQTT_PASS:-}" \
   --arg host "${MQTT_HOST:-homeassistant}" \
   --arg port "${MQTT_PORT:-1883}" \
   '(.[] | select(.type == "mqtt-broker")) |= . + {
     "broker": ("mqtt://" + $host + ":" + $port),
     "credentials": {"user": $user, "password": $pass}
   }' "$SOURCE_DIR/flows.json" > /config/flows.json

echo "LibreCoach Node-RED initialization complete"
