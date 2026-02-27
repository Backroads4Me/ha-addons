#!/bin/bash
# Node-RED initialization script for LibreCoach
# This script runs inside the Node-RED container on startup via init_commands
#
# Credentials are stored in flows_cred.json, encrypted with credential_secret="librecoach"
# The LibreCoach orchestrator sets this credential_secret in the Node-RED addon options

set -e

# Robust Suicide Check: Exit if LibreCoach is gone
OWNER_SLUG="REPLACE_ME" # Injected by run.sh to handle both beta and prod
SOURCE_DIR="/share/.librecoach"

if [ ! -d "$SOURCE_DIR" ]; then
    echo "LibreCoach source directory not found. Exiting."
    exit 0
fi

# Multi-retry check against Supervisor API to handle transient startup errors
MAX_RETRIES=3
for i in $(seq 1 $MAX_RETRIES); do
    # Get both body and status code. --max-time 3 allows for busy supervisor during boot.
    RESPONSE=$(curl -s -m 3 -H "Authorization: Bearer $SUPERVISOR_TOKEN" -w "\n%{http_code}" http://supervisor/addons/$OWNER_SLUG/info || echo -e "\n000")
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        # Check JSON for installed=true or state=started
        BODY_NOSPACE=$(echo "$BODY" | tr -d ' ' | tr -d '\n' | tr -d '\r')
        if echo "$BODY_NOSPACE" | grep -q '"installed":true' || echo "$BODY_NOSPACE" | grep -q '"state":"started"'; then
            echo "LibreCoach ($OWNER_SLUG) is verified installed."
            break
        else
            echo "LibreCoach ($OWNER_SLUG) exists but is not installed. Skipping."
            exit 0
        fi
    elif [ "$HTTP_CODE" = "404" ]; then
        echo "LibreCoach ($OWNER_SLUG) not found. Skipping initialization."
        exit 0
    else
        echo "Supervisor busy or error $HTTP_CODE (Attempt $i/$MAX_RETRIES). Retrying..."
        if [ $i -lt $MAX_RETRIES ]; then
            sleep 2
        else
            echo "Max retries reached. Unable to confirm LibreCoach status. Assuming NOT installed for safety."
            exit 0
        fi
    fi
done

PROJECT_DIR="/config/projects/librecoach-node-red"

# Create project directories
mkdir -p "$PROJECT_DIR/data"

# Copy Data/Decoder files
cp -r "$SOURCE_DIR/data/." "$PROJECT_DIR/data/"

# Copy package.json to config directory for Node-RED dependencies
# This ensures that LibreCoach-required nodes (e.g. node-red-contrib-markdown-note) 
# are automatically installed by Node-RED during its npm initialization phase.
cp "$SOURCE_DIR/package.json" /config/package.json

# Copy flows.json and flows_cred.json to Node-RED config
# flows_cred.json contains MQTT credentials encrypted with credential_secret="librecoach"
cp "$SOURCE_DIR/flows.json" /config/flows.json
cp "$SOURCE_DIR/flows_cred.json" /config/flows_cred.json

# Copy settings.js to Node-RED config
# This allows LibreCoach to inject custom environment variables, global contexts, 
# or specific node configurations required by the bundled flows.
cp "$SOURCE_DIR/data/settings.js" /config/settings.js

# Keep GPL license with the installed project
if [ -f "$SOURCE_DIR/LICENSE" ]; then
  cp "$SOURCE_DIR/LICENSE" "$PROJECT_DIR/LICENSE"
fi

echo "LibreCoach Node-RED initialization complete"
