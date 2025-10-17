# syntax=docker/dockerfile:1
# Copyright 2025 Ted Lanham
# Licensed under the MIT License

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
# WiFi management via Supervisor API (no nmcli/NetworkManager packages needed)
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
    wireless-tools \
    && rm -rf /var/cache/apk/*

# Copy addon files
COPY run.sh /
COPY main.py /
COPY app /app
COPY requirements.txt /

# Make run script executable
RUN chmod a+x /run.sh

# Run the addon
CMD ["/run.sh"]