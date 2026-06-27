ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest

# --- Build stage: install build-only tools ---
FROM $BUILD_FROM AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apk add --no-cache git python3 py3-pip

# Install Python dependencies
RUN pip install --no-cache-dir --break-system-packages \
    python-can==4.6.1 \
    paho-mqtt==2.1.0 \
    websockets==16.0

# Bundle the Node-RED project at the exact revision recorded in node-red.ref.
# Keep flows_cred.json — contains MQTT credentials encrypted with "librecoach" as credential_secret
COPY node-red.ref /tmp/node-red.ref
RUN NODE_RED_REF="$(tr -d '\r\n' < /tmp/node-red.ref)" && \
    [ "${#NODE_RED_REF}" -eq 40 ] && \
    case "$NODE_RED_REF" in *[!0-9a-f]*) exit 1 ;; esac && \
    git init /opt/librecoach-project && \
    git -C /opt/librecoach-project remote add origin https://github.com/Backroads4Me/librecoach-node-red && \
    git -C /opt/librecoach-project fetch --depth 1 origin "$NODE_RED_REF" && \
    git -C /opt/librecoach-project checkout --detach FETCH_HEAD && \
    [ "$(git -C /opt/librecoach-project rev-parse HEAD)" = "$NODE_RED_REF" ] && \
    test -f /opt/librecoach-project/artifact/flows.json && \
    test -f /opt/librecoach-project/flows_cred.json && \
    cp /tmp/node-red.ref /opt/librecoach-project/.librecoach-node-red-ref && \
    rm -rf /opt/librecoach-project/.git && \
    rm -f /opt/librecoach-project/.gitignore /opt/librecoach-project/.gitattributes /tmp/node-red.ref

# --- Final stage: runtime only ---
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Runtime dependencies only
RUN apk add --no-cache \
    rsync \
    mosquitto-clients \
    coreutils \
    iproute2 \
    python3

# Copy Python packages from builder to a staging dir, then move to correct location
COPY --from=builder /usr/lib/python3.*/site-packages/ /tmp/site-packages/
RUN PYDIR=$(python3 -c "import site; print(site.getsitepackages()[0])") && \
    cp -r /tmp/site-packages/* "$PYDIR/" && \
    rm -rf /tmp/site-packages

# Copy bundled Node-RED project from builder
COPY --from=builder /opt/librecoach-project /opt/librecoach-project

# Copy init scripts to bundled project (gets deployed to /share/.librecoach/)
COPY init-nodered-overwrite.sh /opt/librecoach-project/init-nodered-overwrite.sh
COPY init-nodered-preserve.sh /opt/librecoach-project/init-nodered-preserve.sh

# Maintain default as overwrite (used if no config present or before orchestrator runs)
COPY init-nodered-overwrite.sh /opt/librecoach-project/init-nodered.sh

# Copy bluetooth integration (installed to /config/custom_components/ at runtime)
COPY librecoach_ble /opt/librecoach_ble

# Copy vehicle bridge
COPY vehicle_bridge /opt/vehicle_bridge

# Copy s6 service definitions and cont-init.d scripts
COPY rootfs /
RUN chmod 755 \
    /etc/s6-overlay/s6-rc.d/vehicle-bridge/run \
    /etc/s6-overlay/s6-rc.d/vehicle-bridge/finish

# Copy orchestrator as cont-init.d script (runs once at startup before services)
COPY --chmod=755 run.sh /etc/cont-init.d/orchestrator.sh

# Strip Windows CRLF line endings from text files only (D-2).
# so unknown/future binary assets are never fed through sed and corrupted.
RUN find /etc/s6-overlay /etc/cont-init.d /opt/vehicle_bridge \
    /opt/librecoach-project /opt/librecoach_ble \
    -type f \( \
        -name "*.sh" -o -name "*.js" -o -name "*.json" -o -name "*.yaml" \
        -o -name "*.yml" -o -name "*.md" -o -name "*.txt" -o -name "*.html" \
        -o -name "*.css" -o -name "*.py" -o -name "*.conf" \
        -o -name "run" -o -name "finish" -o -name "type" -o -name "up" \
    \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
