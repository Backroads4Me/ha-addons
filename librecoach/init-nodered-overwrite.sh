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

echo "LibreCoach owns Node-RED flows unless 'prevent_flow_updates' is enabled"
echo "in the LibreCoach add-on configuration. Local edits to flows are backed"
echo "up before being overwritten."

# ---------------------------------------------------------------------------
# Drift detection: hashes of the files LibreCoach last deployed are recorded
# in $HASH_FILE. If a tracked file in /config no longer matches its recorded
# hash, the user edited it directly — copy it to a timestamped backup before
# overwriting.
# ---------------------------------------------------------------------------
HASH_FILE="/config/.librecoach-deployed-hashes"
BACKUP_ROOT="/config/librecoach-backups"
BACKUP_DIR="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"

deployed_hash() {
    # Recorded hash of a file from the previous deployment ("" if unknown)
    [ -f "$HASH_FILE" ] || { echo ""; return; }
    awk -v f="$1" '$2 == f {print $1}' "$HASH_FILE"
}

backup_if_drifted() {
    local file=$1
    local source=$2
    [ -f "/config/$file" ] || return 0
    local last current
    last=$(deployed_hash "$file")
    current=$(md5sum "/config/$file" | cut -d' ' -f1)
    if [ -z "$last" ]; then
        # No recorded hash: first upgrade from a pre-hash-tracking version, the
        # riskiest case — we can't know whether the user edited the file. Fall
        # back to comparing against the bundled file about to be deployed and
        # back up on any difference. This may save a copy that was never
        # hand-edited (e.g. flows_cred.json is re-encrypted with a fresh IV on
        # every start), but a redundant backup beats destroying a user's only
        # copy of their edits.
        if [ -f "$SOURCE_DIR/$source" ] && [ "$current" = "$(md5sum "$SOURCE_DIR/$source" | cut -d' ' -f1)" ]; then
            return 0
        fi
        mkdir -p "$BACKUP_DIR"
        cp "/config/$file" "$BACKUP_DIR/$file"
        echo "NOTICE: /config/$file differs from the bundled version and no deployment"
        echo "        record exists yet (first run with drift tracking). A copy was"
        echo "        saved to $BACKUP_DIR/$file before overwriting."
        return 0
    fi
    if [ "$current" != "$last" ]; then
        mkdir -p "$BACKUP_DIR"
        cp "/config/$file" "$BACKUP_DIR/$file"
        echo "NOTICE: /config/$file was edited outside LibreCoach."
        echo "        A copy was saved to $BACKUP_DIR/$file before overwriting."
    fi
}

backup_if_drifted "flows.json" "artifact/flows.json"
backup_if_drifted "flows_cred.json" "flows_cred.json"
backup_if_drifted "package.json" "package.json"

# Create project directories
mkdir -p "$PROJECT_DIR/data"

# Copy Data/Decoder files
cp -r "$SOURCE_DIR/data/." "$PROJECT_DIR/data/"

# Copy package.json to config directory for Node-RED dependencies
# This ensures that LibreCoach-required nodes (e.g. node-red-contrib-markdown-note)
# are automatically installed by Node-RED during its npm initialization phase.
# User-added dependencies (not part of the bundled package.json) are merged back
# in so direct `npm install`s survive updates; on any merge failure the bundled
# file is used as-is.
if [ -f /config/package.json ] && command -v node >/dev/null 2>&1; then
    if node -e '
        const fs = require("fs");
        const bundled = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
        const current = JSON.parse(fs.readFileSync("/config/package.json", "utf8"));
        const merged = { ...bundled };
        merged.dependencies = { ...(current.dependencies || {}), ...(bundled.dependencies || {}) };
        fs.writeFileSync("/config/package.json.tmp", JSON.stringify(merged, null, 2) + "\n");
    ' "$SOURCE_DIR/package.json" 2>/dev/null; then
        mv /config/package.json.tmp /config/package.json
        echo "Merged user-added package.json dependencies with bundled dependencies"
    else
        rm -f /config/package.json.tmp
        echo "WARNING: package.json merge failed — using bundled package.json"
        cp "$SOURCE_DIR/package.json" /config/package.json
    fi
else
    cp "$SOURCE_DIR/package.json" /config/package.json
fi

# Copy the generated flow artifact and credentials to Node-RED config
# node-red-contrib-flow-splitter-extended writes the deployable flows file to artifact/.
# flows_cred.json contains MQTT credentials encrypted with credential_secret="librecoach"
if [ ! -f "$SOURCE_DIR/artifact/flows.json" ]; then
    echo "ERROR: flows.json not found at $SOURCE_DIR/artifact/flows.json"
    echo "This usually means LibreCoach needs to be updated. Please update LibreCoach"
    echo "to the latest version in Settings → Add-ons, then restart it."
    exit 1
fi
cp "$SOURCE_DIR/artifact/flows.json" /config/flows.json
cp "$SOURCE_DIR/flows_cred.json" /config/flows_cred.json

# Copy settings.js to Node-RED config, unless this is a developer environment.
# A maintainer's settings.js carries dev-only configuration (Node-RED projects
# enabled, MQTT env injection, etc.) that the canonical file would clobber, so the
# .librecoach-dev sentinel (in the maintainer's own /share, never committed)
# exempts settings.js from being overwritten.
if [ -f "/share/.librecoach-dev" ]; then
    echo "LibreCoach: Developer environment detected (/share/.librecoach-dev) — leaving settings.js untouched"
else
    cp "$SOURCE_DIR/data/settings.js" /config/settings.js
fi

# Record the hashes of what was just deployed so the next run can detect drift.
{
    for f in flows.json flows_cred.json package.json; do
        [ -f "/config/$f" ] && md5sum "/config/$f" | awk -v f="$f" '{print $1, f}'
    done
} > "$HASH_FILE"

# Keep GPL license with the installed project
if [ -f "$SOURCE_DIR/LICENSE" ]; then
  cp "$SOURCE_DIR/LICENSE" "$PROJECT_DIR/LICENSE"
fi

# Migrate persistent context keys from the old default location (/config/context/global)
# to the new explicit location (/share/.librecoach/context/global), which survives
# add-on reinstalls. Carries forward ALL persisted keys (fill-if-absent, never
# overwrites) except those redesigned or reset in 2.0 (see EXCLUDE). Copying all
# keys — rather than a hand-maintained whitelist — preserves dynamic per-instance
# keys (e.g. dimmerBrightness_*, indicatorState_*) and any future keys.
# Skipped on developer environments, which manage their own context configuration.
if [ -f "/share/.librecoach-dev" ]; then
    echo "LibreCoach: Developer environment detected (/share/.librecoach-dev) — skipping context migration"
else
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

echo "LibreCoach Node-RED initialization complete"
