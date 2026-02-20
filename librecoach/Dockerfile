ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest

# --- Build stage: install build-only tools ---
FROM $BUILD_FROM AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apk add --no-cache git python3 py3-pip

# Install Python dependencies (no venv needed — container is single-purpose)
RUN pip install --no-cache-dir --break-system-packages \
    python-can \
    paho-mqtt \
    pyserial \
    bitstruct

# Bundle the Node-RED Project
# Always pulls latest from main branch
# Keep flows_cred.json — contains MQTT credentials encrypted with "librecoach" as credential_secret
RUN git clone --depth 1 https://github.com/Backroads4Me/librecoach-node-red /opt/librecoach-project && \
    rm -rf /opt/librecoach-project/.git && \
    rm -f /opt/librecoach-project/.gitignore /opt/librecoach-project/.gitattributes

# --- Final stage: runtime only ---
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Runtime dependencies only (no git, no pip)
RUN apk add --no-cache \
    curl \
    jq \
    rsync \
    mosquitto-clients \
    coreutils \
    iproute2 \
    python3 \
    bluez \
    dbus-libs \
    can-utils

# Copy Python packages from builder to a staging dir, then move to correct location
COPY --from=builder /usr/lib/python3.*/site-packages/ /tmp/site-packages/
RUN PYDIR=$(python3 -c "import site; print(site.getsitepackages()[0])") && \
    cp -r /tmp/site-packages/* "$PYDIR/" && \
    rm -rf /tmp/site-packages

# Copy bundled Node-RED project from builder
COPY --from=builder /opt/librecoach-project /opt/librecoach-project

# Copy init scripts to bundled project (gets deployed to /share/.librecoach/)
# Copy init scripts to bundled project (gets deployed to /share/.librecoach/)
COPY init-nodered-overwrite.sh /opt/librecoach-project/init-nodered-overwrite.sh
COPY init-nodered-preserve.sh /opt/librecoach-project/init-nodered-preserve.sh

# Maintain default as overwrite (used if no config present or before orchestrator runs)
COPY init-nodered-overwrite.sh /opt/librecoach-project/init-nodered.sh

# Copy bundled HA integration (installed to /config/custom_components/ at runtime)
COPY librecoach_ble /opt/librecoach_ble

# Copy vehicle bridge source
COPY vehicle_bridge /opt/vehicle_bridge

# Copy s6 service definitions and cont-init.d scripts
COPY rootfs /
RUN chmod +x /etc/cont-init.d/*.sh 2>/dev/null || true

# Copy orchestrator as cont-init.d script (runs once at startup before services)
COPY --chmod=755 run.sh /etc/cont-init.d/orchestrator.sh

# Strip Windows CRLF line endings from all scripts and s6 config files
RUN find /etc/s6-overlay /etc/cont-init.d /opt/vehicle_bridge /opt/librecoach-project \
    /opt/librecoach_ble \
    -type f -exec sed -i 's/\r$//' {} + 2>/dev/null || true