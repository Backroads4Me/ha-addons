ARG BUILD_FROM
FROM $BUILD_FROM

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install required packages
# Note: Using Alpine packages for the Home Assistant base images
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
    networkmanager \
    networkmanager-wifi \
    && rm -rf /var/cache/apk/*

# Copy addon files
COPY rootfs /

# Make run script executable
RUN chmod a+x /usr/local/btwifiset/run.sh

# Set working directory
WORKDIR /usr/local/btwifiset

# Run the addon
CMD ["/usr/local/btwifiset/run.sh"]
