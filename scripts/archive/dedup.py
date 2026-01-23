#!/usr/bin/env python3
import json

seen = set()
with open('/mnt/c/Users/Datision/Documents/grundrisse/investigation_results.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line.strip())
        wid = data['work_id']
        if wid not in seen:
            seen.add(wid)
            print(json.dumps(data, ensure_ascii=False))
