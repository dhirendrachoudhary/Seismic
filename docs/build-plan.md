# Blast Radius Code Analyzer — Build Plan
> Based on live inspection of CodeGraphContext v0.3.1 + FalkorDB schema.
> Everything in this plan is grounded in what the database **actually stores**.

---

## What We Learned from the Live Inspection

Before writing a line of code, we ran `cgc index` on a real repo and queried FalkorDB directly. Key findings that reshape the original plan:

| Original Assumption | Ground Truth |
|---|---|
| CGC outputs a static JSON file | CGC writes to a live FalkorDB (Unix socket) or KùzuDB instance |
| You need a custom BFS engine in Python | Blast radius is a single Cypher `[:CALLS*1..10]` traversal |
| Source code must be read from the filesystem | `source` is stored on every `Function` node — no filesystem reads needed |
| `--db kuzu` flag exists | No such flag; database is configured via `cgc context` / `config.yaml` |
| Line metadata may be unreliable | `line_number` + `end_line` on Function nodes; `line_number` on CALLS edges — clean and usable |

### Actual Graph Schema

```
Nodes:    Repository, File, Function, Class, Variable, Parameter, Module
Edges:    CONTAINS, IMPORTS, HAS_PARAMETER, CALLS
Key props on Function: name, source, line_number, end_line, cyclomatic_complexity, decorators, docstring
Key props on CALLS:    line_number, full_call_name
```

### The Blast Radius Query (works today, zero custom code)

```cypher
MATCH p=(entry:Function)-[:CALLS*1..10]->(changed:Function {name: $fn_name})
WHERE NOT ()-[:CALLS]->(entry)
RETURN [n IN nodes(p) | n.name] AS call_chain
```

---

## Phase 1 — Environment Setup
**Goal:** Working Python environment connected to CGC's live FalkorDB instance.
**Time estimate: 30 min**

### 1.1 Install dependencies

```bash
pip install codegraphcontext falkordb google-cloud-aiplatform python-dotenv pytest
```

> **Note:** Pin `tree-sitter-language-pack==0.6.0` — v1.x installs as `_native` module and breaks CGC's import.

### 1.2 pyproject.toml

```toml
[project]
name = "blast-radius"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "falkordb",
    "google-cloud-aiplatform",
    "python-dotenv",
    "pytest",
    "tree-sitter-language-pack==0.6.0",
    "codegraphcontext",
]
```

### 1.3 .env

```env
FALKORDB_SOCKET=/root/.codegraphcontext/global/db/falkordb.sock
GEMINI_PROJECT=your-gcp-project
GEMINI_LOCATION=us-central1
CGC_GRAPH_NAME=codegraph
```

### 1.4 Index your target repo

```bash
cgc index /path/to/your/repo
```

Verify it worked:
```bash
cgc analyze callers <any_function_name>
```

### 1.5 Confirm FalkorDB socket exists

```python
import falkordb, os
client = falkordb.FalkorDB(unix_socket_path=os.getenv("FALKORDB_SOCKET"))
g = client.select_graph("codegraph")
print(g.query("MATCH (f:Function) RETURN count(f)").result_set)
```

---

## Phase 2 — Graph Client (`graph.py`)
**Goal:** A clean Python wrapper over FalkorDB with all blast-radius queries.
**Time estimate: 1.5 hours**

This replaces the entire custom BFS engine from the original plan. All traversal happens in Cypher.

### 2.1 Connection

```python
# src/blast_radius/graph.py
import falkordb, os
from dataclasses import dataclass

@dataclass
class FunctionNode:
    name: str
    source: str
    file_path: str
    line_start: int
    line_end: int
    complexity: int

class CodeGraph:
    def __init__(self):
        self.client = falkordb.FalkorDB(
            unix_socket_path=os.getenv("FALKORDB_SOCKET")
        )
        self.g = self.client.select_graph(os.getenv("CGC_GRAPH_NAME", "codegraph"))
```

### 2.2 Core queries to implement

**a) Find function by name**
```cypher
MATCH (f:Function {name: $name})
RETURN f.name, f.source, f.line_number, f.end_line
```

**b) Find function by file + line range** ← used by git diff resolver
```cypher
MATCH (file:File)-[:CONTAINS]->(f:Function)
WHERE file.path = $file_path
  AND f.line_number <= $changed_line
  AND f.end_line   >= $changed_line
RETURN f.name, f.source, f.line_number, f.end_line
```

**c) Blast radius — full upstream subgraph**
```cypher
MATCH p=(entry:Function)-[:CALLS*1..10]->(changed:Function {name: $fn_name})
RETURN 
  [n IN nodes(p) | n.name]       AS call_chain,
  [n IN nodes(p) | n.source]     AS sources,
  [n IN nodes(p) | n.line_number] AS lines
```

**d) Entry points only** (API routes / top-level functions with no callers)
```cypher
MATCH (entry:Function)-[:CALLS*1..10]->(changed:Function {name: $fn_name})
WHERE NOT ()-[:CALLS]->(entry)
RETURN DISTINCT entry.name, entry.source
```

**e) Deduplicated affected node set**
```cypher
MATCH (affected:Function)-[:CALLS*1..10]->(changed:Function {name: $fn_name})
RETURN DISTINCT affected.name, affected.source, affected.line_number, affected.end_line
ORDER BY affected.line_number
```

### 2.3 What to return from `get_blast_radius(fn_names: list[str])`

```python
@dataclass
class BlastRadiusResult:
    ground_zero: list[FunctionNode]       # the changed functions
    affected_functions: list[FunctionNode] # deduplicated upstream set
    entry_points: list[FunctionNode]       # API routes / top-level callers
    call_chains: list[list[str]]           # human-readable paths
```

> **Cycle guard:** FalkorDB's Cypher handles cycles in variable-length paths natively — it won't loop. No explicit visited-set needed.

---

## Phase 3 — Git Diff Resolver (`git_diff.py` + `resolver.py`)
**Goal:** Map `git diff` output to `FunctionNode` objects via the graph.
**Time estimate: 2 hours**

This is the most fragile phase. Budget time for edge cases.

### 3.1 Parse the diff (`git_diff.py`)

```python
import subprocess, re
from dataclasses import dataclass

@dataclass
class ChangedRange:
    file_path: str      # absolute path
    lines: list[int]    # every changed line number

def get_changed_ranges(repo_path: str) -> list[ChangedRange]:
    result = subprocess.run(
        ["git", "diff", "--unified=0", "HEAD"],
        cwd=repo_path, capture_output=True, text=True
    )
    return _parse_unified_diff(result.stdout, repo_path)
```

Parse the `@@ -a,b +c,d @@` hunk headers to extract every modified line number in the **new** file. Expand ranges: a hunk `+10,5` means lines 10, 11, 12, 13, 14 all changed.

**Edge cases to handle explicitly:**
- New files (no `-` side in the hunk) — treat all lines as changed
- Deleted functions — the node may still exist in the graph from the last index; re-run `cgc index` before diffing
- Renamed files — `git diff --find-renames` and update file path matching accordingly

### 3.2 Resolve lines to nodes (`resolver.py`)

```python
def resolve_to_functions(changed_ranges: list[ChangedRange], graph: CodeGraph) -> list[FunctionNode]:
    found = []
    for change in changed_ranges:
        for line in set(change.lines):   # deduplicate lines before querying
            node = graph.find_function_by_line(change.file_path, line)
            if node and node not in found:
                found.append(node)
    return found
```

> **Fuzzy fallback:** If exact line intersection returns nothing (e.g. the function signature was on a different line than the body), widen the search to ±3 lines. Log when fuzzy matching fires — it's a signal the index is stale and `cgc index` should be re-run.

### 3.3 Full pipeline

```
git diff --unified=0 HEAD
    │
    ▼
ChangedRange(file, [line_nums])
    │
    ▼  graph lookup: line_number <= L <= end_line
FunctionNode (ground zero)
    │
    ▼  Cypher: [:CALLS*1..10] upstream traversal
BlastRadiusResult
```

---

## Phase 4 — Agentic Test Synthesizer (`synthesizer.py` + `runner.py`)
**Goal:** Send the blast radius subgraph to Gemini, get runnable pytest code back, execute it.
**Time estimate: 2.5 hours**

### 4.1 Context assembly

Because `source` is stored on every `Function` node, context assembly requires **zero filesystem reads**:

```python
def build_context(result: BlastRadiusResult) -> str:
    parts = []
    parts.append("## Changed Functions (Ground Zero)")
    for fn in result.ground_zero:
        parts.append(f"### `{fn.name}` ({fn.file_path}:{fn.line_start})")
        parts.append(f"```python\n{fn.source}\n```")

    parts.append("## Affected Functions (Blast Radius)")
    for fn in result.affected_functions:
        parts.append(f"### `{fn.name}`")
        parts.append(f"```python\n{fn.source}\n```")

    parts.append("## Entry Points (API Surface)")
    for fn in result.entry_points:
        parts.append(f"- `{fn.name}`")

    parts.append("## Call Chains")
    for chain in result.call_chains:
        parts.append(f"- {' → '.join(chain)}")

    return "\n\n".join(parts)
```

### 4.2 Prompt architecture

```python
SYSTEM_PROMPT = """
You are a senior Python test engineer. You will receive:
1. A set of functions that were recently modified (Ground Zero)
2. All upstream functions impacted by those changes (Blast Radius)
3. The API entry points that surface those changes to callers
4. The exact call chains connecting them

Your task: write pytest functions targeting the ENTRY POINTS to verify
their contracts still hold after the changes. 

Rules:
- Use pytest only. No unittest.
- Mock all external I/O (database calls, HTTP, filesystem).
- One test function per distinct behavior / edge case.
- Include a test for the happy path AND at least one failure case per entry point.
- If you see existing fixtures or conftest patterns in the source, replicate them.
- Output ONLY valid Python code. No markdown fences, no explanation.
"""

USER_TEMPLATE = """
{context}

Generate pytest functions for the entry points listed above.
"""
```

### 4.3 Gemini integration

```python
import vertexai
from vertexai.generative_models import GenerativeModel

def synthesize_tests(context: str) -> str:
    vertexai.init(
        project=os.getenv("GEMINI_PROJECT"),
        location=os.getenv("GEMINI_LOCATION")
    )
    model = GenerativeModel("gemini-2.0-flash-001")
    response = model.generate_content([SYSTEM_PROMPT, USER_TEMPLATE.format(context=context)])
    return response.text.strip()
```

### 4.4 Test runner (`runner.py`)

```python
import subprocess, tempfile, pathlib

def write_and_run(test_code: str, repo_path: str) -> dict:
    test_file = pathlib.Path(repo_path) / "tests" / "test_blast_radius.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(test_code)

    result = subprocess.run(
        ["pytest", str(test_file), "-v", "--tb=short", "--json-report"],
        cwd=repo_path, capture_output=True, text=True
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "passed": result.stdout.count(" PASSED"),
        "failed": result.stdout.count(" FAILED"),
        "test_file": str(test_file),
    }
```

---

## Phase 5 — Interaction Data Loop (`telemetry.py`)
**Goal:** Every run writes a training record. This is the moat.
**Time estimate: 1 hour**

### 5.1 SQLite schema

```sql
CREATE TABLE interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    repo_path   TEXT    NOT NULL,
    ground_zero TEXT    NOT NULL,   -- JSON: list of changed function names
    prompt      TEXT    NOT NULL,   -- the full context string sent to Gemini
    generated   TEXT    NOT NULL,   -- raw Gemini output
    passed      INTEGER,            -- pytest pass count
    failed      INTEGER,            -- pytest fail count
    edited      INTEGER DEFAULT 0,  -- 1 if developer manually edited the output
    final_code  TEXT                -- post-edit code if developer modified it
);
```

### 5.2 Logger

```python
import sqlite3, json
from datetime import datetime

class TelemetryLogger:
    def __init__(self, db_path: str = "data/interactions.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def log(self, repo_path, ground_zero, prompt, generated, run_result):
        self.conn.execute("""
            INSERT INTO interactions
            (timestamp, repo_path, ground_zero, prompt, generated, passed, failed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            repo_path,
            json.dumps([f.name for f in ground_zero]),
            prompt,
            generated,
            run_result["passed"],
            run_result["failed"],
        ))
        self.conn.commit()

    def mark_edited(self, interaction_id: int, final_code: str):
        self.conn.execute(
            "UPDATE interactions SET edited=1, final_code=? WHERE id=?",
            (final_code, interaction_id)
        )
        self.conn.commit()
```

### 5.3 What this data becomes

Each row is a complete supervised fine-tuning example:
- **Input:** `prompt` (the subgraph context)
- **Output:** `final_code` if `edited=1`, else `generated`
- **Quality signal:** `passed / (passed + failed)` ratio

After ~500 runs on a real codebase, this dataset is sufficient to fine-tune a smaller model (e.g. Gemini Flash or a local Qwen/Llama variant) that understands the repo's specific patterns — fixture conventions, mock styles, domain objects.

---

## Phase 6 — CLI Entrypoint
**Goal:** One command to run the whole pipeline.
**Time estimate: 30 min**

```python
# src/blast_radius/__main__.py
import typer
from .git_diff import get_changed_ranges
from .graph import CodeGraph
from .resolver import resolve_to_functions
from .synthesizer import build_context, synthesize_tests
from .runner import write_and_run
from .telemetry import TelemetryLogger

app = typer.Typer()

@app.command()
def analyze(
    repo: str = typer.Argument(..., help="Path to the git repo"),
    dry_run: bool = typer.Option(False, help="Print blast radius without running tests"),
):
    graph = CodeGraph()
    logger = TelemetryLogger()

    changed = get_changed_ranges(repo)
    typer.echo(f"Found {len(changed)} changed file(s)")

    ground_zero = resolve_to_functions(changed, graph)
    typer.echo(f"Ground zero: {[f.name for f in ground_zero]}")

    result = graph.get_blast_radius([f.name for f in ground_zero])
    typer.echo(f"Blast radius: {len(result.affected_functions)} function(s) affected")
    for chain in result.call_chains:
        typer.echo(f"  {' → '.join(chain)}")

    if dry_run:
        return

    context = build_context(result)
    test_code = synthesize_tests(context)

    run_result = write_and_run(test_code, repo)
    typer.echo(f"Tests: {run_result['passed']} passed, {run_result['failed']} failed")

    logger.log(repo, ground_zero, context, test_code, run_result)

if __name__ == "__main__":
    app()
```

Run it:
```bash
python -m blast_radius /path/to/your/repo
python -m blast_radius /path/to/your/repo --dry-run
```

---

## Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| CGC index is stale when diff runs | High | Always re-run `cgc index` at pipeline start, or use `cgc watch` |
| Gemini generates non-runnable tests | Medium | Strip markdown fences before writing; validate with `ast.parse()` before pytest |
| FalkorDB socket not running | Medium | Add a health check on startup; surface a clear error message |
| `tree-sitter-language-pack` version conflict | High (already hit this) | Pin to `==0.6.0` in pyproject.toml |
| Cyclic call graphs causing infinite traversal | Low | FalkorDB Cypher handles this natively with variable-length path deduplication |
| Gemini context window overflow on large repos | Medium | Cap `affected_functions` to top 20 by cyclomatic complexity before building prompt |

---

## Future Extensions (Post-MVP)

- **VS Code extension:** Show blast radius inline as a hover/diagnostic when a file is saved
- **PR comment bot:** Run on CI, post the affected subgraph + generated tests as a PR comment
- **Fine-tuned model:** After 500+ interactions, distill the dataset into a smaller local model
- **Multi-repo graphs:** CGC supports multiple indexed repos; extend resolver to cross-repo CALLS edges
- **KùzuDB support:** CGC also supports KùzuDB — the Cypher queries are compatible; swap the connection string in `.env`
