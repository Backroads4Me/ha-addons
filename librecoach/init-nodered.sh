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

# Copy flows.json (already configured with ${MQTT_USER} and ${MQTT_PASS} env var references)
cp "$SOURCE_DIR/flows.json" /config/flows.json

# Copy settings.js (sets credentialSecret to "librecoach" for consistent credential encryption)
cp "$SOURCE_DIR/settings.js" /config/settings.js

echo "LibreCoach Node-RED initialization complete"
