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

# Developer environments are left fully alone: when the dev sentinel is present we
# never touch /config/settings.js or run the context migration. A maintainer's
# settings.js carries dev-only configuration (Node-RED projects enabled, MQTT env
# injection, etc.) that the canonical file would clobber. The sentinel lives in the
# maintainer's own /share and is never committed to the repo.
if [ -f "/share/.librecoach-dev" ]; then
    echo "LibreCoach: Developer environment detected (/share/.librecoach-dev) — leaving settings.js and context untouched"
else

# Deploy settings.js even in preserve mode. It is LibreCoach-managed runtime
# config (context storage location, env injection) — not user flow content — so
# preserving flows must not freeze it. Required for the persistent context dir.
cp "$SOURCE_DIR/data/settings.js" /config/settings.js

# Migrate persistent context keys from the old default location (/config/context)
# to the new explicit location (/share/.librecoach/context), which survives add-on
# reinstalls. Carries forward ALL persisted keys (fill-if-absent, never overwrites)
# except those redesigned or reset in 2.0 (see EXCLUDE). Copying all keys — rather
# than a hand-maintained whitelist — preserves dynamic per-instance keys (e.g.
# dimmerBrightness_*, indicatorState_*) and any future keys.
node -e '
  const fs = require("fs");
  const OLD = "/config/context/global/global.json";
  const NEW_DIR = "/share/.librecoach/context/global";
  const NEW = NEW_DIR + "/global.json";
  // Keys redesigned or intentionally reset in 2.0 — do NOT carry forward.
  const EXCLUDE = new Set([
    "victronDevices", "betaDiscoveryTopics",
    "recordUnknown", "recordUnknownLog", "recordUnknownStart"
  ]);

  if (!fs.existsSync(OLD)) process.exit(0);

  let oldCtx;
  try { oldCtx = JSON.parse(fs.readFileSync(OLD, "utf8")); }
  catch (e) { process.exit(0); }

  fs.mkdirSync(NEW_DIR, { recursive: true });

  let newCtx = {};
  if (fs.existsSync(NEW)) {
    try { newCtx = JSON.parse(fs.readFileSync(NEW, "utf8")); } catch (e) {}
  }

  let count = 0;
  for (const [k, v] of Object.entries(oldCtx)) {
    if (EXCLUDE.has(k)) continue;
    if (newCtx[k] === undefined) { newCtx[k] = v; count++; }
  }

  if (count > 0) {
    fs.writeFileSync(NEW, JSON.stringify(newCtx, null, 4));
    console.log("LibreCoach: Migrated " + count + " context key(s) to /share/.librecoach/context/");
  }
' 2>/dev/null || echo "LibreCoach: Context migration skipped"

fi

echo "LibreCoach Node-RED initialization (Preserve Mode) complete"
