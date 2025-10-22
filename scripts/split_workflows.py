#!/usr/bin/env python3
import json
import re
import pathlib

def slugify(name):
    return re.sub(r'[^a-zA-Z0-9]+', '-', name.lower()).strip('-')

with open('n8n/demo-data/workflows/workflows1.json', 'r', encoding='utf-8') as f:
    workflows = json.load(f)

for wf in workflows:
    wf_id = wf['id']
    name = wf['name']
    filename = f"{wf_id}-{slugify(name)}.json"
    with open(f"n8n/demo-data/workflows/{filename}", 'w') as f:
        json.dump(wf, f, indent=2)

print(f"Split {len(workflows)} workflows into separate files.")