#!/usr/bin/env python3
"""
Grundrisse Metadata Pipeline

Unified pipeline for reproducing the complete metadata extraction and derivation
process for the Grundrisse corpus.

This script orchestrates the entire metadata pipeline in the correct order:
1. Initial metadata extraction from ingested content
2. Author lifespan resolution (Wikidata)
3. Publication date resolution (external APIs)
4. Work date derivation from collected evidence
5. First publication date finalization

Usage:
    python scripts/pipeline/metadata.py --all                    # Run complete pipeline
    python scripts/pipeline/metadata.py --step extract          # Extract metadata from ingested works
    python scripts/pipeline/metadata.py --step resolve-authors  # Resolve author lifespans
    python scripts/pipeline/metadata.py --step resolve-dates    # Resolve publication dates
    python scripts/pipeline/metadata.py --step derive           # Derive work dates
    python scripts/pipeline/metadata.py --step finalize         # Finalize first publication dates
    python scripts/pipeline/metadata.py --status               # Show pipeline status
"""
import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, WorkDateDerived, WorkMetadataRun
)
from sqlalchemy import select, func


class MetadataPipeline:
    """Orchestrates the complete metadata pipeline."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.start_time = datetime.now(timezone.utc)

    def _run_cli(self, command: list[str]) -> bool:
        """Run a grundrisse-ingest CLI command."""
        if self.dry_run:
            print(f"  [DRY RUN] Would run: {' '.join(command)}")
            return True

        try:
            result = subprocess.run(
                ["grundrisse-ingest"] + command,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                print(f"  Error: {result.stderr}")
                return False
            return True
        except Exception as e:
            print(f"  Error: {e}")
            return False

    def status(self) -> dict:
        """Show current pipeline status."""
        with SessionLocal() as session:
            # Count works by date field status
            status_counts = session.execute(
                select(
                    WorkDateDerived.display_date_field,
                    func.count(Work.work_id)
                )
                .group_by(WorkDateDerived.display_date_field)
                .order_by(func.count(Work.work_id).desc())
            ).all()

            total_works = session.execute(select(func.count(Work.work_id))).scalar()

            return {
                "total_works": total_works,
                "status_breakdown": {field: count for field, count in status_counts},
                "coverage": f"{(total_works - status_counts.get(('unknown',), (0,))[0]) / total_works * 100:.1f}%" if total_works else "0%"
            }

    def extract_metadata(self) -> dict:
        """
        Step 1: Extract metadata from all ingested works.

        This includes:
        - Marxists.org header metadata from HTML
        - Source URL path dates
        """
        print("\n" + "="*80)
        print("STEP 1: EXTRACT METADATA")
        print("="*80)

        # 1a. Extract Marxists.org header metadata
        print("\n1a. Extracting Marxists.org header metadata...")
        success1a = self._run_cli([
            "extract-marxists-source-metadata",
            "--limit", "20000"
        ])

        # 1b. Materialize header metadata to evidence rows
        print("\n1b. Materializing header metadata...")
        success1b = self._run_cli([
            "materialize-marxists-header",
            "--limit", "20000"
        ])

        return {"status": "completed", "header_extraction": success1a and success1b}

    def resolve_authors(self) -> dict:
        """
        Step 2: Resolve author lifespans from Wikidata.

        Fetches birth/death years for authors missing this data.
        """
        print("\n" + "="*80)
        print("STEP 2: RESOLVE AUTHOR LIFESPANS")
        print("="*80)

        # Resolve author lifespans
        print("\nResolving author lifespans from Wikidata...")
        success = self._run_cli([
            "resolve-author-lifespans",
            "--only-missing",
            "--limit", "2000"
        ])

        return {"status": "completed", "resolved": success}

    def resolve_dates(self) -> dict:
        """
        Step 3: Resolve publication dates using external APIs.

        Uses OpenLibrary, Wikidata, and other sources to find
        publication dates for works.
        """
        print("\n" + "="*80)
        print("STEP 3: RESOLVE PUBLICATION DATES")
        print("="*80)

        # Resolve publication dates
        print("\nResolving publication dates from external APIs...")
        success = self._run_cli([
            "resolve-publication-dates",
            "--only-missing",
            "--limit", "20000"
        ])

        return {"status": "completed", "resolved": success}

    def derive_dates(self) -> dict:
        """
        Step 4: Derive work dates from collected evidence.

        Analyzes all evidence and derives the most likely publication date
        for each work using confidence scoring.
        """
        print("\n" + "="*80)
        print("STEP 4: DERIVE WORK DATES")
        print("="*80)

        # Derive work dates
        print("\nDeriving work dates from evidence...")
        success = self._run_cli([
            "derive-work-dates",
            "--force",
            "--limit", "20000"
        ])

        return {"status": "completed", "derived": success}

    def finalize_dates(self) -> dict:
        """
        Step 5: Finalize first publication dates.

        Copies derived dates to the canonical first_publication_date field.
        """
        print("\n" + "="*80)
        print("STEP 5: FINALIZE FIRST PUBLICATION DATES")
        print("="*80)

        print("\nFinalizing first publication dates...")
        success = self._run_cli([
            "finalize-first-publication-dates",
            "--force"
        ])

        return {"status": "completed", "finalized": success}

    def run_all(self, skip: list[str] = None) -> dict:
        """
        Run the complete pipeline in order.

        Args:
            skip: List of step names to skip (e.g., ['resolve-authors', 'resolve-dates'])
        """
        skip = skip or []

        steps = [
            ("extract_metadata", "Extract metadata"),
            ("resolve_authors", "Resolve authors"),
            ("resolve_dates", "Resolve dates"),
            ("derive_dates", "Derive dates"),
            ("finalize_dates", "Finalize dates"),
        ]

        results = {}

        print("\n" + "="*80)
        print("GRUNDRESSE METADATA PIPELINE")
        print("="*80)
        print(f"Started: {self.start_time.isoformat()}")
        print(f"Skip steps: {skip or 'none'}")

        for step_name, step_desc in steps:
            if step_name in skip:
                print(f"\n[SKIP] {step_desc}")
                continue

            try:
                result = getattr(self, step_name)()
                results[step_name] = result
            except Exception as e:
                print(f"\n[ERROR] {step_desc} failed: {e}")
                results[step_name] = {"status": "error", "error": str(e)}

        # Show final status
        self._print_status()

        return results

    def _print_status(self):
        """Print current pipeline status."""
        status = self.status()

        print("\n" + "="*80)
        print("PIPELINE STATUS")
        print("="*80)

        print(f"\nTotal works: {status['total_works']:,}")
        print(f"\nDate source breakdown:")

        for field, count in status['status_breakdown'].items():
            if isinstance(field, tuple):
                field = field[0]
            pct = count / status['total_works'] * 100
            print(f"  {field}: {count:,} ({pct:.1f}%)")

        print(f"\nCoverage: {status['coverage']}")


def main():
    parser = argparse.ArgumentParser(
        description="Grundrisse Metadata Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without executing")
    parser.add_argument("--step", type=str, default=None,
                        choices=["all", "extract_metadata", "resolve_authors",
                                "resolve_dates", "derive_dates", "finalize_dates", "status"],
                        help="Run a specific step or 'all'")
    parser.add_argument("--skip", type=str, default="",
                        help="Comma-separated steps to skip")

    args = parser.parse_args()

    pipeline = MetadataPipeline(dry_run=args.dry_run)

    if args.step == "status":
        status = pipeline.status()
        print(f"\nTotal works: {status['total_works']:,}")
        print(f"\nDate source breakdown:")
        for field, count in status['status_breakdown'].items():
            if isinstance(field, tuple):
                field = field[0]
            pct = count / status['total_works'] * 100
            print(f"  {field}: {count:,} ({pct:.1f}%)")
        print(f"\nCoverage: {status['coverage']}")
        return

    if args.step == "all":
        results = pipeline.run_all(skip=args.skip.split(",") if args.skip else None)
    elif args.step:
        results = getattr(pipeline, args.step)()
    else:
        parser.print_help()
        return

    # Print summary
    print(f"\n{'='*80}")
    print("PIPELINE COMPLETE")
    print(f"{'='*80}")
    print(f"Duration: {datetime.now(timezone.utc) - pipeline.start_time}")


if __name__ == "__main__":
    main()
