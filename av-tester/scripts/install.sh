#!/usr/bin/env bash
# Installs the AV tester's dependencies from the OS package manager.
set -e
sudo apt-get update
sudo apt-get install -y python3-pygame python3-numpy alsa-utils libdrm-tests edid-decode
echo "Installed. Run: ./scripts/device_check.sh"
