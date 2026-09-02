#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RUN_SH="$SCRIPT_DIR/../run.sh"
TEST_TMP=$(mktemp -d)
trap 'rm -rf -- "$TEST_TMP"' EXIT

load_function() {
	local name=$1
	local definition
	definition=$(sed -n "/^\t${name}() {/,/^\t}/p" "$RUN_SH")
	if [ -z "$definition" ]; then
		echo "Function not found: $name" >&2
		exit 1
	fi
	eval "$definition"
}

assert_status() {
	local expected=$1
	shift
	local actual
	set +e
	"$@"
	actual=$?
	set -e
	if [ "$actual" -ne "$expected" ]; then
		echo "Expected status $expected, got $actual from: $*" >&2
		exit 1
	fi
}

load_function get_addon_install_state
load_function ensure_homeassistant_www
load_function classify_nodered_install_state
load_function mark_nodered_install_pending
load_function is_nodered_install_pending
load_function clear_nodered_install_pending
load_function mark_nodered_managed
load_function wait_for_install
load_function install_addon
load_function nodered_is_unconfigured

api_call() {
	printf '%s\n' "$MOCK_API_RESPONSE"
}

log_debug() {
	:
}

bashio::log.info() {
	:
}

bashio::log.error() {
	:
}

sleep() {
	:
}

redact_json() {
	printf '%s\n' "$1"
}

SLUG_NODERED="a0d7b954_nodered"
export DATA_DIR="$TEST_TMP"
NODERED_INSTALL_PENDING_FILE="$TEST_TMP/install-pending.json"
STATE_FILE="$TEST_TMP/state.json"
export ADDON_VERSION="test-version"
export PREVENT_FLOW_UPDATES=false

export HOMEASSISTANT_CONFIG_DIR="$TEST_TMP/homeassistant"
ensure_homeassistant_www
test "$HOMEASSISTANT_WWW_CREATED" = "true"
test -d "$HOMEASSISTANT_CONFIG_DIR/www"
ensure_homeassistant_www
test "$HOMEASSISTANT_WWW_CREATED" = "false"

MOCK_API_RESPONSE='{"result":"ok","data":{"installed":true}}'
assert_status 0 get_addon_install_state "$SLUG_NODERED"

MOCK_API_RESPONSE='{"result":"ok","data":{"installed":false}}'
assert_status 1 get_addon_install_state "$SLUG_NODERED"

MOCK_API_RESPONSE='{"result":"error","message":"Supervisor unavailable"}'
assert_status 2 get_addon_install_state "$SLUG_NODERED"

API_TIMEOUT_IMAGE_PULL=1800

MOCK_API_RESPONSE='{"result":"ok"}'
assert_status 0 install_addon "$SLUG_NODERED"

# A truncated response means the Supervisor is still pulling, not that it failed.
MOCK_API_RESPONSE=''
INSTALL_STATE_RESULTS=(1 1 0)
INSTALL_STATE_INDEX=0
get_addon_install_state() {
	local status=${INSTALL_STATE_RESULTS[$INSTALL_STATE_INDEX]}
	if [ $((INSTALL_STATE_INDEX + 1)) -lt ${#INSTALL_STATE_RESULTS[@]} ]; then
		((INSTALL_STATE_INDEX++))
	fi
	return "$status"
}
assert_status 0 install_addon "$SLUG_NODERED"

INSTALL_STATE_RESULTS=(1)
INSTALL_STATE_INDEX=0
assert_status 1 install_addon "$SLUG_NODERED"

MOCK_API_RESPONSE='{"result":"error","message":"Add-on is not available"}'
assert_status 1 install_addon "$SLUG_NODERED"

load_function get_addon_install_state

# A Node-RED the Supervisor installed but nothing ever configured.
assert_status 0 nodered_is_unconfigured \
	'{"data":{"state":"unknown","options":{"theme":"default","init_commands":[]}}}'
assert_status 0 nodered_is_unconfigured \
	'{"data":{"state":"stopped","options":{}}}'
# A Node-RED the user has set up, in each of the ways that shows.
assert_status 1 nodered_is_unconfigured \
	'{"data":{"state":"started","options":{"init_commands":[]}}}'
assert_status 1 nodered_is_unconfigured \
	'{"data":{"state":"stopped","options":{"credential_secret":"user-secret","init_commands":[]}}}'
assert_status 1 nodered_is_unconfigured \
	'{"data":{"state":"stopped","options":{"init_commands":["bash /config/setup.sh"]}}}'
assert_status 1 nodered_is_unconfigured \
	'{"data":{"state":"stopped","options":{"users":[{"username":"owner"}],"init_commands":[]}}}'

test "$(classify_nodered_install_state 0 true false)" = "managed"
test "$(classify_nodered_install_state 0 false true)" = "resume"
test "$(classify_nodered_install_state 0 false false)" = "preexisting"
test "$(classify_nodered_install_state 1 false true)" = "install"
test "$(classify_nodered_install_state 2 false false)" = "unknown"

mark_nodered_install_pending
assert_status 0 is_nodered_install_pending
jq -e --arg slug "$SLUG_NODERED" \
	'.owner == "librecoach" and .slug == $slug and .version == "test-version"' \
	"$NODERED_INSTALL_PENDING_FILE" >/dev/null

# The marker licenses adopting an installation without asking, so it is only
# honored while the install it describes is recent. An old, undated or
# unparsable marker reads as expired, which sends the installation down the
# pre-existing path where the owner is asked.
write_pending_marker() {
	jq -n --arg slug "$SLUG_NODERED" --arg started_at "$1" \
		'{owner: "librecoach", slug: $slug, version: "test-version"} +
		 (if $started_at == "" then {} else {started_at: $started_at} end)' \
		>"$NODERED_INSTALL_PENDING_FILE"
}

write_pending_marker "$(date -Iseconds -d '1 hour ago')"
assert_status 0 is_nodered_install_pending
write_pending_marker "$(date -Iseconds -d '25 hours ago')"
assert_status 1 is_nodered_install_pending
write_pending_marker ""
assert_status 1 is_nodered_install_pending
write_pending_marker "not-a-timestamp"
assert_status 1 is_nodered_install_pending

# A clock that moved backwards is not evidence the install is old.
write_pending_marker "$(date -Iseconds -d '1 hour')"
assert_status 0 is_nodered_install_pending

mark_nodered_install_pending

mark_nodered_managed "test-flow-hash"
jq -e \
	'.nodered_managed == true and .flows_hash == "test-flow-hash" and .prevent_flow_updates == false' \
	"$STATE_FILE" >/dev/null
test ! -e "$NODERED_INSTALL_PENDING_FILE"
test ! -e "${STATE_FILE}.tmp"

echo "orchestrator state tests passed"
