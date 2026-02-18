#!/bin/bash
if [ ! -S /run/dbus/system_bus_socket ]; then
    echo "ERROR: D-Bus system bus socket not found"
    echo "Ensure host_dbus: true is set in config.yaml"
    exit 1
fi
echo "D-Bus system bus socket verified"
