#!/usr/bin/env bash
# Saved add-on options: production is independent, and a fresh beta/alpha
# install starts from production's settings. Updates restore nothing.
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

load_function choose_preserve_files
load_function restore_saved_options
load_function save_options

curl() {
	:
}

bashio::log.info() {
	:
}

bashio::log.warning() {
	echo "warning: $*" >&2
}

assert_json() {
	local file=$1 filter=$2 expected=$3 actual
	actual=$(jq -c "$filter" "$file")
	if [ "$actual" != "$expected" ]; then
		echo "Expected $filter in $file to be $expected, got $actual" >&2
		exit 1
	fi
}

AUTH_HEADER="Authorization: Bearer test"
SUPERVISOR="http://supervisor"

# One Home Assistant: a shared /share, and one /data per installed channel.
PRESERVE_DIR="$TEST_TMP/share/.librecoach-preserve"
PRESERVE_FILE="$PRESERVE_DIR/options.json"
PRERELEASE_PRESERVE_FILE="$PRESERVE_DIR/options-prerelease.json"

# Option schemas: production, and a beta that adds a feature production lacks.
SCHEMA_PROD='{"mqtt_pass":"default","debug_logging":false}'
SCHEMA_BETA='{"mqtt_pass":"default","debug_logging":false,"tank_enabled":false}'

# Install (fresh) or restart/update (existing) a version, then run the
# boot-time restore and save. An existing install that gains options on
# update receives their defaults from the Supervisor, as Home Assistant does.
boot() {
	local version=$1 schema=$2 mode=${3:-fresh}
	ADDON_VERSION=$version
	case "$version" in
	*-beta.*) DATA_DIR="$TEST_TMP/data-beta" ;;
	*-alpha.*) DATA_DIR="$TEST_TMP/data-alpha" ;;
	*) DATA_DIR="$TEST_TMP/data-release" ;;
	esac
	STATE_FILE="$DATA_DIR/.librecoach-state.json"
	OPTIONS_FILE="$DATA_DIR/options.json"
	if [ "$mode" = "fresh" ]; then
		rm -rf "$DATA_DIR"
		mkdir -p "$DATA_DIR"
		echo "$schema" >"$OPTIONS_FILE"
	else
		jq -c --argjson s "$schema" '$s * .' "$OPTIONS_FILE" >"$OPTIONS_FILE.new"
		mv "$OPTIONS_FILE.new" "$OPTIONS_FILE"
	fi
	choose_preserve_files
	restore_saved_options
	touch "$STATE_FILE"
	save_options
}

# The user edits options in the add-on UI and restarts it.
set_option() {
	jq -c "$1" "$OPTIONS_FILE" >"$OPTIONS_FILE.new"
	mv "$OPTIONS_FILE.new" "$OPTIONS_FILE"
	save_options
}

# Release and pre-release versions are told apart by the version string.
ADDON_VERSION=1.7.1
choose_preserve_files
[ "$IS_RELEASE_BUILD" = "true" ] && [ "$OWN_PRESERVE_FILE" = "$PRESERVE_FILE" ]
for version in 1.7.1-beta.4 1.7.1-alpha.2 "" null; do
	ADDON_VERSION=$version
	choose_preserve_files
	[ "$IS_RELEASE_BUILD" = "false" ] && [ "$OWN_PRESERVE_FILE" = "$PRERELEASE_PRESERVE_FILE" ]
done

# A tester who never ran production keeps settings across beta/alpha installs.
boot 1.7.1-beta.6 "$SCHEMA_BETA"
set_option '.mqtt_pass = "beta-pass" | .tank_enabled = true'
[ ! -f "$PRESERVE_FILE" ]
boot 1.7.1-alpha.4 "$SCHEMA_BETA"
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"beta-pass","debug_logging":false,"tank_enabled":true}'

# Production is independent: its first install never reads beta/alpha settings.
boot 1.7.1 "$SCHEMA_PROD"
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"default","debug_logging":false}'
set_option '.mqtt_pass = "prod-pass"'
assert_json "$PRESERVE_FILE" '.' '{"mqtt_pass":"prod-pass","debug_logging":false}'

# A fresh beta/alpha install takes production's value for every setting
# production has, and the last beta/alpha value for the rest.
boot 1.7.1-beta.6 "$SCHEMA_BETA"
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"prod-pass","debug_logging":false,"tank_enabled":true}'

# Beta/alpha updates and restarts keep the tester's changes.
set_option '.mqtt_pass = "beta-pass-2" | .debug_logging = true'
boot 1.7.1-beta.7 "$SCHEMA_BETA" existing
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"beta-pass-2","debug_logging":true,"tank_enabled":true}'

# Beta/alpha saves never touch production's settings.
assert_json "$PRESERVE_FILE" '.' '{"mqtt_pass":"prod-pass","debug_logging":false}'

# A fresh alpha install still starts from production, not from beta's changes.
boot 1.7.1-alpha.4 "$SCHEMA_BETA"
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"prod-pass","debug_logging":false,"tank_enabled":true}'

# Reinstalling production restores production's own settings.
boot 1.7.1 "$SCHEMA_PROD"
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"prod-pass","debug_logging":false}'

# Updating production in place changes nothing, even for a setting beta has:
# the new setting keeps its default.
boot 1.7.2 "$SCHEMA_BETA" existing
assert_json "$OPTIONS_FILE" '.' '{"mqtt_pass":"prod-pass","debug_logging":false,"tank_enabled":false}'

# Production saves exactly its own options, dropping keys it does not have.
jq -c '. + {"beta_only": true}' "$PRESERVE_FILE" >"$PRESERVE_FILE.new"
mv "$PRESERVE_FILE.new" "$PRESERVE_FILE"
boot 1.7.2 "$SCHEMA_BETA" existing
assert_json "$PRESERVE_FILE" 'has("beta_only")' 'false'

# An unreadable saved file is ignored; the other one still restores.
echo 'not json' >"$PRERELEASE_PRESERVE_FILE"
boot 1.7.1-beta.6 "$SCHEMA_BETA"
assert_json "$OPTIONS_FILE" '.mqtt_pass' '"prod-pass"'
# The next save repairs it.
assert_json "$PRERELEASE_PRESERVE_FILE" '.mqtt_pass' '"prod-pass"'

echo "preserved options tests passed"
