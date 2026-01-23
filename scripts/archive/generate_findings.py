#!/usr/bin/env python3
"""
Generate investigation findings from auto-investigation results
"""
import json
import sys

def generate_finding(auto_result):
    """Generate a finding from auto-investigation result"""
    work_id = auto_result["work_id"]
    title = auto_result["title"]
    author = auto_result["author"]

    url_date = auto_result.get("url_date")
    source_dates = auto_result.get("source_metadata_dates", [])
    work_pub_date = auto_result.get("work_pub_date")

    # Determine best date
    best_date = None
    confidence = "medium"
    source = "unknown"
    precision = "year"
    evidence = ""
    issue = ""
    fix_method = ""

    # Priority: source metadata dates > URL dates (for most cases)
    # Exception: for letters/speeches, URL date is often written date

    # Check for day-precision dates first
    day_precision_dates = [d for d in source_dates if d["precision"] == "day"]
    if day_precision_dates:
        best = day_precision_dates[0]
        best_date = best["date"]
        precision = "day"
        source = best["source"]
        confidence = "high"
        evidence = f"{best['source']}: {best_date}"
        issue = f"Parser extracted date but may not be in derived_date"
        fix_method = f"Ensure {best['source']} parsing feeds into work_date_deriver"
    elif url_date and url_date["precision"] == "day":
        best_date = url_date["date"]
        precision = "day"
        source = "url_path"
        confidence = "high"
        evidence = f"URL path contains date: {best_date}"
        issue = "URL date heuristic exists but may not extract full precision"
        fix_method = "Enhance URL parser to extract /YYYY/MM/DD format"
    elif source_dates:
        best = source_dates[0]
        best_date = best["date"]
        precision = best["precision"]
        source = best["source"]
        confidence = "high" if best["precision"] == "day" else "medium"
        evidence = f"{best['source']}: {best_date}"
        issue = "Source metadata has date but parser may not extract it"
        fix_method = f"Improve {best['source']} parsing"
    elif url_date:
        best_date = url_date["date"]
        precision = url_date["precision"]
        source = "url_path"
        confidence = "medium" if precision == "year" else "high"
        evidence = f"URL path: {best_date}"
        issue = "URL heuristic working but may need precision enhancement"
        fix_method = "URL date extraction functioning"
    elif work_pub_date and isinstance(work_pub_date, dict) and "year" in work_pub_date:
        # Has derived date already
        if work_pub_date.get("method"):
            # This is a derived date with metadata
            best_date = str(work_pub_date.get("year"))
            if work_pub_date.get("month"):
                best_date += f"-{work_pub_date['month']:02d}"
            if work_pub_date.get("day"):
                best_date += f"-{work_pub_date['day']:02d}"
            precision = work_pub_date.get("precision", "year")
            source = work_pub_date.get("method", "unknown")
            confidence = "low" if work_pub_date.get("confidence", 0) < 0.5 else "medium"
            evidence = f"Existing derived date via {source}: {best_date}"
            issue = "Date derived but confidence may be low or method suspect"
            fix_method = "Verify accuracy of derived date method"
        else:
            # Simple year dict
            best_date = str(work_pub_date["year"])
            precision = "year"
            source = "work.publication_date"
            confidence = "medium"
            evidence = f"work.publication_date has year: {best_date}"
            issue = "Year available but no month/day"
            fix_method = "Check if URL or source metadata can provide more precision"
    else:
        # No date found
        best_date = None
        confidence = "uncertain"
        source = "none"
        evidence = "No date found in URL or source metadata"
        issue = "Missing publication date entirely"
        fix_method = "Requires web search or text inspection"

    finding = {
        "work_id": work_id,
        "title": title,
        "author": author,
        "investigation_date": "2026-01-20",
        "findings": {
            "correct_date": best_date,
            "confidence": confidence,
            "source": source,
            "evidence": evidence,
            "precision": precision,
            "issue": issue,
            "fix_method": fix_method
        }
    }

    return finding

if __name__ == '__main__':
    with open('/mnt/c/Users/Datision/Documents/grundrisse/auto_investigation_output.json', 'r') as f:
        for line in f:
            auto_result = json.loads(line.strip())
            # Skip work #5 (already done manually)
            if auto_result['work_id'] == '425158e0-adad-579c-8d41-83e6c7f4e0ec':
                continue
            finding = generate_finding(auto_result)
            print(json.dumps(finding, ensure_ascii=False))
