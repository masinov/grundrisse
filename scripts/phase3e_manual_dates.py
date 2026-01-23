#!/usr/bin/env python3
"""
Phase 3e: Apply Research Dates from Online Investigation

Applies publication dates found through web research for the remaining
unknown works.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, func

sys.path.insert(0, str(Path(__file__).parent.parent / "packages" / "core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "ingest_service" / "src"))

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, WorkDateDerived, WorkMetadataRun, WorkMetadataEvidence
)

# Dates found through web research with sources
RESEARCHED_DATES = {
    # Albert Weisbord works
    "Taxes Explained": {"year": 1975, "confidence": 0.6, "note": "Written in 1970s, references GATT and Kennedy-era policies"},
    "THE LAWS OF MOVEMENT OF CAPITALISM": {"year": 1936, "confidence": 0.7, "note": "Cited in academic sources as 1936 pamphlet"},

    # Andy Blunden works (Hegel Discussion Group, 1997)
    "Dialectics & the Theory of Group Organisation": {"year": 1997, "confidence": 0.8, "note": "Hegel Discussion Group, 1997-1998"},
    "The Meaning of Reflection in Hegel's Logic": {"year": 1997, "confidence": 0.8, "note": "Part of Hegel's Logic series, 1997"},

    # Anton Makarenko works
    "Lectures to Parents": {"year": 1961, "confidence": 0.8, "note": "English translation publication, National Council NY"},
    "The Road to Life-volume 2": {"year": 1951, "confidence": 0.8, "note": "English translation by Foreign Languages Publishing House, Moscow"},

    # Eleanor Marx
    "An Enemy of Society": {"year": 1888, "confidence": 0.9, "note": "Eleanor Marx Aveling's translation of Ibsen, published 1888"},

    # Evald Ilyenkov
    "Logic and Dialectics": {"year": 1974, "confidence": 0.8, "note": "Chapter 3 of Dialectical Logic, written 1974, published 1977"},

    # Hegel works
    "Hegel's Lectures on Aesthetics": {"year": 1835, "confidence": 0.9, "note": "Posthumous publication, edited by H.G. Hotho"},
    "Outlines of Hegel's Phenomenology": {"year": 1997, "confidence": 0.6, "note": "Modern summary document, Hegel Discussion Group era"},
    "The German Constitution": {"year": 1802, "confidence": 0.8, "note": "Written 1798-1802, early unpublished work"},

    # Other authors
    "Hegel and Complexity": {"year": 2005, "confidence": 0.5, "note": "Jan Sarnovsky, circa 2005 based on author's active period"},
    "Analysis of the Phenomenology of Spirit": {"year": 1977, "confidence": 0.9, "note": "J.N. Findlay, published with A.V. Miller translation, Oxford 1977"},
    "Pampas y lanzas II": {"year": 2002, "confidence": 0.7, "note": "Liborio Justo, published 2002 by Badajo"},
    "God or Labor": {"year": 1871, "confidence": 0.7, "note": "Chapter from Bakunin's Writings, written during his 1870s period"},
    "Discussion on Essence": {"year": 1997, "confidence": 0.7, "note": "Mustafa Cemal, Hegel Discussion Group 1997-1998"},
    "If a grandmother makes a birthday": {"year": 1997, "confidence": 0.6, "note": "SPSM listserv discussion excerpt, Hegel Discussion Group era"},

    # Jorge Luis Cometti - no reliable dates found, using estimates
    "The Landscape of Theory": {"year": 2000, "confidence": 0.3, "note": "Jorge Luis Cometti, estimate based on context"},
    "La depresion en los aos 30": {"year": 2000, "confidence": 0.3, "note": "Jorge Luis Cometti, estimate based on context"},
}


def run_phase3e():
    """Apply manually researched dates."""
    print("="*80)
    print("PHASE 3E: APPLY RESEARCHED DATES FROM ONLINE INVESTIGATION")
    print("="*80)

    with SessionLocal() as session:
        run_id = uuid.uuid4()

        # Create run record
        run = WorkMetadataRun(
            run_id=run_id,
            pipeline_version="metadata_completion_v1",
            strategy="phase3e_manual_research",
            params={"source": "web_research_2025"},
            sources=["manual_web_research"],
            started_at=datetime.now(timezone.utc),
            status="started",
        )
        session.add(run)
        session.commit()

        updated = 0

        for title_pattern, info in RESEARCHED_DATES.items():
            # Find works by title pattern
            works = session.execute(
                select(Work.work_id, Work.title, Author.name_canonical)
                .select_from(Work)
                .join(Author)
                .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
                .where(Work.title.ilike(f"%{title_pattern}%"))
                .where(WorkDateDerived.display_date_field == "unknown")
            ).all()

            for work_id, title, author in works:
                # Add evidence
                evidence = WorkMetadataEvidence(
                    evidence_id=uuid.uuid4(),
                    run_id=run_id,
                    work_id=work_id,
                    source_name="web_research_manual",
                    source_locator=f"researched:{title_pattern}",
                    retrieved_at=datetime.now(timezone.utc),
                    extracted={
                        "year": info["year"],
                        "month": None,
                        "day": None,
                        "precision": "year",
                    },
                    score=info["confidence"],
                    raw_payload={
                        "research_note": info["note"],
                        "title_pattern": title_pattern,
                    },
                    notes=info["note"]
                )
                session.add(evidence)
                updated += 1
                print(f"  + {author}: {title[:50]}... → {info['year']} (conf: {info['confidence']})")

        session.commit()

        # Update run record
        run.works_scanned = len(RESEARCHED_DATES)
        run.works_updated = updated
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    print(f"\n{'='*80}")
    print("PHASE 3E COMPLETE")
    print(f"{'='*80}")
    print(f"Works updated: {updated}")

    return {"updated": updated}


if __name__ == "__main__":
    run_phase3e()
