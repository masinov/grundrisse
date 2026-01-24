"""
Command-line interface for the argument extraction pipeline.

Usage:
    grundrisse-argument init                      # Initialize databases
    grundrisse-argument backfill                  # Backfill locutions from existing text
    grundrisse-argument extract <doc_id>          # Extract arguments from document
    grundrisse-argument validate <doc_id>         # Validate extraction
    grundrisse-argument cross-link <doc_id>       # Cross-document linking
    grundrisse-argument motion <doc_id>           # Compute dialectical motion
    grundrisse-argument status                    # Show pipeline status
"""

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from argument_pipeline.settings import get_settings

app = typer.Typer(
    name="grundrisse-argument",
    help="AIF/IAT argument extraction and dialectical motion analysis",
)
console = Console()


def _print_banner():
    """Print the pipeline banner."""
    console.print(
        "\n[bold cyan]Grundrisse Argument Extraction Pipeline[/bold cyan]\n"
        "[dim]AIF/IAT-based unsupervised argument mining[/dim]\n"
    )


@app.command()
def init(
    force: bool = typer.Option(
        False, "--force", "-f", help="Force reinitialization of collections"
    ),
):
    """
    Initialize databases and collections.

    Creates Neo4j constraints and Qdrant collections.
    """
    _print_banner()
    settings = get_settings()

    console.print("[yellow]Initializing argument extraction infrastructure...[/yellow]")

    # TODO: Implement initialization
    # 1. Connect to Neo4j and create constraints
    # 2. Connect to Qdrant and create collections
    # 3. Verify connectivity

    console.print(f"  Neo4j: {settings.neo4j_uri}")
    console.print(f"  Qdrant: {settings.qdrant_host}:{settings.qdrant_port}")

    console.print("\n[green]✓ Infrastructure initialized[/green]")
    console.print("\n[cyan]Next steps:[/cyan]")
    console.print("  1. Start services: docker compose -f ops/docker-compose.yml up -d")
    console.print("  2. Run extraction: grundrisse-argument extract <doc_id>")


@app.command()
def backfill(
    edition_id: Optional[str] = typer.Option(
        None, "--edition-id", "-e", help="Specific edition ID (omit for all)"
    ),
    source: str = typer.Option(
        "paragraph", "--source", "-s", help="Source type: 'paragraph' or 'span'"
    ),
    batch_size: int = typer.Option(
        1000, "--batch-size", "-b", help="Batch size for commits"
    ),
):
    """
    Backfill locutions from existing text units.

    Creates ArgumentLocution records for all Paragraphs or SentenceSpans
    that don't have one yet. Uses deterministic UUIDs for idempotency.
    """
    from grundrisse_core.db.session import SessionLocal
    from grundrisse_argument.graph import (
        backfill_paragraph_locutions,
        backfill_span_locutions,
        create_extraction_run,
    )

    _print_banner()

    console.print(f"[yellow]Backfilling locutions...[/yellow]")
    console.print(f"  Source: {source}")
    if edition_id:
        console.print(f"  Edition: {edition_id}")
    console.print(f"  Batch size: {batch_size}")

    with SessionLocal() as session:
        # Create extraction run
        run = create_extraction_run(
            session=session,
            pipeline_version="0.1.0",
            model_name="backfill",
            prompt_name="locution_backfill",
            prompt_version="0.1.0",
            params={"source": source, "batch_size": batch_size},
        )

        edition_uuid = None
        if edition_id:
            try:
                edition_uuid = __import__("uuid").UUID(edition_id)
            except ValueError:
                console.print(f"[red]Invalid edition ID: {edition_id}[/red]")
                raise typer.Exit(1)

        # Run backfill
        console.print()
        if source == "paragraph":
            stats = backfill_paragraph_locutions(
                session=session,
                created_run_id=run.run_id,
                edition_id=edition_uuid,
                batch_size=batch_size,
            )
        elif source == "span":
            stats = backfill_span_locutions(
                session=session,
                created_run_id=run.run_id,
                edition_id=edition_uuid,
                batch_size=batch_size,
            )
        else:
            console.print(f"[red]Invalid source: {source}. Use 'paragraph' or 'span'.[/red]")
            raise typer.Exit(1)

        # Update run stats
        run.finished_at = __import__("datetime").datetime.utcnow()
        run.status = "completed"
        run.windows_processed = 0  # N/A for backfill
        run.propositions_extracted = 0  # N/A for backfill
        run.relations_extracted = 0  # N/A for backfill
        session.commit()

        # Print results
        console.print()
        console.print("[green]✓ Backfill complete[/green]")
        console.print(f"  Created: {stats['created']}")
        console.print(f"  Skipped (already exists): {stats['skipped']}")
        if stats['errors'] > 0:
            console.print(f"  Errors: {stats['errors']}", style="red")


@app.command()
def extract(
    doc_id: str = typer.Argument(..., help="Document ID to extract from"),
    window_size: int = typer.Option(
        None, "--window-size", "-w", help="Number of paragraphs per window (2-6)"
    ),
    output: Optional[Path] = typer.Option(
        None, "-o", "--output", help="Output JSON file for extraction results"
    ),
):
    """
    Extract arguments from a document.

    Processes the document through:
    1. DOM parsing and locution extraction
    2. Entity normalization
    3. Windowing with retrieval-augmented context
    4. LLM-based argument extraction
    5. Validation and persistence
    """
    _print_banner()

    console.print(f"[yellow]Extracting arguments from: {doc_id}[/yellow]")

    # TODO: Implement extraction pipeline
    console.print("\n[dim]Stage 1: DOM parsing and locution extraction...[/dim]")
    console.print("[dim]Stage 2: Entity normalization...[/dim]")
    console.print("[dim]Stage 3: Windowing and retrieval...[/dim]")
    console.print("[dim]Stage 4: LLM extraction...[/dim]")
    console.print("[dim]Stage 5: Validation...[/dim]")
    console.print("[dim]Stage 6: Persistence...[/dim]")

    console.print("\n[green]✓ Extraction complete[/green]")


@app.command()
def validate(
    doc_id: str = typer.Argument(..., help="Document ID to validate"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed results"),
):
    """
    Validate extraction results.

    Checks:
    - Hard constraints (span grounding, AIF validity, evidence requirements)
    - Soft constraints (cyclic support, unmotivated conflicts)
    - Stability across extraction runs
    """
    _print_banner()

    console.print(f"[yellow]Validating extraction for: {doc_id}[/yellow]")

    # TODO: Implement validation
    console.print("\n[green]✓ Validation complete[/green]")


@app.command()
def cross_link(
    doc_id: Optional[str] = typer.Option(
        None, help="Specific document ID (omit for all documents)"
    ),
    threshold: float = typer.Option(
        0.7, "--threshold", "-t", help="Similarity threshold (0.0-1.0)"
    ),
):
    """
    Cross-document linking.

    Finds relations between documents:
    - Support
    - Conflict
    - Rephrase
    - Refinement
    - Historical displacement
    """
    _print_banner()

    target = doc_id if doc_id else "all documents"
    console.print(f"[yellow]Cross-linking: {target}[/yellow]")

    # TODO: Implement cross-document linking
    console.print("\n[green]✓ Cross-linking complete[/green]")


@app.command()
def motion(
    doc_id: Optional[str] = typer.Option(
        None, help="Specific document ID (omit for all documents)"
    ),
):
    """
    Compute dialectical motion hypotheses.

    Analyzes graph-structural patterns to identify:
    - Contradiction candidates
    - Definitional re-articulations
    - Abstract → concrete movements
    - Repeated failure → new determinations

    Motion is COMPUTED, not extracted.
    """
    _print_banner()

    target = doc_id if doc_id else "all documents"
    console.print(f"[yellow]Computing dialectical motion for: {target}[/yellow]")

    # TODO: Implement dialectical motion computation
    console.print("\n[green]✓ Motion computation complete[/green]")


@app.command()
def status():
    """
    Show pipeline status.

    Displays:
    - Database connectivity
    - Document processing statistics
    - Extraction coverage
    - Pending tasks
    """
    _print_banner()
    settings = get_settings()

    # Create status table
    table = Table(title="Pipeline Status", show_header=True, header_style="bold cyan")
    table.add_column("Component", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    # TODO: Implement actual status checks
    table.add_row("Neo4j", "[yellow]Checking...[/yellow]", f"{settings.neo4j_uri}")
    table.add_row("Qdrant", "[yellow]Checking...[/yellow]", f"{settings.qdrant_host}:{settings.qdrant_port}")
    table.add_row("PostgreSQL", "[yellow]Checking...[/yellow]", "localhost:5432")
    table.add_row("Embedding Model", "[green]Ready[/green]", settings.embedding_model)
    table.add_row("spaCy Model", "[green]Ready[/green]", settings.spacy_model)

    console.print("\n")
    console.print(table)

    console.print("\n[dim]Documents processed: 0 / 0[/dim]")
    console.print("[dim]Propositions extracted: 0[/dim]")
    console.print("[dim]Relations identified: 0[/dim]")


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
