#!/usr/bin/env bash
# NomadTools device check: reports what this CardputerZero can actually do
# for AV testing (HDMI modes, EDID, audio devices, camera modes, displays).
# Safe to run: read-only, no settings are changed.
# Usage: ./device_check.sh > device_report.txt 2>&1

section() { printf '\n===== %s =====\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

section "System"
uname -a
cat /etc/os-release 2>/dev/null | grep -E '^(PRETTY_NAME|VERSION)='
tr -d '\0' < /proc/device-tree/model 2>/dev/null; echo
free -m | head -2
grep -E '^(dtoverlay|hdmi|display|camera_auto|start_x|gpu_mem)' /boot/firmware/config.txt /boot/config.txt 2>/dev/null

section "DRM connectors (HDMI and LCD)"
for c in /sys/class/drm/card*-*; do
  [ -e "$c/status" ] || continue
  echo "$(basename "$c"): status=$(cat "$c/status") enabled=$(cat "$c/enabled" 2>/dev/null)"
  if [ -s "$c/modes" ]; then echo "  modes: $(sort -u "$c/modes" | tr '\n' ' ')"; fi
done
for d in /sys/class/drm/card*; do
  [ -e "$d/device/driver" ] && echo "$(basename "$d") driver: $(basename "$(readlink "$d/device/driver")")"
done

section "Framebuffers"
for f in /sys/class/graphics/fb*; do
  [ -e "$f" ] || continue
  echo "$(basename "$f"): name=$(cat "$f/name" 2>/dev/null) size=$(cat "$f/virtual_size" 2>/dev/null) bpp=$(cat "$f/bits_per_pixel" 2>/dev/null)"
done

section "HDMI modes with refresh rates (modetest)"
if have modetest; then
  modetest -c 2>/dev/null | grep -E '^[0-9]+|#[0-9]+ ' | head -80
else
  echo "modetest not installed (sudo apt install libdrm-tests)"
fi

section "EDID of connected HDMI display"
for c in /sys/class/drm/card*-HDMI-A-*; do
  [ -s "$c/edid" ] || { echo "$(basename "$c"): no EDID (nothing connected?)"; continue; }
  echo "$(basename "$c"): $(stat -c %s "$c/edid") bytes"
  if have edid-decode; then edid-decode "$c/edid" 2>/dev/null | head -120
  else echo "edid-decode not installed (sudo apt install edid-decode)"; fi
done

section "Audio playback devices"
aplay -l 2>&1
section "Audio capture devices"
arecord -l 2>&1
section "ALSA cards"
cat /proc/asound/cards 2>/dev/null

section "Camera"
if have rpicam-hello; then rpicam-hello --list-cameras 2>&1
elif have libcamera-hello; then libcamera-hello --list-cameras 2>&1
else echo "rpicam-apps not installed (sudo apt install rpicam-apps)"; fi

section "Input devices (keyboard)"
grep -E '^N: Name=' /proc/bus/input/devices 2>/dev/null

section "Network"
ip -brief addr 2>/dev/null

section "CEC"
ls /dev/cec* 2>/dev/null || echo "no /dev/cec* device"

section "Python"
python3 --version
python3 - <<'PY'
for m in ("pygame", "numpy", "picamera2"):
    try:
        mod = __import__(m)
        print(m, getattr(mod, "__version__", getattr(getattr(mod, "version", None), "ver", "ok")))
    except Exception as e:
        print(m, "MISSING:", e.__class__.__name__)
PY

echo
echo "Done. Please send this whole output back."
