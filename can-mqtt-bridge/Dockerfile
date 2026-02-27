# syntax=docker/dockerfile:1
# Copyright 2025-2026 Ted Lanham
# Licensed under the MIT License

ARG BUILD_FROM=ghcr.io/home-assistant/armv7-addon-base:latest
ARG BUILD_VERSION=0.0.0
FROM ${BUILD_FROM}

# Add metadata labels
ARG BUILD_VERSION
LABEL \
    io.hass.name="CAN to MQTT Bridge" \
    io.hass.description="Initializes CAN interface and provides a bidirectional CAN-MQTT bridge" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="Ted Lanham <Backroads4Me@gmail.com>"

# Set working directory
WORKDIR /data

# Install required packages
RUN apk add --no-cache \
    bash \
    can-utils \
    mosquitto-clients \
    iproute2 \
    procps \
    coreutils \
    jq \
    python3

# Copy and make executable the run script
COPY run.sh / 
RUN chmod a+x /run.sh

# Create a healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s \
    CMD ps aux | grep -v grep | grep -q mosquitto_sub || exit 1

# Set the entrypoint
ENTRYPOINT ["/init"]
CMD ["/run.sh"]
