# Blast Radius

**Blast Radius** is a developer tool that answers the question: *"I just changed this function — what else could break?"*

It uses a live code graph (via [CodeGraphContext](https://github.com/CodeGraphContext/cgc)) to traverse the call chain upstream from any changed function, then sends that subgraph to Gemini to automatically synthesize and run targeted pytest tests against every affected entry point.

---

## How It Works

```
git diff --unified=0 HEAD
        │
        ▼
  ChangedRange(file, lines)
        │
        ▼   FalkorDB Cypher: line_number ≤ L ≤ end_line
  FunctionNode  ← ground zero
        │
        ▼   MATCH (caller)-[:CALLS*1..10]->(changed)
  BlastRadiusResult
   ├── affected_functions  (deduplicated upstream set)
   ├── entry_points        (API surface — callers with nothing above them)
   └── call_chains         (human-readable traversal paths)
        │
        ▼   Gemini prompt: subgraph source + call chains
  Generated pytest file
        │
        ▼   pytest -v --tb=short
  Pass / fail counts  →  interactions.db  (training data flywheel)
```

The entire blast-radius traversal is a single Cypher query — no custom BFS code required. The `source` field is stored on every `Function` node in FalkorDB, so context assembly requires zero filesystem reads.

---

## Prerequisites

- Python 3.10+
- [CodeGraphContext](https://github.com/CodeGraphContext/cgc) installed and `cgc` in your PATH
- A running FalkorDB instance (CGC manages this automatically via Unix socket)
- A Google Cloud project with Vertex AI enabled

---

## Setup

**1. Clone and create a virtual environment**

```bash
git clone https://github.com/dhirendrachoudhary/Seismic.git
cd Seismic
python -m venv .venv && source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -e .
# Critical: v1.x of tree-sitter-language-pack breaks CGC's import
pip install tree-sitter-language-pack==0.6.0
```

**3. Configure environment**

```bash
cp .env.example .env
# Edit .env with your FalkorDB socket path and GCP project
```

**4. Index your target repository**

```bash
cgc index /path/to/your/repo
# Verify the graph is populated:
cgc analyze callers <any_function_name>
```

---

## Usage

```bash
# Full pipeline: diff → blast radius → synthesize tests → run tests
python -m blast_radius /path/to/your/repo

# Print blast radius only, no test generation
python -m blast_radius /path/to/your/repo --dry-run
```

**Example output:**
```
Found 2 changed file(s)
Ground zero: ['calculate_discount', 'apply_coupon']
Blast radius: 7 function(s) affected
  process_order → apply_coupon → calculate_discount
  checkout → process_order → apply_coupon → calculate_discount
  api_checkout → checkout → process_order → apply_coupon
Tests: 5 passed, 1 failed
```

Generated tests are written to `tests/test_blast_radius.py` in your target repo.

---

## Project Structure

```
src/blast_radius/
├── graph.py        # FalkorDB client + Cypher queries
├── git_diff.py     # git diff parser → ChangedRange objects
├── resolver.py     # line ranges → FunctionNode via graph lookup
├── synthesizer.py  # Gemini prompt builder + test code generator
├── runner.py       # writes test file, runs pytest, captures results
├── telemetry.py    # SQLite logger — every run stored as a training record
└── __main__.py     # CLI entrypoint (typer)

docs/
├── build-plan.md   # detailed implementation plan with Cypher queries
└── tasks.md        # phase-by-phase task tracker

data/
└── interactions.db # SQLite — generated at runtime, gitignored
```

---

## Graph Schema

Blast Radius queries the graph written by `cgc index`. The schema used:

| Node | Key Properties |
|---|---|
| `Function` | `name`, `source`, `line_number`, `end_line`, `cyclomatic_complexity` |
| `File` | `path` |
| `Class` | `name` |

| Edge | Key Properties |
|---|---|
| `CALLS` | `line_number`, `full_call_name` |
| `CONTAINS` | — |

The core traversal query:
```cypher
MATCH p=(entry:Function)-[:CALLS*1..10]->(changed:Function {name: $fn_name})
WHERE NOT ()-[:CALLS]->(entry)
RETURN [n IN nodes(p) | n.name] AS call_chain
```

---

## Interaction Logging

Every pipeline run is logged to `data/interactions.db`:

| Column | Purpose |
|---|---|
| `prompt` | Full subgraph context sent to Gemini |
| `generated` | Raw Gemini output |
| `passed` / `failed` | pytest result counts |
| `edited` | 1 if a developer manually corrected the output |
| `final_code` | Post-edit code (used as the ground-truth label) |

After ~500 runs, this dataset is sufficient to fine-tune a smaller model on your codebase's specific fixture conventions and mock patterns.

---

## Environment Variables

| Variable | Description |
|---|---|
| `FALKORDB_SOCKET` | Path to the FalkorDB Unix socket (created by `cgc`) |
| `CGC_GRAPH_NAME` | Graph name inside FalkorDB (default: `codegraph`) |
| `GEMINI_PROJECT` | GCP project ID for Vertex AI |
| `GEMINI_LOCATION` | GCP region (e.g. `us-central1`) |

---

## Development Roadmap

- [x] Project scaffold and documentation
- [ ] Phase 2: Graph client (`graph.py`)
- [ ] Phase 3: Git diff resolver (`git_diff.py` + `resolver.py`)
- [ ] Phase 4: Test synthesizer + runner (`synthesizer.py` + `runner.py`)
- [ ] Phase 5: Telemetry loop (`telemetry.py`)
- [ ] Phase 6: CLI entrypoint (`__main__.py`)
- [ ] Phase 7: Demo script and end-to-end validation
- [ ] VS Code extension
- [ ] CI/CD PR comment bot
- [ ] Fine-tuned model distillation

See [`docs/tasks.md`](docs/tasks.md) for the detailed task tracker.
