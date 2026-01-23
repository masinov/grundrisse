#!/usr/bin/env python3
"""
Master Metadata Completion Pipeline Executor

Orchestrates the complete metadata completion process across all phases.

Usage:
    python master_metadata_completion.py --phase 0     # Code fixes only
    python master_metadata_completion.py --phase all    # Full pipeline
    python master_metadata_completion.py --phase 1-3    # Phases 1 through 3
"""
import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived, WorkMetadataRun,
    WorkMetadataEvidence, WorkDateDerivationRun, WorkDateDerived
)
from sqlalchemy import select, func, update


class MetadataCompletionPipeline:
    """Orchestrates the complete metadata completion pipeline."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.results = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phases": {},
            "final_stats": {}
        }

    def run_phase(self, phase: int) -> dict:
        """Run a specific phase and return results."""
        phase_methods = {
            0: self.phase0_code_fixes,
            1: self.phase1_url_recovery,
            2: self.phase2_author_lifespans,
            3: self.phase3_external_enrichment,
            4: self.phase4_derivation_qa,
            5: self.phase5_uncertainty_annotation,
        }

        if phase not in phase_methods:
            raise ValueError(f"Invalid phase: {phase}")

        print(f"\n{'='*80}")
        print(f"PHASE {phase}: {self._phase_name(phase)}")
        print(f"{'='*80}")

        result = phase_methods[phase]()
        self.results["phases"][f"phase_{phase}"] = result
        return result

    def run_all_phases(self, skip: list[int] = None) -> dict:
        """Run all phases sequentially."""
        skip = skip or []

        print("\n" + "="*80)
        print("MASTER METADATA COMPLETION PIPELINE")
        print("="*80)
        print(f"Started: {self.results['started_at']}")
        print(f"Dry run: {self.dry_run}")
        print(f"Skip phases: {skip or 'none'}")

        for phase in range(6):
            if phase in skip:
                print(f"\n[SKIP] Phase {phase}")
                continue
            try:
                self.run_phase(phase)
            except Exception as e:
                print(f"\n[ERROR] Phase {phase} failed: {e}")
                self.results["phases"][f"phase_{phase}"] = {"error": str(e)}
                if not self.dry_run:
                    raise  # Stop on error in production

        self.results["finished_at"] = datetime.now(timezone.utc).isoformat()

        # Print final summary
        self._print_summary()

        # Save results
        self._save_results()

        return self.results

    def _phase_name(self, phase: int) -> str:
        names = {
            0: "Code Fixes & Infrastructure",
            1: "URL Date Recovery",
            2: "Author Lifespan Resolution",
            3: "External Enrichment (GLM-4.7)",
            4: "Derivation & QA",
            5: "Uncertainty Annotation"
        }
        return names.get(phase, f"Phase {phase}")

    def phase0_code_fixes(self) -> dict:
        """
        Phase 0: Apply code corrections to parsing logic.

        This phase modifies the source code to fix:
        1. Case-insensitive field matching
        2. "Date" field support
        3. Full URL date extraction
        4. work.publication_date fallback
        """
        print("\nApplying code fixes...")

        fixes_applied = []

        # Check if fixes are already applied by looking for markers
        fix_file = Path("/mnt/c/Users/Datision/Documents/grundrisse/scripts/phase0_fixes_applied.flag")
        if fix_file.exists():
            print("  Code fixes already applied (flag file exists)")
            with open(fix_file) as f:
                return json.load(f)

        # The actual code fixes will be applied via git or direct file modification
        # For now, we'll track what NEEDS to be fixed

        fixes_needed = [
            "marxists_header_metadata.py: Add case-insensitive field matching",
            "marxists_header_metadata.py: Add 'Date' field support",
            "marxists_header_metadata.py: Add 'Delivered' field support",
            "publication_date_resolver.py: Add full URL date extraction",
            "work_date_deriver.py: Add URL date as high-priority candidate",
            "work_date_deriver.py: Add work.publication_date fallback",
        ]

        print(f"  Fixes needed: {len(fixes_needed)}")
        for fix in fixes_needed:
            print(f"    - {fix}")

        return {
            "status": "needs_manual_execution",
            "fixes_needed": fixes_needed,
            "instruction": "Run scripts/apply_phase0_fixes.py to apply all fixes"
        }

    def phase1_url_recovery(self) -> dict:
        """Phase 1: Extract dates from all marxists.org URLs."""
        import re

        print("\nScanning for URL dates...")

        with SessionLocal() as session:
            # Create run record first (required for foreign key)
            run_id = uuid.uuid4()
            run = WorkMetadataRun(
                run_id=run_id,
                pipeline_version="metadata_completion_v1",
                git_commit_hash=None,
                strategy="phase1_url_date_recovery",
                params={"target": "unknown_works_with_url_dates"},
                sources=["marxists_url_path"],
                started_at=datetime.now(timezone.utc),
                status="started",
                works_scanned=0,
                works_updated=0,
                works_skipped=0,
                works_failed=0,
            )
            session.add(run)
            session.commit()

            # Find works with unknown dates that have year-like URLs
            works_with_urls = session.execute(
                select(
                    Work.work_id,
                    Work.title,
                    Author.name_canonical,
                    func.array_agg(Edition.source_url.distinct()).label("urls")
                )
                .select_from(Work)
                .join(Author)
                .join(Edition, Edition.work_id == Work.work_id)
                .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
                .where(WorkDateDerived.display_date_field == "unknown")
                .where(Edition.source_url.op("~*")(r"/\d{4}/"))
                .group_by(Work.work_id, Work.title, Author.name_canonical)
            ).all()

            print(f"  Found {len(works_with_urls)} works with date-like URLs")

            recovered = 0

            for work_id, title, author, urls in works_with_urls:
                for url in urls:
                    if not url:
                        continue

                    # Extract date with full precision
                    date_info = self._extract_full_date_from_url(url)
                    if date_info:
                        # Write evidence row
                        if not self.dry_run:
                            evidence = WorkMetadataEvidence(
                                evidence_id=uuid.uuid4(),
                                run_id=run_id,
                                work_id=work_id,
                                source_name="marxists_url_path",
                                source_locator=url,
                                retrieved_at=datetime.now(timezone.utc),
                                extracted=date_info,
                                score=0.98,
                                raw_payload={"url": url, "extraction_method": "url_regex_v2"},
                                notes="URL date extraction with full precision"
                            )
                            session.add(evidence)
                        recovered += 1
                        break  # One date per work is enough

            if not self.dry_run:
                # Commit all evidence rows
                session.commit()

                # Update run record
                run.works_scanned = len(works_with_urls)
                run.works_updated = recovered
                run.status = "completed"
                run.finished_at = datetime.now(timezone.utc)
                session.commit()

            # Also check exact count of URL-date works in full corpus
            total_url_unknown = session.execute(
                select(func.count(Work.work_id))
                .select_from(Work)
                .join(WorkDateDerived)
                .where(WorkDateDerived.display_date_field == "unknown")
                .join(Edition, Edition.work_id == Work.work_id)
                .where(Edition.source_url.op("~*")(r"/\d{4}/"))
            ).scalar()

            return {
                "status": "completed",
                "works_scanned": len(works_with_urls),
                "works_recovered": recovered,
                "total_url_unknown_in_corpus": total_url_unknown,
                "run_id": str(run_id)
            }

    def phase2_author_lifespans(self) -> dict:
        """Phase 2: Resolve author lifespans from Wikidata."""
        print("\nResolving author lifespans...")

        with SessionLocal() as session:
            # Count authors missing lifespan data
            missing_birth = session.execute(
                select(func.count(Author.author_id))
                .where(Author.birth_year.is_(None))
            ).scalar()

            missing_death = session.execute(
                select(func.count(Author.author_id))
                .where(Author.death_year.is_(None))
            ).scalar()

            print(f"  Authors missing birth year: {missing_birth}")
            print(f"  Authors missing death year: {missing_death}")

            # This phase would call the existing CLI command
            return {
                "status": "requires_cli_execution",
                "command": "grundrisse-ingest resolve-author-lifespans --only-missing --limit 1500",
                "missing_birth": missing_birth,
                "missing_death": missing_death
            }

    def phase3_external_enrichment(self) -> dict:
        """Phase 3: External enrichment via GLM-4.7 and APIs."""
        print("\nExternal enrichment with GLM-4.7...")

        with SessionLocal() as session:
            # Count works still unknown after Phase 1
            still_unknown = session.execute(
                select(func.count(Work.work_id))
                .join(WorkDateDerived)
                .where(WorkDateDerived.display_date_field == "unknown")
            ).scalar()

            # Count works without external evidence
            no_external = session.execute(
                select(func.count(Work.work_id))
                .outerjoin(WorkMetadataEvidence)
                .where(WorkMetadataEvidence.evidence_id.is_(None))
            ).scalar()

            print(f"  Works still unknown: {still_unknown}")
            print(f"  Works without external evidence: {no_external}")

            return {
                "status": "requires_llm_execution",
                "script": "scripts/phase3_llm_enrichment.py",
                "still_unknown": still_unknown,
                "no_external_evidence": no_external,
                "estimated_llm_calls": no_external,
                "api_key_required": "GRUNDRISSE_ZAI_API_KEY"
            }

    def phase4_derivation_qa(self) -> dict:
        """Phase 4: Re-derive all dates and run QA."""
        print("\nRe-deriving dates with new evidence...")

        return {
            "status": "requires_cli_execution",
            "commands": [
                "grundrisse-ingest derive-work-dates --force --limit 20000",
                "python scripts/phase4_validate_corpus.py"
            ]
        }

    def phase5_uncertainty_annotation(self) -> dict:
        """Phase 5: Annotate remaining uncertain works."""
        print("\nAnnotating uncertain works...")

        with SessionLocal() as session:
            # Count remaining unknown works
            remaining_unknown = session.execute(
                select(func.count(Work.work_id))
                .join(WorkDateDerived)
                .where(WorkDateDerived.display_date_field == "unknown")
            ).scalar()

            return {
                "status": "pending_phase4_completion",
                "expected_remaining": min(150, remaining_unknown),
                "action": "Manually review and annotate uncertainty_reason"
            }

    def _extract_full_date_from_url(self, url: str) -> dict | None:
        """Extract date with full precision from URL."""
        if not url:
            return None

        # /YYYY/MM/DD.htm
        m = re.search(r'/(\d{4})/(\d{2})/(\d{2})(?:\.htm|\.html|/)', url)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1500 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return {"year": year, "month": month, "day": day, "precision": "day"}

        # /YYYY/MM/
        m = re.search(r'/(\d{4})/(\d{2})(?:\.htm|\.html|/)', url)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            if 1500 <= year <= 2030 and 1 <= month <= 12:
                return {"year": year, "month": month, "precision": "month"}

        # /YYYY/
        m = re.search(r'/(\d{4})(?:\.htm|\.html|/)', url)
        if m:
            year = int(m.group(1))
            if 1500 <= year <= 2030:
                return {"year": year, "precision": "year"}

        return None

    def _print_summary(self):
        """Print final summary."""
        print("\n" + "="*80)
        print("PIPELINE SUMMARY")
        print("="*80)

        for phase_key, result in self.results.get("phases", {}).items():
            status = result.get("status", "unknown")
            print(f"  {phase_key.upper()}: {status}")

        print("\nRecommendations:")
        print("  1. Review Phase 0 fixes and apply manually")
        print("  2. Run Phase 1 (URL recovery) - high impact")
        print("  3. Configure GLM-4.7 API key for Phase 3")
        print("  4. Run validation after Phase 4")

    def _save_results(self):
        """Save results to file."""
        out_path = Path("/mnt/c/Users/Datision/Documents/grundrisse/metadata_completion_results.json")
        out_path.write_text(json.dumps(self.results, indent=2, default=str))
        print(f"\nResults saved to: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Master Metadata Completion Pipeline")
    parser.add_argument("--phase", type=str, default="all",
                        help="Phase to run: 0-5, or 'all'")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to database")
    parser.add_argument("--skip", type=str, default="",
                        help="Comma-separated phases to skip")

    args = parser.parse_args()

    pipeline = MetadataCompletionPipeline(dry_run=args.dry_run)

    skip_phases = [int(p) for p in args.skip.split(",") if p.strip()] if args.skip else []

    if args.phase.lower() == "all":
        results = pipeline.run_all_phases(skip=skip_phases)
    elif args.phase.isdigit():
        phase = int(args.phase)
        results = pipeline.run_phase(phase)
        print(json.dumps(results, indent=2, default=str))
    else:
        # Handle range like "1-3"
        if "-" in args.phase:
            start, end = map(int, args.phase.split("-"))
            for phase in range(start, end + 1):
                if phase not in skip_phases:
                    pipeline.run_phase(phase)
            pipeline._print_summary()
        else:
            parser.error(f"Invalid phase: {args.phase}")


if __name__ == "__main__":
    main()
