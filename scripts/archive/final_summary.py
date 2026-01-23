#!/usr/bin/env python3
"""
Generate investigation summary statistics
"""
import json
from collections import Counter

with open('/mnt/c/Users/Datision/Documents/grundrisse/investigation_results.jsonl', 'r') as f:
    investigations = [json.loads(line.strip()) for line in f]

print(f"INVESTIGATION SUMMARY")
print(f"=" * 80)
print(f"\nTotal works investigated: {len(investigations)}")

# Count by confidence
confidence_counts = Counter(inv['findings']['confidence'] for inv in investigations)
print(f"\nBy confidence level:")
for conf in ['high', 'medium', 'low', 'uncertain']:
    print(f"  {conf}: {confidence_counts.get(conf, 0)}")

# Count by precision
precision_counts = Counter(inv['findings']['precision'] for inv in investigations)
print(f"\nBy precision:")
for prec in ['day', 'month', 'year']:
    print(f"  {prec}: {precision_counts.get(prec, 0)}")

# Count by source
source_counts = Counter(inv['findings']['source'] for inv in investigations)
print(f"\nBy source (top 10):")
for source, count in source_counts.most_common(10):
    print(f"  {source}: {count}")

# Count missing dates
missing = [inv for inv in investigations if inv['findings']['correct_date'] is None]
print(f"\nWorks with no date found: {len(missing)}")
if missing:
    for inv in missing[:5]:
        print(f"  - {inv['title'][:50]} ({inv['author']})")

# Count by precision and confidence
print(f"\nDay precision + high confidence: {len([i for i in investigations if i['findings']['precision'] == 'day' and i['findings']['confidence'] == 'high'])}")
print(f"Month precision + high confidence: {len([i for i in investigations if i['findings']['precision'] == 'month' and i['findings']['confidence'] == 'high'])}")
print(f"Year precision + high confidence: {len([i for i in investigations if i['findings']['precision'] == 'year' and i['findings']['confidence'] == 'high'])}")

print("\n" + "=" * 80)
