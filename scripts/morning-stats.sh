#!/bin/bash
export TZ="America/Chicago"
echo "=== Date ==="
echo ""
echo "  $(date '+%A, %B %d, %Y')"
echo "  $(/home/saffyai/.local/hijri-venv/bin/python3 -c "
from hijridate import Gregorian
from datetime import datetime
import zoneinfo
today = datetime.now(zoneinfo.ZoneInfo('America/Chicago')).date()
h = Gregorian.fromdate(today).to_hijri()
months = ['Muharram','Safar','Rabi al-Awwal','Rabi al-Thani','Jumada al-Ula','Jumada al-Thani','Rajab','Shaban','Ramadan','Shawwal','Dhul Qadah','Dhul Hijjah']
print(f'{h.day} {months[h.month-1]} {h.year} AH')
")"
echo ""
echo "=== DGX System Stats ==="
echo ""
echo "Disk Usage:"
df -h / | tail -1 | awk '{print "  Size: "$2"  Used: "$3"  Avail: "$4"  Use%: "$5}'
echo ""
echo "Memory:"
free -h | grep Mem | awk '{print "  Total: "$2"  Used: "$3"  Cached: "$6"  Available: "$7}'
echo ""
echo "GPU Temperature:"
echo "  $(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader)°C"
echo ""
echo "=== TODAY's events ($(date '+%A %B %d')) ==="
echo ""
export PATH="$HOME/.local/bin:$PATH"
EVENTS=$(gog calendar list --today --plain --all 2>/dev/null | tail -n +2 | awk -F'\t' '{
  start=$3; end=$4; name=$5
  gsub(/.*T/,"",start); gsub(/-05:00$/,"",start)
  gsub(/.*T/,"",end); gsub(/-05:00$/,"",end)
  print "  " name " | " start " - " end
}')
if [ -z "$EVENTS" ]; then
  echo "  No events today"
else
  echo "$EVENTS"
fi
echo ""
echo "=== TOMORROW's events ($(date -d '+1 day' '+%A %B %d')) ==="
echo ""
TOMORROW=$(gog calendar list --tomorrow --plain --all 2>/dev/null | tail -n +2 | awk -F'\t' '{
  start=$3; end=$4; name=$5
  gsub(/.*T/,"",start); gsub(/-05:00$/,"",start)
  gsub(/.*T/,"",end); gsub(/-05:00$/,"",end)
  print "  " name " | " start " - " end
}')
if [ -z "$TOMORROW" ]; then
  echo "  No events tomorrow"
else
  echo "$TOMORROW"
fi
