"""CLI entrypoint — index and analyze commands (typer)."""

import os
import typer
from pathlib import Path
from dotenv import load_dotenv

from blast_radius.indexer import PythonRepoIndexer
from blast_radius.git_diff import GitDiffParser
from blast_radius.resolver import FunctionResolver
from blast_radius.graph import CodeGraph

app = typer.Typer()


@app.command()
def index(repo: str = typer.Argument(..., help="Path to Python repository to index")):
    """Parse repository and build the SQLite call graph.

    Example:
        blast-radius index /path/to/your/repo
    """
    load_dotenv()
    db_path = os.getenv("BLAST_RADIUS_DB", "data/blast_radius.db")

    try:
        indexer = PythonRepoIndexer(repo, db_path)
        indexer.run()
    except KeyboardInterrupt:
        print("\n⚠️  Indexing cancelled by user")
        raise typer.Exit(1)
    except Exception as e:
        print(f"❌ Error during indexing: {e}")
        raise typer.Exit(1)


@app.command()
def analyze(
    repo: str = typer.Argument(..., help="Path to Python repository"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print blast radius without generating tests"),
):
    """Run full pipeline: analyze changes → generate tests → run tests.

    Example:
        blast-radius analyze /path/to/your/repo
        blast-radius analyze /path/to/your/repo --dry-run
    """
    load_dotenv()
    db_path = os.getenv("BLAST_RADIUS_DB", "data/blast_radius.db")

    try:
        # Phase 5: Parse git diff
        print(f"📂 Analyzing repository: {repo}")
        print("📋 Phase 5: Parsing git diff...")

        diff_parser = GitDiffParser(repo)
        changed_ranges = diff_parser.get_changed_ranges()

        if not changed_ranges:
            print("✓ No changes detected")
            raise typer.Exit(0)

        print(f"✓ Found changes in {len(changed_ranges)} file(s)")

        # Phase 5: Resolve to functions
        print("🔍 Phase 5: Resolving changed functions...")

        graph = CodeGraph(db_path)
        resolver = FunctionResolver(graph)
        ground_zero = resolver.resolve_to_functions(changed_ranges)

        if not ground_zero:
            print("✓ No functions found in changed lines")
            graph.close()
            raise typer.Exit(0)

        print(f"✓ Found {len(ground_zero)} changed function(s)")
        for fn in ground_zero:
            print(f"  - {fn.name} ({fn.file_path}:{fn.line_start})")

        # Get blast radius
        print("⚡ Computing blast radius...")
        ground_zero_names = [fn.name for fn in ground_zero]
        result = graph.get_blast_radius(ground_zero_names)

        print(f"✓ Blast radius: {len(result.affected_functions)} function(s)")
        print(f"✓ Entry points: {len(result.entry_points)} function(s)")
        print(f"✓ Call chains: {len(result.call_chains)} chain(s)")

        if result.call_chains:
            print("\nCall chains:")
            for chain in result.call_chains[:10]:
                print(f"  {' → '.join(chain)}")
            if len(result.call_chains) > 10:
                print(f"  ... and {len(result.call_chains) - 10} more")

        graph.close()

        if dry_run:
            print("\n(Dry run: stopping here. Remove --dry-run to generate and run tests.)")
            raise typer.Exit(0)

        # TODO: Phase 6 — generate and run tests
        print("\n❌ Test generation not yet implemented (Phase 6)")
        raise typer.Exit(1)

    except KeyboardInterrupt:
        print("\n⚠️  Analysis cancelled by user")
        raise typer.Exit(1)
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
