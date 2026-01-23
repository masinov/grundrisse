#!/usr/bin/env python3
"""
Benchmark GLM model variants for publication date investigation task.
"""
import json
import time
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add nlp_pipeline to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pipelines/nlp_pipeline/src"))

from nlp_pipeline.llm.zai_glm import ZaiGlmClient

MODELS = [
    "glm-4.7",
    "glm-4.7-flash",
    "glm-4.7-flashx",
    "glm-4.6v",
    "glm-4.5",
]

DEFAULT_SAMPLE_SIZE = 5


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark GLM models for date investigation")
    parser.add_argument("--models", type=str, default=",".join(MODELS))
    parser.add_argument("--sample-file", type=str, default="sample_100_works.json")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--work-ids", type=str, default="")
    parser.add_argument("--ground-truth", type=str, default="investigation_results.jsonl")
    return parser.parse_args()

INVESTIGATION_PROMPT_TEMPLATE = """You are investigating the publication date for a Marxist text.

WORK DETAILS:
Title: {title}
Author: {author}
URL: {url}

SOURCE METADATA:
{source_metadata}

FIRST 3 PARAGRAPHS:
{paragraphs}

CURRENT STATUS:
- Current display_date_field: {display_date_field}
- Current display_date: {display_date}

TASK:
Extract the ORIGINAL publication date (not collection/reprint/edition dates).

Check these sources IN ORDER:
1. source_metadata.fields - look for "First Published", "First published", "Published", "Delivered", "Source" (with dates in periodical citations)
2. Paragraph text - look for publication info like newspaper names, issue numbers, dates
3. URL path - extract year/month/day patterns like /YYYY/MM/DD.htm or /YYYY/mon/DD.htm

IMPORTANT:
- Distinguish between ORIGINAL publication and later editions/collections
- For letters, prefer written date over collection publication date
- For speeches, use delivery or first publication date, not collected works date
- Extract month/day precision when available, not just year

OUTPUT SCHEMA:
{{
  "correct_date": "YYYY-MM-DD or YYYY-MM or YYYY or null",
  "confidence": "high or medium or low",
  "source": "where you found it",
  "evidence": "exact text snippet",
  "precision": "day or month or year or null",
  "reasoning": "brief explanation"
}}
"""

def load_work_details(work_id: str):
    """Load work details from database"""
    from grundrisse_core.db.session import SessionLocal
    from grundrisse_core.db.models import Work, Author, Edition, Paragraph, WorkDateDerived
    from sqlalchemy import select

    with SessionLocal() as session:
        work = session.get(Work, work_id)
        if not work:
            return None

        author = session.get(Author, work.author_id)
        edition = session.execute(
            select(Edition).where(Edition.work_id == work_id).limit(1)
        ).scalar_one_or_none()

        derived = session.get(WorkDateDerived, work_id)

        paragraphs = []
        if edition:
            paras = session.execute(
                select(Paragraph)
                .where(Paragraph.edition_id == edition.edition_id)
                .limit(3)
            ).scalars().all()
            paragraphs = [p.text_normalized[:500] for p in paras]

        return {
            "work_id": work_id,
            "title": work.title,
            "author": author.name_canonical if author else "Unknown",
            "url": edition.source_url if edition else None,
            "source_metadata": json.dumps(edition.source_metadata, indent=2) if edition and edition.source_metadata else "null",
            "paragraphs": "\n\n".join(f"[Para {i+1}]\n{p}" for i, p in enumerate(paragraphs)),
            "display_date_field": derived.display_date_field if derived else "unknown",
            "display_date": json.dumps(derived.display_date) if derived and derived.display_date else "null",
        }

def test_model(model_name: str, work_details: dict, api_key: str, base_url: str) -> dict:
    """Test a model on a single work"""
    prompt = INVESTIGATION_PROMPT_TEMPLATE.format(**work_details)

    schema = {
        "type": "object",
        "properties": {
            "correct_date": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "source": {"type": "string"},
            "evidence": {"type": "string"},
            "precision": {"type": ["string", "null"]},
            "reasoning": {"type": "string"}
        },
        "required": ["correct_date", "confidence", "source", "evidence"]
    }

    start_time = time.time()

    try:
        with ZaiGlmClient(api_key=api_key, base_url=base_url, model=model_name) as client:
            response = client.complete_json(prompt=prompt, schema=schema)

        elapsed = time.time() - start_time

        if not response.json:
            return {
                "success": False,
                "error": f"Failed to parse JSON from response: {response.raw_text[:200]}",
                "elapsed_seconds": elapsed,
                "model": model_name
            }

        return {
            "success": True,
            "result": response.json,
            "elapsed_seconds": elapsed,
            "tokens_prompt": response.prompt_tokens or 0,
            "tokens_completion": response.completion_tokens or 0,
            "model": model_name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "elapsed_seconds": time.time() - start_time,
            "model": model_name
        }

def benchmark():
    """Run benchmark on sample works"""
    args = _parse_args()
    api_key = os.environ.get("GRUNDRISSE_ZAI_API_KEY")
    base_url = os.environ.get("GRUNDRISSE_ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")

    if not api_key:
        print("ERROR: GRUNDRISSE_ZAI_API_KEY not set")
        return None

    print("="*80)
    print("GLM MODEL BENCHMARK FOR PUBLICATION DATE INVESTIGATION")
    print("="*80)

    models = [m.strip() for m in args.models.split(",") if m.strip()]

    sample_work_ids: list[str] = []
    if args.work_ids.strip():
        sample_work_ids = [w.strip() for w in args.work_ids.split(",") if w.strip()]
    else:
        try:
            with open(args.sample_file, "r") as f:
                sample = json.load(f)
            sample_work_ids = [w["work_id"] for w in sample[: args.sample_size]]
        except Exception as exc:
            print(f"ERROR: Failed to load sample works: {exc}")
            return None

    # Load ground truth
    ground_truth: dict[str, dict[str, str]] = {}
    if args.ground_truth:
        try:
            with open(args.ground_truth, "r") as f:
                for line in f:
                    record = json.loads(line)
                    ground_truth[record["work_id"]] = record["findings"]
        except Exception as exc:
            print(f"WARNING: Failed to load ground truth: {exc}")
            ground_truth = {}

    results = []

    for model_name in models:
        print(f"\n{'='*80}")
        print(f"Testing: {model_name}")
        print(f"{'='*80}\n")

        model_results = {
            "model": model_name,
            "works_tested": 0,
            "successes": 0,
            "failures": 0,
            "correct_dates": 0,
            "total_time": 0,
            "total_tokens": 0,
            "avg_time": 0,
            "avg_tokens": 0,
            "tests": []
        }

        for work_id in sample_work_ids:
            print(f"Testing work: {work_id[:8]}...")

            details = load_work_details(work_id)
            if not details:
                print(f"  ERROR: Could not load work")
                continue

            test_result = test_model(model_name, details, api_key, base_url)

            model_results["works_tested"] += 1
            model_results["total_time"] += test_result["elapsed_seconds"]

            if test_result["success"]:
                model_results["successes"] += 1
                model_results["total_tokens"] += test_result["tokens_prompt"] + test_result["tokens_completion"]

                # Check if date is correct
                extracted_date = test_result["result"].get("correct_date")
                expected_date = ground_truth.get(work_id, {}).get("correct_date")

                if expected_date:
                    if extracted_date and extracted_date.startswith(expected_date[:4]):
                        model_results["correct_dates"] += 1
                        print(f"  ✓ SUCCESS - Date: {extracted_date} (expected: {expected_date})")
                    else:
                        print(f"  ✗ WRONG DATE - Got: {extracted_date}, Expected: {expected_date}")
                else:
                    print(f"  ? NO GROUND TRUTH - Got: {extracted_date}")

                print(f"    Time: {test_result['elapsed_seconds']:.2f}s, Tokens: {test_result['tokens_prompt'] + test_result['tokens_completion']}")
                print(f"    Confidence: {test_result['result'].get('confidence')}, Source: {test_result['result'].get('source')}")
            else:
                model_results["failures"] += 1
                print(f"  ERROR: {test_result['error']}")

            model_results["tests"].append(test_result)

        # Calculate averages
        if model_results["works_tested"] > 0:
            model_results["avg_time"] = model_results["total_time"] / model_results["works_tested"]
            if model_results["successes"] > 0:
                model_results["avg_tokens"] = model_results["total_tokens"] / model_results["successes"]

        results.append(model_results)

    # Print summary
    print(f"\n\n{'='*80}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*80}\n")

    print(f"{'Model':<20} {'Success':<10} {'Correct':<10} {'Avg Time':<12} {'Avg Tokens':<12} {'Recommendation':<20}")
    print("-" * 90)

    best_model = None
    best_score = 0

    for r in results:
        success_rate = r["successes"] / r["works_tested"] if r["works_tested"] > 0 else 0
        accuracy = r["correct_dates"] / r["successes"] if r["successes"] > 0 else 0

        # Score: accuracy * 0.7 + speed * 0.3 (lower time is better)
        speed_score = 1 / (r["avg_time"] + 0.1)  # Avoid div by zero
        score = accuracy * 0.7 + min(speed_score / 10, 0.3)

        recommendation = ""
        if score > best_score:
            best_score = score
            best_model = r["model"]
            recommendation = "★ BEST"

        success_str = f"{r['successes']}/{r['works_tested']}"
        correct_str = f"{r['correct_dates']}/{r['successes']}" if r['successes'] > 0 else "0/0"
        time_str = f"{r['avg_time']:.2f}s"
        tokens_str = str(int(r['avg_tokens'])) if r['avg_tokens'] > 0 else "0"
        print(f"{r['model']:<20} {success_str:<10} {correct_str:<10} {time_str:<12} {tokens_str:<12} {recommendation:<20}")

    print(f"\n{'='*80}")
    print(f"RECOMMENDATION: Use {best_model} for bulk investigation")
    print(f"{'='*80}\n")

    # Save detailed results
    with open("benchmark_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": results,
            "recommendation": best_model
        }, f, indent=2)

    print("Detailed results saved to benchmark_results.json")

    return best_model

if __name__ == '__main__':
    benchmark()
