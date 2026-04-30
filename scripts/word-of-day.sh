#!/bin/bash
# Fetches the real Word of the Day from Merriam-Webster's RSS feed.

RSS=$(curl -s --max-time 10 "https://www.merriam-webster.com/wotd/feed/rss2" 2>/dev/null)

echo "$RSS" | python3 -c "
import sys, re, html
from xml.etree import ElementTree as ET

try:
    data = sys.stdin.read()
    root = ET.fromstring(data)
    item = root.find('.//item')
    if item is None:
        print('word unavailable today')
        sys.exit()
    word = item.findtext('title', '').strip()
    desc = item.findtext('description', '')

    pos_match = re.search(r'<em>([^<]+)</em>', desc)
    pos = pos_match.group(1).strip() if pos_match else ''

    def_match = re.search(r'<em>[^<]+</em>[^<]*<br\s*/?>[^<]*<p>([^<]+)</p>', desc)
    if not def_match:
        def_match = re.search(r'<p>([^<]{30,})</p>', desc)
    definition = def_match.group(1).strip() if def_match else ''
    definition = html.unescape(definition).replace('  ', ' ')

    if pos and definition:
        print(f'{word} ({pos}) — {definition}')
    elif word:
        print(f'{word}')
    else:
        print('word unavailable today')
except Exception as e:
    print('word unavailable today')
"
