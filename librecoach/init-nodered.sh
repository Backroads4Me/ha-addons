#!/bin/bash
# Node-RED initialization script for LibreCoach
# This script runs inside the Node-RED container on startup via init_commands
#
# Credentials are stored in flows_cred.json, encrypted with credential_secret="librecoach"
# The LibreCoach orchestrator sets this credential_secret in the Node-RED addon options

set -e

PROJECT_DIR="/config/projects/librecoach-node-red"
SOURCE_DIR="/share/.librecoach"

# Create project directories
mkdir -p "$PROJECT_DIR/rvc"

# Copy RVC decoder data
cp -r "$SOURCE_DIR/rvc/." "$PROJECT_DIR/rvc/"

# Copy package.json to config directory for Node-RED dependencies
cp "$SOURCE_DIR/package.json" /config/package.json

# Copy flows.json and flows_cred.json to Node-RED config
# flows_cred.json contains MQTT credentials encrypted with credential_secret="librecoach"
cp "$SOURCE_DIR/flows.json" /config/flows.json
cp "$SOURCE_DIR/flows_cred.json" /config/flows_cred.json

# Keep GPL license with the installed project
if [ -f "$SOURCE_DIR/LICENSE" ]; then
  cp "$SOURCE_DIR/LICENSE" "$PROJECT_DIR/LICENSE"
fi

echo "LibreCoach Node-RED initialization complete"
