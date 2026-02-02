#!/bin/bash
# Node-RED initialization script for LibreCoach
# This script runs inside the Node-RED container on startup via init_commands
# Environment variables MQTT_USER, MQTT_PASS are set via Node-RED addon env_vars

set -e

PROJECT_DIR="/config/projects/librecoach-node-red"
SOURCE_DIR="/share/.librecoach"

# Create project directories
mkdir -p "$PROJECT_DIR/rvc"

# Copy RVC decoder data
cp -r "$SOURCE_DIR/rvc/." "$PROJECT_DIR/rvc/"

# Copy package.json to config directory for Node-RED dependencies
cp "$SOURCE_DIR/package.json" /config/package.json

# Inject MQTT credentials into flows.json and copy to Node-RED config
jq --arg user "$MQTT_USER" --arg pass "$MQTT_PASS" \
  '(.[] | select(.type == "mqtt-broker")) |= . + {
    "broker": "mqtt://homeassistant:1883",
    "credentials": {"user": $user, "password": $pass}
  }' "$SOURCE_DIR/flows.json" > /config/flows.json

echo "LibreCoach Node-RED initialization complete"
