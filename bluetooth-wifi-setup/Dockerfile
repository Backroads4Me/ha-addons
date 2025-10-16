# syntax=docker/dockerfile:1

ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
ARG BUILD_VERSION=0.0.0
FROM ${BUILD_FROM}

# Add metadata labels
ARG BUILD_VERSION
LABEL \
    io.hass.name="Bluetooth WiFi Setup" \
    io.hass.description="Setup Bluetooth and WiFi from a web interface" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="Ted Lanham <tedlanham@gmail.com>"

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install required packages
# Note: Using Alpine packages for the Home Assistant base images
# NetworkManager is accessed via host D-Bus (host_dbus: true), not installed in container
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-dbus \
    py3-gobject3 \
    py3-cryptography \
    bluez \
    bluez-libs \
    bluez-deprecated \
    dbus \
    && rm -rf /var/cache/apk/*

# Copy addon files
COPY rootfs /

# Make run script executable
RUN chmod a+x /usr/local/btwifiset/run.sh

# Set working directory
WORKDIR /usr/local/btwifiset

# Run the addon
CMD ["/usr/local/btwifiset/run.sh"]