ARG BUILD_FROM
FROM $BUILD_FROM

# Add metadata labels
LABEL \
    io.hass.name="CAN to MQTT Bridge" \
    io.hass.description="Initializes CAN interface and provides a bidirectional CAN-MQTT bridge" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="Ted Lanham <tedlanham@gmail.com>"

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
    s6-overlay \
    python3 \
    openssl \
    ca-certificates

# Copy and make executable the run script
COPY run.sh /
RUN chmod a+x /run.sh

# Create a healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s \
    CMD ps aux | grep -v grep | grep -q mosquitto_sub || exit 1

# Set the entrypoint
ENTRYPOINT ["/init"]
CMD ["/run.sh"]