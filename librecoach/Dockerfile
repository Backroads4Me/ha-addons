ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install dependencies
# git, curl, jq, bash: For Orchestrator
# mosquitto-clients: For MQTT connectivity verification
RUN apk add --no-cache \
    git \
    curl \
    jq \
    bash \
    rsync \
    mosquitto-clients \
    coreutils \
    openssl \
    ca-certificates \
    && rm -rf /var/cache/apk/*

# Bundle the Node-RED Project
# Always pulls latest from main branch
RUN git clone --depth 1 https://github.com/Backroads4Me/librecoach-node-red /opt/librecoach-project && \
    rm -rf /opt/librecoach-project/.git && \
    rm -f /opt/librecoach-project/.gitignore /opt/librecoach-project/.gitattributes /opt/librecoach-project/flows_cred.json

# Copy run script and make it executable
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
