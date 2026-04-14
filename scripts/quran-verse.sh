#!/bin/bash
# Pick a verse based on the day of year so it's different each day but repeatable
DAY_OF_YEAR=$(date '+%j')
YEAR=$(date '+%Y')
# 6236 total ayahs in the Quran
AYAH=$(( (DAY_OF_YEAR * 17 + YEAR) % 6236 + 1 ))

RESPONSE=$(curl -s "https://api.alquran.cloud/v1/ayah/$AYAH/editions/quran-uthmani,en.sahih" 2>/dev/null)

if [ $? -eq 0 ]; then
  echo "$RESPONSE" | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('code') == 200:
    arabic = d['data'][0]
    english = d['data'][1]
    surah_ar = arabic['surah']['name']
    surah_en = arabic['surah']['englishName']
    ayah_num = arabic['numberInSurah']
    print(f'=== Quran Verse of the Day ===')
    print()
    print(f'{arabic[\"text\"]}')
    print()
    print(f'{english[\"text\"]}')
    print()
    print(f'— {surah_en} ({surah_ar}), Ayah {ayah_num}')
else:
    print('Could not fetch verse')
"
else
  echo "Could not reach Quran API"
fi
