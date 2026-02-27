#!/bin/bash
# Node-RED initialization script for LibreCoach (PRESERVE FLOWS MODE)
# This script runs inside the Node-RED container on startup via init_commands
#
# DIFFERENCE FROM STANDARD SCRIPT:
# This version DOES NOT copy flows.json or flows_cred.json.
# It only updates reference files and dependencies.

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

echo "LibreCoach: Running in PRESERVE FLOWS mode."
echo "   - Updating decodata files..."
echo "   - SKIPPING flows.json (User flows preserved)"

# Create project directories
mkdir -p "$PROJECT_DIR/data"

# Copy RVC decoder data
cp -r "$SOURCE_DIR/data/." "$PROJECT_DIR/data/"

echo "LibreCoach Node-RED initialization (Preserve Mode) complete"
