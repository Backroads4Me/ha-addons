#!/usr/bin/with-contenv bashio

run_orchestrator() {
	set -e

	bashio::log.info "================================================"
	bashio::log.info "🚐 LibreCoach - System Starting"
	bashio::log.info "================================================"

	# ========================
	# Configuration
	# ========================
	SUPERVISOR="http://supervisor"
	AUTH_HEADER="Authorization: Bearer $SUPERVISOR_TOKEN"
	PROJECT_PATH="/share/.librecoach"
	BUNDLED_PROJECT="/opt/librecoach-project"

	# Add-on Slugs
	SLUG_MOSQUITTO="core_mosquitto"
	SLUG_NODERED="a0d7b954_nodered"

	# State file to track LibreCoach management
	STATE_FILE="/data/.librecoach-state.json"
	ADDON_VERSION=$(bashio::addon.version)

	# Wait for /data/options.json to exist before reading config.
	# The Supervisor writes this before container start, so this should never wait —
	# but guards against edge cases on very first boot or slow Supervisor initialization.
	_opts_wait=0
	while [ ! -f /data/options.json ]; do
		if [ $_opts_wait -ge 10 ]; then
			bashio::log.warning "   ⚠️  /data/options.json not found after 10s — config may use defaults"
			break
		fi
		bashio::log.info "   Waiting for /data/options.json..."
		sleep 1
		_opts_wait=$((_opts_wait + 1))
	done

	# Config values used by orchestrator (from config.yaml)
	MQTT_USER=$(bashio::config 'mqtt_user')
	MQTT_PASS=$(bashio::config 'mqtt_pass')
	DEBUG_LOGGING=$(bashio::config 'debug_logging')
	VICTRON_ENABLED=$(bashio::config 'victron_enabled')
	# Beta features are currently disabled and intentionally have no UI option.
	# Keep publishing false to clear any retained true value from older installs.
	BETA_ENABLED=false
	MICROAIR_ENABLED=$(bashio::config 'microair_enabled')
	HUGHES_ENABLED=$(bashio::config 'hughes_enabled')
	GEO_ENABLED=$(bashio::config 'geo_enabled')
	RVC_TIME_SYNC_ENABLED=$(bashio::config 'rvc_time_sync_enabled')

	# The Supervisor option store is the source for several option updates below;
	# corrupt JSON here must abort rather than push garbage back to the Supervisor.
	if [ -f /data/options.json ] && ! jq -e . /data/options.json >/dev/null 2>&1; then
		bashio::log.fatal "❌ /data/options.json contains invalid JSON. Aborting startup."
		exit 1
	fi

	# MQTT credentials are embedded in Mosquitto options, flows_cred.json, and
	# settings.js. Newlines cannot be represented safely in all of those targets.
	case "$MQTT_USER$MQTT_PASS" in
	*$'\n'* | *$'\r'*)
		bashio::log.fatal "❌ MQTT username/password must not contain newline characters."
		bashio::log.fatal "   Fix the credentials in the LibreCoach Configuration tab and restart."
		exit 1
		;;
	esac

	# ========================
	# Orchestrator Helpers
	# ========================
	log_debug() {
		if [ "$DEBUG_LOGGING" = "true" ]; then
			# Log to stderr to avoid polluting stdout (which is captured by $())
			echo "[DEBUG] $1" >&2
		fi
	}

	# Run a command that must succeed. On failure, log a clear fatal message and
	# abort startup so we never continue with partial deployment state.
	run_required() {
		local msg=$1
		shift
		if ! "$@"; then
			bashio::log.fatal "❌ $msg"
			bashio::log.fatal "   Command: $*"
			exit 1
		fi
	}

	api_call() {
		local method=$1
		local endpoint=$2
		local data=${3:-}

		log_debug "API Call: $method $endpoint"
		if [ -n "$data" ]; then
			log_debug "API Data: $data"
			local response=$(curl -s --connect-timeout 5 -m 30 -X "$method" -H "$AUTH_HEADER" -H "Content-Type: application/json" -d "$data" "$SUPERVISOR$endpoint")
		else
			local response=$(curl -s --connect-timeout 5 -m 30 -X "$method" -H "$AUTH_HEADER" "$SUPERVISOR$endpoint")
		fi

		echo "$response"
	}

	check_mqtt_integration() {
		bashio::log.info "   Checking for MQTT integration..."

		# Wait up to 10 minutes for HA Core to fully boot (120 retries * 5s)
		# HA Core can take several minutes to start on standard hardware after a host reboot.
		local retries=120
		local logged_wait=false

		while [ $retries -gt 0 ]; do
			local response
			response=$(api_call GET "/core/api/components")

			if [ -n "$response" ] && ! echo "$response" | grep -q -E "502|Bad Gateway|Gateway|Error" >/dev/null 2>&1; then
				# Only valid JSON array expected here. If it's valid JSON and contains "mqtt", we're good.
				if echo "$response" | jq -e 'if type == "array" then index("mqtt") else false end' >/dev/null 2>&1; then
					if [ "$logged_wait" = "true" ]; then
						bashio::log.info "   MQTT integration found"
					fi
					return 0
				fi
			fi

			if [ "$logged_wait" = "false" ]; then
				bashio::log.info "   Home Assistant is still starting. Waiting for MQTT component..."
				logged_wait=true
			fi

			sleep 5
			((retries--))
		done

		bashio::log.warning "   ⚠️  Timed out waiting for Home Assistant to start"
		return 1
	}

	send_notification() {
		local title=$1
		local message=$2
		local notification_id=${3:-"librecoach_notification"}

		local payload
		payload=$(jq -n \
			--arg title "$title" \
			--arg message "$message" \
			--arg id "$notification_id" \
			'{"title": $title, "message": $message, "notification_id": $id}')

		api_call POST "/core/api/services/persistent_notification/create" "$payload" >/dev/null 2>&1
	}

	dismiss_notification() {
		local notification_id=$1
		api_call POST "/core/api/services/persistent_notification/dismiss" \
			"{\"notification_id\": \"$notification_id\"}" >/dev/null 2>&1
	}

	is_installed() {
		local slug=$1
		local response
		response=$(api_call GET "/addons/$slug/info")

		if [ -z "$response" ]; then
			log_debug "Empty response for $slug"
			return 1
		fi

		if ! echo "$response" | jq -e '.result == "ok"' >/dev/null 2>&1; then
			log_debug "API call failed for $slug"
			return 1
		fi

		# Check version field — present means installed
		local version
		version=$(echo "$response" | jq -r '.data.version // empty')
		if [ -n "$version" ]; then
			log_debug "$slug is installed (version $version)"
			return 0
		fi

		log_debug "$slug is not installed"
		return 1
	}

	is_running() {
		local slug=$1
		local state
		state=$(api_call GET "/addons/$slug/info" | jq -r '.data.state // "unknown"')
		[ "$state" == "started" ]
	}

	install_addon() {
		local slug=$1
		bashio::log.info "   Installing $slug"
		local result
		result=$(api_call POST "/store/addons/$slug/install")
		if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
			bashio::log.info "   Installed $slug"
		else
			local error_msg=$(echo "$result" | jq -r '.message')
			bashio::log.error "   ❌ Failed to install $slug: $error_msg"

			# Special handling for Node-RED already installed
			if [[ "$slug" == "$SLUG_NODERED" ]] && [[ "$error_msg" == *"already installed"* ]]; then
				bashio::log.error ""
				bashio::log.error "   Node-RED is already installed on your system."
				bashio::log.error "   To use it with LibreCoach, you must grant permission:"
				bashio::log.error ""
				bashio::log.error "   1. Go to the LibreCoach add-on Configuration tab"
				bashio::log.error "   2. Enable the 'Allow Node-RED Overwrite' option"
				bashio::log.error "   3. Scroll down and click 'Save'"
				bashio::log.error ""
				bashio::log.error "   ⚠️  WARNING: This will replace your existing Node-RED flows with LibreCoach flows."
			fi

			return 1
		fi
	}

	start_addon() {
		local slug=$1
		bashio::log.info "   Starting $slug"
		local result
		result=$(api_call POST "/addons/$slug/start")

		if ! echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
			bashio::log.error "   ❌ Failed to start $slug. API Response: $(echo "$result" | jq -r '.message // "Unknown error"')"
			return 1
		fi

		local retries=30
		while [ $retries -gt 0 ]; do
			if is_running "$slug"; then
				bashio::log.info "   $slug is running"
				return 0
			fi
			sleep 2
			((retries--))
		done
		bashio::log.warning "   ⚠️  $slug started but state is not 'started' yet"
		return 1
	}

	set_options() {
		local slug=$1
		local json=$2
		bashio::log.info "   Configuring $slug"
		log_debug "Configuration JSON: $json"
		local result
		result=$(api_call POST "/addons/$slug/options" "{\"options\": $json}")
		if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
			bashio::log.info "   Configured $slug"
		else
			bashio::log.error "   ❌ Failed to configure $slug: $(echo "$result" | jq -r '.message')"
			return 1
		fi
	}

	restart_addon() {
		local slug=$1
		#bashio::log.info "   Restarting $slug"
		local result
		result=$(api_call POST "/addons/$slug/restart")

		if ! echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
			bashio::log.error "   ❌ Failed to restart $slug. API Response: $(echo "$result" | jq -r '.message // "Unknown error"')"
			return 1
		fi

		local retries=30
		while [ $retries -gt 0 ]; do
			if is_running "$slug"; then
				bashio::log.info "   $slug is running"
				return 0
			fi
			sleep 2
			((retries--))
		done
		bashio::log.error "   ❌ $slug failed to restart in time"
		return 1
	}

	set_boot_auto() {
		local slug=$1
		local result
		result=$(api_call POST "/addons/$slug/options" '{"boot":"auto","watchdog":true}')
		if echo "$result" | jq -e '.result == "ok"' >/dev/null 2>&1; then
			bashio::log.info "   $slug will start on boot with watchdog enabled"
		else
			bashio::log.warning "   ⚠️  Failed to set boot option for $slug: $(echo "$result" | jq -r '.message')"
			return 1
		fi
	}

	wait_for_mqtt() {
		local host=$1
		local port=$2
		local user=$3
		local pass=$4

		bashio::log.info "   Waiting for MQTT broker at $host:$port"

		# Array (not a string) so usernames/passwords containing spaces or shell
		# metacharacters survive word splitting intact.
		local auth_args=()
		[ -n "$user" ] && auth_args+=(-u "$user")
		[ -n "$pass" ] && auth_args+=(-P "$pass")

		local retries=30
		while [ $retries -gt 0 ]; do
			if timeout 2 mosquitto_pub -h "$host" -p "$port" "${auth_args[@]}" -t "librecoach/test" -m "test" -q 0 2>/dev/null; then
				bashio::log.info "   MQTT broker is ready"
				return 0
			fi
			sleep 2
			((retries--))
		done

		bashio::log.error "   ❌ MQTT broker not responding"
		return 1
	}

	wait_for_nodered_api() {
		bashio::log.info "   Waiting for Node-RED API to be ready"

		local host="a0d7b954-nodered"
		local port=1880
		local retries=60
		local url="http://${host}:${port}/"

		while [ $retries -gt 0 ]; do
			log_debug "Checking for Node-RED API at $url"
			# A 401 error will still return 0 here, which is what we want.
			if curl -sS -m 3 "$url" >/dev/null 2>&1; then
				bashio::log.info "   Node-RED is ready"
				return 0
			fi
			sleep 3
			((retries--))
		done

		bashio::log.error "   ❌ Node-RED timeout: HTTP port never opened at $url"
		return 1
	}

	# ========================
	# State Management
	# ========================
	is_nodered_managed() {
		if [ ! -f "$STATE_FILE" ]; then
			return 1
		fi

		local managed=$(jq -r '.nodered_managed // false' "$STATE_FILE")
		[ "$managed" = "true" ]
	}

	mark_nodered_managed() {
		local current_hash=$1
		[ -z "$current_hash" ] && current_hash=$(get_flows_hash)

		mkdir -p /data
		cat >"$STATE_FILE" <<EOF
{
  "nodered_managed": true,
  "version": "$ADDON_VERSION",
  "flows_hash": "$current_hash",
  "prevent_flow_updates": $PREVENT_FLOW_UPDATES,
  "last_update": "$(date -Iseconds)"
}
EOF
		bashio::log.info "   Marked Node-RED as managed by LibreCoach"
	}

	get_managed_version() {
		if [ ! -f "$STATE_FILE" ]; then
			echo ""
			return
		fi
		jq -r '.version // ""' "$STATE_FILE"
	}

	get_flows_hash() {
		if [ -f "$BUNDLED_PROJECT/artifact/flows.json" ]; then
			md5sum "$BUNDLED_PROJECT/artifact/flows.json" | cut -d' ' -f1
		else
			echo "unknown"
		fi
	}

	get_managed_hash() {
		if [ ! -f "$STATE_FILE" ]; then
			echo ""
			return
		fi
		jq -r '.flows_hash // ""' "$STATE_FILE"
	}

	get_managed_preserve_mode() {
		if [ ! -f "$STATE_FILE" ]; then
			echo ""
			return
		fi
		jq -r '.prevent_flow_updates // ""' "$STATE_FILE"
	}

	# Ensure this addon starts on boot.
	# The self-watchdog is intentionally NOT enabled here — if setup fails or pauses
	# (e.g., waiting for the MQTT integration), an enabled watchdog turns that into a
	# Supervisor restart crash loop. It is enabled at the end of a successful setup.
	api_call POST "/addons/self/options" '{"boot":"auto"}' >/dev/null

	# Clean stale config keys left in the Supervisor's internal option store from previous releases.
	# The Supervisor generates /data/options.json for the addon (stripping unknown keys), but keeps
	# stale keys in its own store and warns about them at every boot. The only way to remove them
	# is to overwrite the Supervisor's store via its API with a full replacement of the options.
	# POST /addons/self/options with {"options": {...}} does a full replace — any keys not included
	# are dropped from the store. Reading the current valid options from /data/options.json and
	# posting them back effectively purges the stale keys.
	# Intentionally non-fatal: stale-key cleanup is cosmetic; a flaky Supervisor
	# response here must not abort startup.
	SELF_OPTIONS=$(api_call GET "/addons/self/info" | jq -r '.data.options // empty' 2>/dev/null || true)
	STALE_KEYS='["ble_scan_interval","mqtt_host","mqtt_port","mqtt_topic_raw","mqtt_topic_send","mqtt_topic_status"]'
	if [ -n "$SELF_OPTIONS" ]; then
		HAS_STALE=$(echo "$SELF_OPTIONS" | jq --argjson keys "$STALE_KEYS" '[.[$keys[]]] | map(select(. != null)) | length' 2>/dev/null || echo 0)
		if [ "$HAS_STALE" -gt 0 ] 2>/dev/null; then
			# Use /data/options.json as the POST source — it's the authoritative merged file generated
			# at startup and already strips unknown schema keys. Using the API response risks posting
			# schema defaults back, silently overwriting user-set values like prevent_flow_updates.
			CLEANED=$(cat /data/options.json)
			RESULT=$(api_call POST "/addons/self/options" "$(jq -n --argjson opts "$CLEANED" '{"options":$opts}')")
			if echo "$RESULT" | jq -e '.result == "ok"' >/dev/null 2>&1; then
				bashio::log.info "   Cleaned $HAS_STALE stale config keys from Supervisor store"
			else
				bashio::log.warning "   Failed to clean stale config keys: $RESULT"
			fi
		fi
	fi

	# ========================
	# Deployment
	# ========================
	bashio::log.info "Deploying Files"

	# A missing or incomplete bundled project means a broken image — abort with a
	# clear message instead of deploying a partial tree.
	if [ ! -d "$BUNDLED_PROJECT" ] || [ ! -f "$BUNDLED_PROJECT/artifact/flows.json" ]; then
		bashio::log.fatal "❌ Bundled Node-RED project is missing or incomplete at $BUNDLED_PROJECT"
		bashio::log.fatal "   This add-on image is corrupt. Reinstall or update LibreCoach."
		exit 1
	fi

	# Ensure directory exists
	mkdir -p "$PROJECT_PATH"

	# One-time migration: older releases stored the Node-RED credential_secret
	# backup inside $PROJECT_PATH, where `rsync --delete` destroyed it on every
	# start. Move it to add-on private storage before the rsync below.
	if [ -f "$PROJECT_PATH/.backup_credential_secret" ] && [ ! -f /data/.backup_credential_secret ]; then
		bashio::log.info "   Migrating credential_secret backup to /data/.backup_credential_secret"
		cp "$PROJECT_PATH/.backup_credential_secret" /data/.backup_credential_secret
		chmod 600 /data/.backup_credential_secret
	fi

	# Always deploy/update project files from bundled version
	if [ "$(ls -A $PROJECT_PATH)" ]; then
		bashio::log.info "   Updating project files from bundled version"
	else
		bashio::log.info "   Deploying bundled project to $PROJECT_PATH"
	fi

	# Deploy project files. The --exclude keeps any legacy credential_secret backup
	# alive at the old path during the migration transition.
	# Note: the developer-environment sentinel deliberately lives OUTSIDE this
	# directory (at /share/.librecoach-dev) so that rsync --delete can never remove
	# it, regardless of excludes.
	run_required "Failed to deploy bundled Node-RED project to $PROJECT_PATH" \
		rsync -a --delete --exclude=.backup_credential_secret "$BUNDLED_PROJECT/" "$PROJECT_PATH/"

	# Select the appropriate init script based on configuration
	PREVENT_FLOW_UPDATES=$(bashio::config 'prevent_flow_updates')
	bashio::log.info "   Preserve flow updates: $PREVENT_FLOW_UPDATES"

	if [ "$PREVENT_FLOW_UPDATES" = "true" ]; then
		bashio::log.info "   ✅ Flow updates PREVENTED. Using preserve-mode init script."
		cp "$PROJECT_PATH/init-nodered-preserve.sh" "$PROJECT_PATH/init-nodered.sh"
	else
		bashio::log.info "   Flow updates allowed. Using standard init script."
		cp "$PROJECT_PATH/init-nodered-overwrite.sh" "$PROJECT_PATH/init-nodered.sh"
	fi

	# Inject the addon slug for the suicide check
	OWNER_SLUG=$(api_call GET "/addons/self/info" | jq -r '.data.slug // empty')
	sed -i "s/REPLACE_ME/$OWNER_SLUG/g" "$PROJECT_PATH/init-nodered.sh"

	# Inject MQTT credentials into settings.js (if it contains placeholders).
	# Uses literal string replacement in Python, not sed — credentials containing
	# |, &, \, quotes, $, or spaces must not corrupt the file. Quoted placeholders
	# are replaced with a JSON-encoded string so the result is always valid JS.
	# Newlines in credentials were already rejected at startup.
	_SETTINGS_JS="$PROJECT_PATH/data/settings.js"
	if [ -f "$_SETTINGS_JS" ] && grep -q "REPLACE_MQTT_" "$_SETTINGS_JS"; then
		if LC_MQTT_USER="$MQTT_USER" LC_MQTT_PASS="$MQTT_PASS" \
			python3 - "$_SETTINGS_JS" <<'PYEOF'; then
import json, os, sys

path = sys.argv[1]
user = os.environ["LC_MQTT_USER"]
password = os.environ["LC_MQTT_PASS"]

with open(path, encoding="utf-8") as f:
    text = f.read()

# Quoted placeholders become JSON-encoded strings (valid JS string literals);
# bare placeholders get the raw value.
for quoted, bare, value in (
    ('"REPLACE_MQTT_USER"', "REPLACE_MQTT_USER", user),
    ('"REPLACE_MQTT_PASS"', "REPLACE_MQTT_PASS", password),
):
    text = text.replace(quoted, json.dumps(value)).replace(bare, value)

tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(text)
os.replace(tmp, path)
PYEOF
			bashio::log.info "   MQTT credentials injected into settings.js"
		else
			bashio::log.fatal "❌ Failed to inject MQTT credentials into settings.js"
			exit 1
		fi
	fi
	unset _SETTINGS_JS

	# Inject actual MQTT credentials into flows_cred.json.
	# The bundled file uses ${MQTT_USER}/${MQTT_PASS} placeholders which require Node-RED
	# env-var resolution at runtime — this step is fragile if credentialSecret doesn't
	# match. Instead, decrypt the file here, substitute real values, and re-encrypt so
	# Node-RED receives the credentials directly without any env-var dependency.
	# Every step is explicitly checked: a failed decrypt, substitute, or re-encrypt
	# aborts startup with a clear message. The original file is only replaced after
	# the new ciphertext is fully written (temp file + atomic move), so a forced
	# openssl failure can never leave a corrupted flows_cred.json behind.
	_FLOWS_CRED="$PROJECT_PATH/flows_cred.json"
	if [ -f "$_FLOWS_CRED" ] && command -v openssl >/dev/null 2>&1; then
		_enc=$(jq -r '."$" // empty' "$_FLOWS_CRED" 2>/dev/null || true)
		if [ -z "$_enc" ]; then
			# Intentionally non-fatal: a flows_cred.json without an encrypted "$"
			# field simply has nothing to inject.
			bashio::log.warning "   ⚠️  flows_cred.json has no encrypted payload — skipping credential injection"
		else
			_key=$(echo -n "librecoach" | openssl dgst -sha256 | awk '{print $2}')
			_iv="${_enc:0:32}"
			_ct="${_enc:32}"
			if ! _plain=$(echo "$_ct" | base64 -d |
				openssl enc -d -aes-256-ctr -K "$_key" -iv "$_iv" -nosalt); then
				bashio::log.fatal "❌ Failed to decrypt flows_cred.json. Node-RED would start without working MQTT credentials."
				exit 1
			fi
			if ! _new=$(echo "$_plain" | python3 -c "
import sys,json
c=json.loads(sys.stdin.read()); u,p=sys.argv[1],sys.argv[2]
for v in c.values():
    if isinstance(v,dict):
        if v.get('user')=='\${MQTT_USER}': v['user']=u
        if v.get('password')=='\${MQTT_PASS}': v['password']=p
print(json.dumps(c))
" "$MQTT_USER" "$MQTT_PASS"); then
				bashio::log.fatal "❌ Failed to substitute MQTT credentials in flows_cred.json"
				exit 1
			fi
			_new_iv=$(openssl rand -hex 16)
			if ! _new_enc=$(echo -n "$_new" |
				openssl enc -aes-256-ctr -K "$_key" -iv "$_new_iv" -nosalt |
				base64 -w 0) || [ -z "$_new_enc" ]; then
				bashio::log.fatal "❌ Failed to re-encrypt flows_cred.json"
				exit 1
			fi
			printf '{\n    "$": "%s%s"\n}\n' "$_new_iv" "$_new_enc" >"${_FLOWS_CRED}.tmp"
			mv "${_FLOWS_CRED}.tmp" "$_FLOWS_CRED"
			bashio::log.info "   MQTT credentials injected into flows_cred.json"
		fi
	fi
	unset _FLOWS_CRED _enc _key _iv _ct _plain _new _new_iv _new_enc

	# Ensure permissions are open (Node-RED runs as non-root)
	chmod -R 755 "$PROJECT_PATH"
	bashio::log.info "   Project files deployed"

	# ========================
	# Mosquitto MQTT Broker
	# ========================
	bashio::log.info "Mosquitto MQTT Broker"

	if is_installed "$SLUG_MOSQUITTO"; then
		# Mosquitto is installed, ensure it's running
		bashio::log.info "   Mosquitto is already installed"
		if ! is_running "$SLUG_MOSQUITTO"; then
			start_addon "$SLUG_MOSQUITTO" || exit 1
		fi
	else
		# Mosquitto is NOT installed. Install it.
		bashio::log.info "   Mosquitto not found. Installing"
		install_addon "$SLUG_MOSQUITTO" || exit 1
		start_addon "$SLUG_MOSQUITTO" || exit 1
	fi

	# Ensure Mosquitto starts on boot
	bashio::log.info "   Setting Mosquitto to start on boot with watchdog"
	set_boot_auto "$SLUG_MOSQUITTO" || bashio::log.warning "   ⚠️  Could not set Mosquitto to auto-start"

	# Ensure librecoach MQTT user exists in Mosquitto
	bashio::log.info "   Ensuring '$MQTT_USER' user exists in Mosquitto"
	MQTT_HOST="core-mosquitto"
	MQTT_PORT=1883

	MOSQUITTO_OPTIONS=$(api_call GET "/addons/$SLUG_MOSQUITTO/info" | jq '.data.options')
	NEW_MOSQUITTO_OPTIONS=$(echo "$MOSQUITTO_OPTIONS" | jq --arg user "$MQTT_USER" --arg pass "$MQTT_PASS" '
    .logins = (.logins // []) |
    .logins |= (map(select(.username != $user)) + [{"username": $user, "password": $pass}])
')

	if [ -z "$NEW_MOSQUITTO_OPTIONS" ] || [ "$NEW_MOSQUITTO_OPTIONS" == "null" ]; then
		bashio::log.error "   ❌ Failed to generate Mosquitto configuration"
		exit 1
	fi

	# Only update config and restart if the librecoach user/password changed
	if [ "$NEW_MOSQUITTO_OPTIONS" != "$MOSQUITTO_OPTIONS" ]; then
		api_call POST "/addons/$SLUG_MOSQUITTO/options" "{\"options\": $NEW_MOSQUITTO_OPTIONS}" >/dev/null
		bashio::log.info "   Configured Mosquitto user: $MQTT_USER"
		if is_running "$SLUG_MOSQUITTO"; then
			bashio::log.info "   Restarting Mosquitto to apply new configuration"
			restart_addon "$SLUG_MOSQUITTO" || exit 1
		fi
	else
		bashio::log.info "   Mosquitto user already configured"
		# Ensure Mosquitto is running (may not be after a reboot)
		if ! is_running "$SLUG_MOSQUITTO"; then
			start_addon "$SLUG_MOSQUITTO" || exit 1
		else
			bashio::log.info "   $SLUG_MOSQUITTO is running"
		fi
	fi

	# Verify MQTT is responding with configured credentials
	wait_for_mqtt "$MQTT_HOST" "$MQTT_PORT" "$MQTT_USER" "$MQTT_PASS" || {
		bashio::log.fatal "❌ MQTT broker is not responding. Cannot continue."
		exit 1
	}
	bashio::log.info "   MQTT credentials verified"

	# Validate MQTT Integration
	bashio::log.info "   Validating MQTT integration..."

	if ! check_mqtt_integration; then
		# Send persistent notification to Home Assistant UI
		send_notification \
			"⚠️ LibreCoach: MQTT Integration Required" \
			"**LibreCoach installation is paused!**

✅ Mosquitto broker is installed and running
⚠️ But MQTT integration needs to be configured

**Quick Setup (30 seconds):**

1. Go to **Settings → Devices & Services**
2. Look for **MQTT** in the 'Discovered' section
3. Click **ADD** on the MQTT card
4. Click **SUBMIT** to use Mosquitto broker
5. Return to **Settings → Add-ons → LibreCoach** and click **RESTART**

**Why?** The MQTT integration listens for device discovery messages and creates entities automatically.

_See LibreCoach addon logs for more details_" \
			"librecoach_mqtt_setup"

		# Also log to addon logs
		bashio::log.error ""
		bashio::log.error "╔════════════════════════════════════════════════════════════╗"
		bashio::log.error "║   ⚠️  MQTT INTEGRATION REQUIRED  ⚠️                        ║"
		bashio::log.error "╚════════════════════════════════════════════════════════════╝"
		bashio::log.error ""
		bashio::log.error "   ✅ Mosquitto broker is installed and running"
		bashio::log.error "   ⚠️  But MQTT integration needs to be configured"
		bashio::log.error ""
		bashio::log.error "   Quick Setup (takes 30 seconds):"
		bashio::log.error ""
		bashio::log.error "   1. Go to Settings → Devices & Services"
		bashio::log.error "   2. Look for MQTT in the 'Discovered' section"
		bashio::log.error "   3. Click ADD on the MQTT card"
		bashio::log.error "   4. Click SUBMIT to use Mosquitto broker"
		bashio::log.error "   5. Return to Settings → Add-ons → LibreCoach and click RESTART"
		bashio::log.error ""
		bashio::log.error "   Check the notification in Home Assistant UI (🔔 bell icon)"
		bashio::log.error ""
		bashio::log.warning "   ⏳ Waiting for MQTT integration. Setup resumes automatically once it is configured."
		bashio::log.warning ""

		# Keep the process alive and poll instead of exiting — exiting here used to
		# trigger a Supervisor watchdog restart crash loop. The self-watchdog is not
		# enabled until setup completes, but staying alive also lets setup resume
		# without user intervention the moment the integration appears.
		_mqtt_wait_minutes=0
		while true; do
			sleep 60
			if api_call GET "/core/api/components" | jq -e 'if type == "array" then index("mqtt") else false end' >/dev/null 2>&1; then
				bashio::log.info "   MQTT integration detected. Resuming setup."
				break
			fi
			_mqtt_wait_minutes=$((_mqtt_wait_minutes + 1))
			if [ $((_mqtt_wait_minutes % 10)) -eq 0 ]; then
				bashio::log.warning "   ⏳ Still waiting for MQTT integration (${_mqtt_wait_minutes} minutes). See setup steps above."
			fi
		done
	fi

	# MQTT is configured - dismiss any previous setup notifications
	dismiss_notification "librecoach_mqtt_setup"
	bashio::log.info "   MQTT integration is configured"

	# Legacy cleanup: disable old CAN-MQTT Bridge add-on if present
	SLUG_CAN_BRIDGE="3b081c96_can-mqtt-bridge"
	if is_installed "$SLUG_CAN_BRIDGE"; then
		bashio::log.info "Migrating from standalone CAN-MQTT Bridge"
		# Intentionally non-fatal: legacy bridge may already be stopped.
		if is_running "$SLUG_CAN_BRIDGE"; then
			api_call POST "/addons/$SLUG_CAN_BRIDGE/stop" "" >/dev/null 2>&1
		fi
		api_call POST "/addons/$SLUG_CAN_BRIDGE/options" '{"boot":"manual","watchdog":false}' >/dev/null 2>&1
		bashio::log.info "CAN-MQTT Bridge disabled. The vehicle_bridge now handles CAN."
		bashio::log.info "You may uninstall can-mqtt-bridge from Settings → Add-ons."
	fi

	# Publish config toggles as retained MQTT messages for Node-RED
	# Auth flags built as an array so credentials with spaces/metacharacters work,
	# and so no-auth mode (empty user/pass) cleanly omits -u/-P.
	mqtt_auth_args() {
		MQTT_AUTH_ARGS=()
		[ -n "${MQTT_USER:-}" ] && MQTT_AUTH_ARGS+=(-u "$MQTT_USER")
		[ -n "${MQTT_PASS:-}" ] && MQTT_AUTH_ARGS+=(-P "$MQTT_PASS")
	}

	mqtt_pub() {
		mqtt_auth_args
		mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" "${MQTT_AUTH_ARGS[@]}" -r -q 1 "$@"
	}

	# Publish a retained config toggle; failures are fatal because Node-RED flows
	# depend on these retained topics to configure themselves.
	publish_config_toggle() {
		run_required "Failed to publish retained config topic $1" mqtt_pub -t "$1" -m "$2"
	}
	publish_config_toggle "librecoach/config/victron_enabled" "$VICTRON_ENABLED"
	publish_config_toggle "librecoach/config/beta_enabled" "$BETA_ENABLED"
	publish_config_toggle "librecoach/config/microair_enabled" "$MICROAIR_ENABLED"
	publish_config_toggle "librecoach/config/hughes_enabled" "$HUGHES_ENABLED"
	publish_config_toggle "librecoach/config/geo_enabled" "$GEO_ENABLED"
	publish_config_toggle "librecoach/config/rvc_time_sync_enabled" "$RVC_TIME_SYNC_ENABLED"
	bashio::log.info "   Published config toggles to MQTT"

	# ========================
	# LibreCoach BLE Integration
	# ========================

	bashio::log.info "Bluetooth Integration"

	INTEGRATION_SRC="/opt/librecoach_ble"
	INTEGRATION_DST="/config/custom_components/librecoach_ble"

	# Write config file for the integration to read at runtime.
	# Always written regardless of toggle — the integration handles enable/disable dynamically via MQTT.
	MICROAIR_PASSWORD=$(bashio::config 'microair_password')
	MICROAIR_EMAIL=$(bashio::config 'microair_email')

	if ! jq -n \
		--argjson enabled "$MICROAIR_ENABLED" \
		--argjson hughes_enabled "$HUGHES_ENABLED" \
		--arg password "$MICROAIR_PASSWORD" \
		--arg email "$MICROAIR_EMAIL" \
		--arg slug "$OWNER_SLUG" \
		'{
        microair_enabled: $enabled,
        hughes_enabled: $hughes_enabled,
        microair_password: $password,
        microair_email: $email,
        addon_slug: $slug
    }' >/config/.librecoach-ble-config.json.tmp; then
		bashio::log.fatal "❌ Failed to generate BLE integration config (.librecoach-ble-config.json)"
		exit 1
	fi
	mv /config/.librecoach-ble-config.json.tmp /config/.librecoach-ble-config.json

	# Ensure the config file is excluded from git to protect credentials
	GITIGNORE="/config/.gitignore"
	GITIGNORE_ENTRY=".librecoach-ble-config.json"
	if [ ! -f "$GITIGNORE" ] || ! grep -qF "$GITIGNORE_ENTRY" "$GITIGNORE"; then
		echo "$GITIGNORE_ENTRY" >>"$GITIGNORE"
		bashio::log.info "   Added $GITIGNORE_ENTRY to /config/.gitignore"
	fi

	# Install/update integration files (only restart if code actually changed)
	NEEDS_HA_RESTART=false

	# Define a hash function that ignores HA runtime files (.translations) and OS hidden files
	get_integration_hash() {
		local dir=$1
		# Only hash explicit extension types and ignore all hidden paths or pycache
		(cd "$dir" && find . -type f \( -name "*.py" -o -name "*.json" -o -name "*.png" \) \
			-not -path "*/__pycache__/*" -not -path "*/.*" -exec md5sum {} + | sort -k 2 | md5sum | cut -d' ' -f1)
	}

	BUNDLED_HASH=$(get_integration_hash "$INTEGRATION_SRC")

	if [ -d "$INTEGRATION_DST" ]; then
		INSTALLED_HASH=$(get_integration_hash "$INTEGRATION_DST")

		if [ "$BUNDLED_HASH" != "$INSTALLED_HASH" ]; then
			bashio::log.info "   Updating librecoach_ble integration"
			log_debug "BLE hash mismatch (Bundled: $BUNDLED_HASH, Installed: $INSTALLED_HASH)"
			rm -rf "$INTEGRATION_DST"
			cp -r "$INTEGRATION_SRC" "$INTEGRATION_DST"
			NEEDS_HA_RESTART=true
		else
			bashio::log.info "   librecoach_ble is up to date"
			log_debug "BLE hashes match: $INSTALLED_HASH"
		fi
	else
		bashio::log.info "   Installing librecoach_ble integration"
		mkdir -p /config/custom_components
		cp -r "$INTEGRATION_SRC" "$INTEGRATION_DST"
		NEEDS_HA_RESTART=true
	fi

	# Add to configuration.yaml if not present
	if ! grep -q "librecoach_ble:" /config/configuration.yaml 2>/dev/null; then
		bashio::log.info "   Adding librecoach_ble to configuration.yaml"
		echo -e "\nlibrecoach_ble:" >>/config/configuration.yaml
		NEEDS_HA_RESTART=true
	fi

	if [ "$NEEDS_HA_RESTART" = "true" ]; then
		bashio::log.warning "   ⚠️  LibreCoach Bluetooth Integration state changed"
		bashio::log.warning "   ⚠️  Restarting Home Assistant Core to apply changes"
		bashio::log.warning "   ⚠️  It is normal to briefly lose connection to Home Assistant."
		bashio::log.warning "   ⚠️  Please wait a few minutes and refresh your browser if necessary."

		api_call POST "/core/restart" >/dev/null 2>&1

		# Wait for HA to come back (10s initial delay + up to ~2 min polling)
		bashio::log.info "   Waiting for Home Assistant to finish restarting"
		sleep 10
		retries=30
		while [ $retries -gt 0 ]; do
			if curl -s --connect-timeout 3 -m 5 -H "$AUTH_HEADER" "$SUPERVISOR/core/api/" 2>/dev/null | grep -q "API running"; then
				bashio::log.info "   Home Assistant is back online"
				break
			fi
			sleep 3
			((retries--))
		done

		if [ $retries -eq 0 ]; then
			bashio::log.warning "   ⚠️  HA restart taking longer than expected"
			bashio::log.warning "   BLE integration will load after HA finishes"
		fi
	fi

	bashio::log.info "   LibreCoach Bluetooth integration ready"

	# ========================
	# Node-RED
	# ========================
	bashio::log.info "Node-RED"

	CONFIRM_TAKEOVER=$(bashio::config 'confirm_nodered_takeover')
	NODERED_ALREADY_INSTALLED=false
	MIGRATION_DETECTED=false

	if is_installed "$SLUG_NODERED"; then
		bashio::log.info "   Node-RED is already installed."
		NODERED_ALREADY_INSTALLED=true
	else
		# Try to install Node-RED
		bashio::log.info "   Node-RED not found. Installing"
		if ! install_addon "$SLUG_NODERED"; then
			# Installation failed - check if it's because it's already installed
			nr_check=$(api_call GET "/addons/$SLUG_NODERED/info")
			# Check if addon is actually installed (by checking for version field)
			nr_version=$(echo "$nr_check" | jq -r '.data.version // empty')
			if [ -n "$nr_version" ]; then
				bashio::log.info "   Node-RED was already installed (detection issue)"
				NODERED_ALREADY_INSTALLED=true
			else
				# Different error, exit
				exit 1
			fi
		fi
	fi

	# If Node-RED was already installed, check if we need takeover permission
	# Skip takeover check if already managed by LibreCoach
	if [ "$NODERED_ALREADY_INSTALLED" = "true" ]; then
		# Migration: if state file doesn't exist but Node-RED's init_commands already
		# point to LibreCoach, a previous version was managing it. Auto-create state file
		# so upgrades don't re-prompt for takeover permission.
		if ! is_nodered_managed; then
			nr_init_check=$(api_call GET "/addons/$SLUG_NODERED/info" | jq -r '.data.options.init_commands[0] // empty')
			if [[ "$nr_init_check" == *"librecoach"* ]]; then
				bashio::log.info "   Migrating: previous LibreCoach version detected (init_commands present). Creating state file."
				mark_nodered_managed "$(get_flows_hash)"
				MIGRATION_DETECTED=true
			fi
		fi

		if is_nodered_managed; then
			MANAGED_VERSION=$(get_managed_version)
			bashio::log.info "   Node-RED already managed by LibreCoach (version $MANAGED_VERSION)"
		else
			# Node-RED exists but not managed by LibreCoach - need permission
			if [ "$PREVENT_FLOW_UPDATES" = "true" ]; then
				bashio::log.info "   ✅ Flow update prevention enabled - implicitly allowing Node-RED management."
			elif [ "$CONFIRM_TAKEOVER" != "true" ]; then
				bashio::log.warning ""
				bashio::log.warning "   ⚠️  EXISTING INSTALLATION DETECTED"
				bashio::log.warning "   LibreCoach needs to configure Node-RED to run the LibreCoach project."
				bashio::log.warning "   This will REPLACE your active Node-RED flows."
				bashio::log.warning "   "
				bashio::log.warning "   To proceed, you must explicitly grant permission:"
				bashio::log.warning "   1. Go to the LibreCoach add-on configuration tab."
				bashio::log.warning "   2. Enable 'Allow Node-RED Overwrite'."
				bashio::log.warning "   3. Scroll down and click 'Save'."
				bashio::log.warning "   4. Restart the LibreCoach add-on."
				bashio::log.warning ""
				send_notification \
					"⚠️ LibreCoach: Node-RED Setup Required" \
					"**LibreCoach setup is paused — action required!**

An existing Node-RED installation was detected. LibreCoach needs to replace your Node-RED flows with the LibreCoach project flows.

**To proceed:**
1. Go to **Settings → Add-ons → LibreCoach**
2. Open the **Configuration** tab
3. Enable **Allow Node-RED Overwrite**
4. Click **Save**
5. **Restart** the LibreCoach add-on

⚠️ This will replace your existing Node-RED flows." \
					"librecoach_nodered_takeover"
				bashio::log.warning "   ⏸️  Setup paused. LibreCoach will not restart automatically."
				bashio::log.warning "   After granting permission and saving, restart the add-on."
				return 1
			else
				bashio::log.info "   ✅ Permission granted to take over Node-RED."
			fi
		fi
	fi

	# Save previous state before marking managed (needed for update detection later)
	PREVIOUS_VERSION=$(get_managed_version)
	PREVIOUS_FLOWS_HASH=$(get_managed_hash)
	PREVIOUS_PRESERVE_MODE=$(get_managed_preserve_mode)
	FLOWS_HASH=$(get_flows_hash)

	# Mark Node-RED as managed now, before configuration steps that may fail and trigger a watchdog
	# restart. Without this, a failed restart_addon call causes the next run to see Node-RED as
	# installed-but-unmanaged and incorrectly prompt for takeover permission.
	mark_nodered_managed "$FLOWS_HASH"

	# Configure Node-RED
	NR_INFO=$(api_call GET "/addons/$SLUG_NODERED/info")
	log_debug "Node-RED Info API called."
	NR_OPTIONS=$(echo "$NR_INFO" | jq '.data.options // {}')
	EXISTING_SECRET=$(echo "$NR_OPTIONS" | jq -r '.credential_secret // empty')
	log_debug "Existing credentials secret extracted."

	# Because Home Assistant add-ons cannot mount volumes during installation, LibreCoach
	# deploys its project files to `/share/.librecoach`. We then inject a bash script into
	# Node-RED's `init_commands` array. When Node-RED boots, it runs this script to copy
	# the project files from the `/share` drive into its own protected `/config` volume.
	SETTINGS_INIT_CMD="bash /share/.librecoach/init-nodered.sh"

	# LibreCoach requires credential_secret to be "librecoach" for flows_cred.json decryption
	LIBRECOACH_SECRET="librecoach"

	NEEDS_RESTART=false

	# Backup existing credential_secret if it exists and differs from ours.
	# Stored in add-on private /data (never touched by project rsync) and written
	# only once — the first backup is the user's original pre-LibreCoach secret
	# and must never be overwritten by later restarts.
	if [ -n "$EXISTING_SECRET" ] && [ "$EXISTING_SECRET" != "$LIBRECOACH_SECRET" ]; then
		BACKUP_FILE="/data/.backup_credential_secret"
		if [ -f "$BACKUP_FILE" ]; then
			bashio::log.info "   Node-RED credential_secret backup already exists at $BACKUP_FILE (keeping original)"
		else
			bashio::log.info "   Backing up existing Node-RED credential_secret to $BACKUP_FILE"
			echo "$EXISTING_SECRET" >"$BACKUP_FILE"
			chmod 600 "$BACKUP_FILE"
		fi
	fi

	if [ -z "$EXISTING_SECRET" ] || [ "$EXISTING_SECRET" != "$LIBRECOACH_SECRET" ]; then
		bashio::log.info "   Setting credential_secret to 'librecoach' for flows_cred.json compatibility"
		NEW_OPTIONS=$(echo "$NR_OPTIONS" | jq \
			--arg secret "$LIBRECOACH_SECRET" \
			--arg initcmd "$SETTINGS_INIT_CMD" \
			'. + {"credential_secret": $secret, "ssl": false, "init_commands": [$initcmd]} | del(.users)')
		set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
		NEEDS_RESTART=true
	else
		CURRENT_INIT_CMD=$(echo "$NR_OPTIONS" | jq -r '.init_commands[0] // empty')
		HAS_USERS=$(echo "$NR_OPTIONS" | jq -r 'if .users then "true" else "false" end')

		# Check if config needs updating (init command changed or users auth still present)
		if [ "$CURRENT_INIT_CMD" != "$SETTINGS_INIT_CMD" ] || [ "$HAS_USERS" = "true" ]; then
			if [ -z "$CURRENT_INIT_CMD" ]; then
				bashio::log.warning "   ⚠️  Node-RED init command is missing. Restoring."
			else
				bashio::log.info "   Updating Node-RED configuration (init commands)"
			fi
			NEW_OPTIONS=$(echo "$NR_OPTIONS" | jq \
				--arg initcmd "$SETTINGS_INIT_CMD" \
				'. + {"init_commands": [$initcmd]} | del(.users)')
			set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
			NEEDS_RESTART=true
		else
			bashio::log.info "   Node-RED configuration is up to date"
		fi
	fi

	# Check if flows need updating (requiring a restart to pick up)
	if [ "$PREVENT_FLOW_UPDATES" != "true" ] && [ "$NEEDS_RESTART" = "false" ]; then
		if [ -n "$PREVIOUS_VERSION" ] && [ "$PREVIOUS_VERSION" != "$ADDON_VERSION" ]; then
			# Version changed — always restart to ensure init script runs with latest bundled flows
			bashio::log.info "   Add-on version changed ($PREVIOUS_VERSION → $ADDON_VERSION). Restarting Node-RED."
			NEEDS_RESTART=true
		elif [ -n "$PREVIOUS_FLOWS_HASH" ] && [ "$PREVIOUS_FLOWS_HASH" != "$FLOWS_HASH" ]; then
			log_debug "Flow hash changed from $PREVIOUS_FLOWS_HASH to $FLOWS_HASH"
			NEEDS_RESTART=true
		fi
	fi

	# Detect preserve-mode transition: if preserve was previously enabled and is now disabled,
	# run the full Node-RED verification — ensure the init command is present, using the correct
	# (overwrite) init script, and restart Node-RED to replace preserved flows with bundled flows.
	if [ "$PREVIOUS_PRESERVE_MODE" = "true" ] && [ "$PREVENT_FLOW_UPDATES" != "true" ]; then
		bashio::log.info "   Flow preservation was disabled. Verifying Node-RED configuration."

		# Re-check init command — user may have removed it while in preserve mode
		CURRENT_INIT_CMD=$(api_call GET "/addons/$SLUG_NODERED/info" | jq -r '.data.options.init_commands[0] // empty')
		if [ "$CURRENT_INIT_CMD" != "$SETTINGS_INIT_CMD" ]; then
			bashio::log.warning "   ⚠️  Node-RED init command is missing. Restoring."
			# Re-read live options to avoid stale data from earlier set_options call
			NR_OPTIONS_LIVE=$(api_call GET "/addons/$SLUG_NODERED/info" | jq '.data.options // {}')
			NEW_OPTIONS=$(echo "$NR_OPTIONS_LIVE" | jq \
				--arg initcmd "$SETTINGS_INIT_CMD" \
				'. + {"init_commands": [$initcmd]} | del(.users)')
			set_options "$SLUG_NODERED" "$NEW_OPTIONS" || exit 1
		else
			bashio::log.info "   Node-RED init command verified"
		fi

		bashio::log.info "   Restarting Node-RED to restore standard flows."
		NEEDS_RESTART=true
	fi

	# Force restart on migration from a previous LibreCoach installation (e.g., beta → production).
	# The migration path creates the state file with the current hash, making the hash comparison
	# see no change. But Node-RED's flows may be stale, so we must restart to run the init script.
	# Skip forced restart if preserve mode is on — flows should not be replaced, and data files
	# are already deployed to /share/.librecoach via rsync above.
	if [ "$MIGRATION_DETECTED" = "true" ] && [ "$NEEDS_RESTART" = "false" ] && [ "$PREVENT_FLOW_UPDATES" != "true" ]; then
		bashio::log.info "   Migration detected — restarting Node-RED to deploy bundled flows."
		NEEDS_RESTART=true
	elif [ "$MIGRATION_DETECTED" = "true" ] && [ "$PREVENT_FLOW_UPDATES" = "true" ]; then
		bashio::log.info "   Migration detected — skipping Node-RED restart (preserve mode active)."
	fi

	# Ensure Node-RED starts/restarts to apply init commands
	if [ "$NEEDS_RESTART" = "true" ]; then
		if is_running "$SLUG_NODERED"; then
			bashio::log.info "   Restarting Node-RED to apply new configuration"
			restart_addon "$SLUG_NODERED" || exit 1
		else
			bashio::log.info "   Starting Node-RED with new configuration"
			start_addon "$SLUG_NODERED" || exit 1

			# Force a restart after fresh start to fix race condition:
			# On first boot, Node-RED's initialization may interfere with init_commands.
			# A restart ensures init_commands run cleanly on an initialized volume.
			bashio::log.info "   Performing initialization restart to ensure init_commands take effect"
			sleep 5
			restart_addon "$SLUG_NODERED" || exit 1
		fi
	else
		if ! is_running "$SLUG_NODERED"; then
			start_addon "$SLUG_NODERED" || exit 1
		fi
	fi

	# Wait for Node-RED to be available before proceeding.
	# Flows are loaded automatically by Node-RED on startup via init_commands — no API deploy needed.
	if wait_for_nodered_api; then
		# Re-publish config toggles now that Node-RED is online.
		# The initial publish (retained) may be missed if the broker cycled during startup.
		publish_config_toggle "librecoach/config/victron_enabled" "$VICTRON_ENABLED"
		publish_config_toggle "librecoach/config/beta_enabled" "$BETA_ENABLED"
		publish_config_toggle "librecoach/config/microair_enabled" "$MICROAIR_ENABLED"
		publish_config_toggle "librecoach/config/hughes_enabled" "$HUGHES_ENABLED"
		publish_config_toggle "librecoach/config/geo_enabled" "$GEO_ENABLED"
		publish_config_toggle "librecoach/config/rvc_time_sync_enabled" "$RVC_TIME_SYNC_ENABLED"
		bashio::log.info "   Re-published config toggles to MQTT"
	else
		bashio::log.warning "   ⚠️  Node-RED API did not respond. It may still be starting."
	fi

	# Ensure Node-RED starts on boot
	bashio::log.info "   Setting Node-RED to start on boot with watchdog"
	set_boot_auto "$SLUG_NODERED" || bashio::log.warning "   ⚠️  Could not set Node-RED to auto-start"

	# ========================
	# Installation Summary
	# ========================
	bashio::log.info ""
	bashio::log.info "     _     _ _                 ____                 _"
	bashio::log.info "    | |   (_) |__  _ __ ___  / ___|___   __ _  ___| |__"
	bashio::log.info "    | |   | | '_ \\| '__/ _ \\| |   / _ \\ / _\` |/ __| '_ \\\\"
	bashio::log.info "    | |___| | |_) | | |  __/| |__| (_) | (_| | (__| | | |"
	bashio::log.info "    |_____|_|_.__/|_|  \\___| \\____\\___/ \\__,_|\\___|_| |_|"
	bashio::log.info ""
	bashio::log.info "╔════════════════════════════════════════════════════════════╗"
	bashio::log.info "║           LibreCoach Installation Summary                  ║"
	bashio::log.info "╠════════════════════════════════════════════════════════════╣"
	bashio::log.info "║  MQTT Integration ................ Configured              ║"
	bashio::log.info "║  Mosquitto MQTT Broker ........... Running                 ║"
	bashio::log.info "║  Node-RED ........................ Running                 ║"
	bashio::log.info "║  RV-C Bridge ..................... Started                 ║"
	bashio::log.info "║  Bluetooth server ................ Started                 ║"
	bashio::log.info "╠════════════════════════════════════════════════════════════╣"
	bashio::log.info "║  All components installed successfully!                    ║"
	bashio::log.info "║  Visit https://LibreCoach.com for more information         ║"
	bashio::log.info "╚════════════════════════════════════════════════════════════╝"

	# Setup succeeded — only now is the self-watchdog safe to enable. Enabling it
	# earlier turns any setup failure or wait state into a restart crash loop.
	# Intentionally non-fatal: a failed watchdog update must not fail a good setup.
	api_call POST "/addons/self/options" '{"boot":"auto","watchdog":true}' >/dev/null 2>&1 ||
		bashio::log.warning "   ⚠️  Could not enable self-watchdog"

} # end run_orchestrator

# As a cont-init.d script, this runs once at startup before s6 services start.
# The vehicle_bridge Python process is managed by s6 as a longrun service.
#
# run_orchestrator must NOT be invoked inside an `if` condition — doing so
# disables `set -e` for its entire body, letting failures continue with
# partial deployment state. The EXIT trap logs the outcome either way and the
# script exits with the orchestrator's real exit code.
on_exit() {
	local rc=$?
	if [ $rc -eq 0 ]; then
		bashio::log.info "Orchestrator complete. Vehicle bridge starting via s6."
	else
		bashio::log.error "Orchestrator failed (exit code $rc). Startup aborted — see errors above."
		bashio::log.error "Fix the issue, then restart the addon from Settings → Add-ons → LibreCoach."
	fi
}

main() {
	run_orchestrator
}

trap on_exit EXIT
main
