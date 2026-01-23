#!/usr/bin/env python3
"""
Merge manual updates into investigation results
"""
import json

# Load manual updates
updates = {}
with open('/mnt/c/Users/Datision/Documents/grundrisse/scripts/manual_updates.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line.strip())
        updates[data['work_id']] = data

# Load and update investigation results
with open('/mnt/c/Users/Datision/Documents/grundrisse/investigation_results.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line.strip())
        wid = data['work_id']
        if wid in updates:
            # Use the manually updated version
            print(json.dumps(updates[wid], ensure_ascii=False))
        else:
            # Keep the existing version
            print(json.dumps(data, ensure_ascii=False))
