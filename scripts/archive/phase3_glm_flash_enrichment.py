#!/usr/bin/env python3
"""
Phase 3: GLM-4.7-Flash External Enrichment

Research publication dates for remaining unknown works using GLM-4.7-Flash.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import openai
from sqlalchemy import select, func

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived, WorkMetadataRun, WorkMetadataEvidence
)

# Configuration from .env
ZAI_BASE_URL = os.environ.get("GRUNDRISSE_ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
ZAI_MODEL = "glm-4.7-flash"
ZAI_API_KEY = os.environ.get("GRUNDRISSE_ZAI_API_KEY")


class GLMFlashDateResearcher:
    """Use GLM-4.7-Flash to research publication dates."""

    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=ZAI_BASE_URL,
        )
        self.model = ZAI_MODEL
        self.run_id = None
        self.results = {"success": [], "failed": []}
        self.evidence_to_store = []  # Initialize the evidence storage list

    async def research_work_date(self, work_info: dict) -> dict:
        """Research the publication date for a single work."""

        work_id = work_info["work_id"]
        title = work_info["title"]
        author = work_info["author"]
        author_birth = work_info.get("author_birth")
        author_death = work_info.get("author_death")
        url = work_info.get("url")

        # Build research prompt
        author_context = f" ({author_birth}-{author_death})" if author_birth or author_death else ""

        prompt = f"""You are a research assistant for Marxist literature. Find the first publication date.

TITLE: {title}
AUTHOR: {author}{author_context}
URL: {url or "N/A"}

Rules:
- Return ORIGINAL publication date, not translation/collection dates
- Speeches: date given
- Letters: date written
- Classical texts: best scholarly estimate
- If uncertain: set confidence < 0.5 and explain

Respond ONLY with JSON:
{{
    "year": 1848,
    "month": null,
    "day": null,
    "precision": "year",
    "confidence": 0.8,
    "reasoning": "Brief explanation",
    "sources": ["marxists.org"]
}}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
                response_format={"type": "json_object"},
                timeout=60,
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)

            # Store evidence if we got a date
            if result.get("year") and result.get("confidence", 0) >= 0.3:
                self._store_evidence(work_id, result, url)

            self.results["success"].append({
                "work_id": work_id,
                "title": title,
                "author": author,
                "result": result
            })

            return {"status": "success", "result": result}

        except Exception as e:
            self.results["failed"].append({
                "work_id": work_id,
                "title": title,
                "error": str(e)
            })
            return {"status": "failed", "error": str(e)}

    def _store_evidence(self, work_id: str, research_result: dict, url: str | None):
        """Store research result - will be batch-committed later."""
        # Store in a list to commit in batch
        if not hasattr(self, 'evidence_to_store'):
            self.evidence_to_store = []

        self.evidence_to_store.append({
            "work_id": work_id,
            "source_name": "glm-4.7-flash_research",
            "source_locator": research_result.get("sources", ["LLM"])[0] if research_result.get("sources") else None,
            "extracted": {
                "year": research_result.get("year"),
                "month": research_result.get("month"),
                "day": research_result.get("day"),
                "precision": research_result.get("precision", "year"),
            },
            "score": research_result.get("confidence", 0.5),
            "raw_payload": {
                "reasoning": research_result.get("reasoning"),
                "sources": research_result.get("sources"),
                "model": ZAI_MODEL,
            },
            "notes": research_result.get("uncertainty"),
        })


async def run_phase3():
    """Run Phase 3: GLM-4.7-Flash enrichment."""

    print("="*80)
    print("PHASE 3: GLM-4.7-FLASH EXTERNAL ENRICHMENT")
    print("="*80)

    # Get unknown works
    with SessionLocal() as session:
        run_id = uuid.uuid4()

        # Create run record
        run = WorkMetadataRun(
            run_id=run_id,
            pipeline_version="metadata_completion_v1",
            strategy="phase3_glm_flash_enrichment",
            params={"model": ZAI_MODEL},
            sources=["glm-4.7-flash"],
            started_at=datetime.now(timezone.utc),
            status="started",
        )
        session.add(run)
        session.commit()

        # Get unknown works
        unknown_works = session.execute(
            select(
                Work.work_id,
                Work.title,
                Author.name_canonical,
                Author.birth_year,
                Author.death_year,
                func.array_agg(Edition.source_url.distinct()).label("urls")
            )
            .select_from(Work)
            .join(Author)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .group_by(Work.work_id, Work.title, Author.name_canonical, Author.birth_year, Author.death_year)
            .order_by(Author.name_canonical, Work.title)
        ).all()

        works_to_research = [
            {
                "work_id": str(w.work_id),
                "title": w.title,
                "author": w.name_canonical,
                "author_birth": w.birth_year,
                "author_death": w.death_year,
                "url": w.urls[0] if w.urls else None,
            }
            for w in unknown_works
        ]

        print(f"\nFound {len(works_to_research)} unknown works")
        print(f"Model: {ZAI_MODEL}")
        print(f"API: {ZAI_BASE_URL}")
        print(f"\nResearching...")

        researcher = GLMFlashDateResearcher(ZAI_API_KEY)
        researcher.run_id = run_id

        # Process in batches of 10 with concurrency of 5
        batch_size = 10
        concurrent = 5

        for i in range(0, len(works_to_research), batch_size):
            batch = works_to_research[i:i + batch_size]
            tasks = [researcher.research_work_date(w) for w in batch]
            await asyncio.gather(*tasks)

            success_count = len(researcher.results["success"])
            failed_count = len(researcher.results["failed"])
            total_done = success_count + failed_count

            print(f"  Progress: {total_done}/{len(works_to_research)} | Success: {success_count} | Failed: {failed_count}")

            # Batch commit evidence every 50 works
            if len(researcher.evidence_to_store) >= 50 or total_done == len(works_to_research):
                for ev in researcher.evidence_to_store:
                    evidence = WorkMetadataEvidence(
                        evidence_id=uuid.uuid4(),
                        run_id=run_id,
                        retrieved_at=datetime.now(timezone.utc),
                        **ev
                    )
                    session.add(evidence)
                session.commit()
                print(f"  Committed {len(researcher.evidence_to_store)} evidence rows")
                researcher.evidence_to_store = []

        # Final results
        success_count = len(researcher.results["success"])
        failed_count = len(researcher.results["failed"])

        # Update run record
        run.works_scanned = len(works_to_research)
        run.works_updated = success_count
        run.works_failed = failed_count
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    print(f"\n{'='*80}")
    print("PHASE 3 COMPLETE")
    print(f"{'='*80}")
    print(f"Total: {len(works_to_research)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")

    # Show some results
    if researcher.results["success"]:
        print(f"\nSample results:")
        for i, r in enumerate(researcher.results["success"][:10], 1):
            print(f"  {i}. {r['author']}: {r['title'][:50]}")
            print(f"     → {r['result'].get('year')} (confidence: {r['result'].get('confidence', 0)})")

    return {"success": success_count, "failed": failed_count}


if __name__ == "__main__":
    asyncio.run(run_phase3())
