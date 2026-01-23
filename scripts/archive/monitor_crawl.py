#!/usr/bin/env python3
"""Monitor crawl progress in real-time."""

import os
import sys
import time
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "ingest_service", "src"))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from grundrisse_core.db.models import CrawlRun, UrlCatalogEntry, ClassificationRun
from grundrisse_core.settings import settings


def format_duration(seconds):
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def monitor_crawl_runs():
    """Monitor active crawl runs."""
    engine = create_engine(settings.database_url)

    print("=" * 80)
    print("📊 CRAWL PROGRESS MONITOR")
    print("=" * 80)
    print("Press Ctrl+C to stop monitoring")
    print("")

    try:
        while True:
            with Session(engine) as session:
                # Get recent crawl runs
                crawl_runs = session.execute(
                    select(CrawlRun)
                    .order_by(CrawlRun.started_at.desc())
                    .limit(3)
                ).scalars().all()

                if not crawl_runs:
                    print("No crawl runs found.")
                    time.sleep(5)
                    continue

                # Clear screen (works on Unix-like systems)
                print("\033[H\033[J", end="")

                print(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("")

                for crawl_run in crawl_runs:
                    # Calculate duration
                    if crawl_run.finished_at:
                        duration = (crawl_run.finished_at - crawl_run.started_at).total_seconds()
                        status_emoji = "✅" if crawl_run.status == "completed" else "❌"
                    else:
                        duration = (datetime.utcnow() - crawl_run.started_at.replace(tzinfo=None)).total_seconds()
                        status_emoji = "🔄"

                    print(f"{status_emoji} Crawl Run: {crawl_run.crawl_run_id}")
                    print(f"   Status: {crawl_run.status}")
                    print(f"   Duration: {format_duration(duration)}")
                    print(f"   Started: {crawl_run.started_at}")

                    # Get URL statistics
                    url_stats = session.execute(
                        select(
                            UrlCatalogEntry.status,
                            func.count(UrlCatalogEntry.url_id).label("count"),
                            func.max(UrlCatalogEntry.depth).label("max_depth"),
                        )
                        .where(UrlCatalogEntry.crawl_run_id == crawl_run.crawl_run_id)
                        .group_by(UrlCatalogEntry.status)
                    ).all()

                    total_urls = sum(row.count for row in url_stats)
                    max_depth = max((row.max_depth for row in url_stats if row.max_depth), default=0)

                    print(f"   Total URLs: {total_urls:,}")
                    print(f"   Max Depth: {max_depth}")
                    print(f"   Breakdown:")
                    for row in url_stats:
                        pct = 100 * row.count / total_urls if total_urls > 0 else 0
                        print(f"      {row.status:10s}: {row.count:6,} ({pct:5.1f}%)")

                    # Check for classification runs
                    class_runs = session.execute(
                        select(ClassificationRun)
                        .where(ClassificationRun.crawl_run_id == crawl_run.crawl_run_id)
                        .order_by(ClassificationRun.started_at.desc())
                        .limit(1)
                    ).scalars().all()

                    if class_runs:
                        class_run = class_runs[0]
                        print(f"   Classification:")
                        print(f"      Status: {class_run.status}")
                        print(f"      URLs classified: {class_run.urls_classified:,}")
                        print(f"      Tokens used: {class_run.tokens_used:,} / {class_run.budget_tokens:,} "
                              f"({100*class_run.tokens_used/class_run.budget_tokens:.1f}%)")
                        if class_run.current_depth is not None:
                            print(f"      Current depth: {class_run.current_depth}")

                    print("")

                print("─" * 80)
                print("Refreshing in 5 seconds... (Ctrl+C to stop)")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


if __name__ == "__main__":
    monitor_crawl_runs()
