#!/usr/bin/env python3
import json

# Load sample works
with open('/mnt/c/Users/Datision/Documents/grundrisse/sample_100_works.json', 'r') as f:
    sample = json.load(f)
sample_ids = set(w['work_id'] for w in sample)

# Load investigated works
with open('/mnt/c/Users/Datision/Documents/grundrisse/investigation_results.jsonl', 'r') as f:
    investigated_ids = set(json.loads(line.strip())['work_id'] for line in f)

# Find missing
missing = sample_ids - investigated_ids
print(f"Total sample: {len(sample_ids)}")
print(f"Investigated: {len(investigated_ids)}")
print(f"Missing: {len(missing)}")
for wid in missing:
    work = next(w for w in sample if w['work_id'] == wid)
    print(f"\nMissing work: {work['title']}")
    print(f"  Author: {work['author']}")
    print(f"  ID: {wid}")
