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
RUN git clone --depth 1 https://github.com/Backroads4Me/libre-coach-node-red /opt/libre-coach-project && \
    rm -rf /opt/libre-coach-project/.git && \
    rm -f /opt/libre-coach-project/.gitignore /opt/libre-coach-project/.gitattributes /opt/libre-coach-project/flows_cred.json

# Copy run script and make it executable
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
