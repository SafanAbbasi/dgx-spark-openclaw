#!/bin/bash
# Silent watchdog: prints HEARTBEAT_OK on healthy, alert text otherwise.
# OpenClaw suppresses HEARTBEAT_OK so only real alerts reach Telegram.
export TZ="America/Chicago"
ALERTS=""

# Disk usage
DISK_PCT=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_PCT" -gt 85 ]; then
  ALERTS="$ALERTS\n⚠️ Disk usage is at ${DISK_PCT}%"
fi

# Available memory
AVAIL_GB=$(free -g | grep Mem | awk '{print $7}')
if [ "$AVAIL_GB" -lt 10 ]; then
  AVAIL_ACTUAL=$(free -h | grep Mem | awk '{print $7}')
  ALERTS="$ALERTS\n⚠️ Available memory is low: ${AVAIL_ACTUAL}"
fi

# GPU temperature
GPU_TEMP=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null | tr -d ' ')
if [ -n "$GPU_TEMP" ] && [ "$GPU_TEMP" -gt 80 ]; then
  ALERTS="$ALERTS\n⚠️ GPU temperature is high: ${GPU_TEMP}°C"
fi

# Ollama
if ! systemctl is-active --quiet ollama; then
  ALERTS="$ALERTS\n⚠️ Ollama is not running!"
fi

# Load average
LOAD=$(cat /proc/loadavg | awk '{print $1}')
LOAD_INT=$(echo "$LOAD" | awk '{printf "%d", $1}')
if [ "$LOAD_INT" -gt 8 ]; then
  ALERTS="$ALERTS\n⚠️ Load average is high: $LOAD"
fi

if [ -z "$ALERTS" ]; then
  echo "HEARTBEAT_OK"
else
  echo -e "🚨 DGX Spark Alert:$ALERTS"
fi
