# Task Tracker — Blast Radius Code Analyzer

> Status legend: `[ ]` Not started · `[~]` In progress · `[x]` Done · `[!]` Blocked

---

## Phase 1 — Environment Setup
**Goal:** Working Python environment connected to CGC's live FalkorDB instance.
**Estimate:** 30 min

- [ ] **1.1** Create `pyproject.toml` with pinned dependencies
- [ ] **1.2** Create `.env.example` with all required env vars documented
- [ ] **1.3** Verify `tree-sitter-language-pack==0.6.0` installs cleanly (v1.x breaks CGC)
- [ ] **1.4** Run `cgc index` on a target repo and confirm graph is populated
- [ ] **1.5** Write a smoke test that connects to FalkorDB and counts Function nodes

---

## Phase 2 — Graph Client
**Goal:** Clean Python wrapper over FalkorDB with all blast-radius Cypher queries.
**Estimate:** 1.5 hours
**File:** `src/blast_radius/graph.py`

- [ ] **2.1** Implement `FunctionNode` and `BlastRadiusResult` dataclasses
- [ ] **2.2** Implement `CodeGraph.__init__` — connect via Unix socket
- [ ] **2.3** Implement `find_function_by_name(name: str) -> FunctionNode | None`
- [ ] **2.4** Implement `find_function_by_line(file_path: str, line: int) -> FunctionNode | None`
- [ ] **2.5** Implement `get_blast_radius(fn_names: list[str]) -> BlastRadiusResult`
  - [ ] Deduplicated affected function set (query e)
  - [ ] Entry points — callers with nothing above them (query d)
  - [ ] Call chains for human-readable output (query c)
- [ ] **2.6** Add FalkorDB health check on startup
- [ ] **2.7** Write unit tests against the live graph

---

## Phase 3 — Git Diff Resolver
**Goal:** Map `git diff` output to `FunctionNode` objects via graph lookup.
**Estimate:** 2 hours
**Files:** `src/blast_radius/git_diff.py`, `src/blast_radius/resolver.py`

- [ ] **3.1** Implement `ChangedRange` dataclass
- [ ] **3.2** Implement `get_changed_ranges(repo_path: str) -> list[ChangedRange]`
  - [ ] Parse `@@ -a,b +c,d @@` hunk headers
  - [ ] Expand ranges to individual line numbers
  - [ ] Handle new files (no `-` side)
  - [ ] Handle renamed files via `--find-renames`
- [ ] **3.3** Implement `resolve_to_functions(changed_ranges, graph) -> list[FunctionNode]`
  - [ ] Deduplicate lines before querying
  - [ ] Fuzzy fallback: widen to ±3 lines if exact match returns nothing
  - [ ] Log when fuzzy matching fires
- [ ] **3.4** Test with a real staged change in a known repo

---

## Phase 4 — Agentic Test Synthesizer
**Goal:** Blast radius subgraph → Gemini → runnable pytest code → executed.
**Estimate:** 2.5 hours
**Files:** `src/blast_radius/synthesizer.py`, `src/blast_radius/runner.py`

- [ ] **4.1** Implement `build_context(result: BlastRadiusResult) -> str`
  - [ ] Ground zero section
  - [ ] Affected functions section
  - [ ] Entry points section
  - [ ] Call chains section
  - [ ] Cap affected functions to top 20 by `cyclomatic_complexity`
- [ ] **4.2** Write `SYSTEM_PROMPT` and `USER_TEMPLATE`
- [ ] **4.3** Implement `synthesize_tests(context: str) -> str` via Vertex AI Gemini
- [ ] **4.4** Strip markdown fences from Gemini output
- [ ] **4.5** Validate generated code with `ast.parse()` before writing to disk
- [ ] **4.6** Implement `write_and_run(test_code: str, repo_path: str) -> dict`
  - [ ] Write to `tests/test_blast_radius.py`
  - [ ] Run `pytest -v --tb=short --json-report`
  - [ ] Parse and return pass/fail counts
- [ ] **4.7** Test with a hardcoded `BlastRadiusResult` to validate Gemini output quality

---

## Phase 5 — Interaction Data Loop
**Goal:** Every run writes a training record to SQLite.
**Estimate:** 1 hour
**File:** `src/blast_radius/telemetry.py`

- [ ] **5.1** Define SQLite schema (`interactions` table)
- [ ] **5.2** Implement `TelemetryLogger.__init__` with auto schema creation
- [ ] **5.3** Implement `TelemetryLogger.log(...)` — write a run record
- [ ] **5.4** Implement `TelemetryLogger.mark_edited(id, final_code)` — flag human edits
- [ ] **5.5** Add `data/interactions.db` to `.gitignore`
- [ ] **5.6** Write tests for schema creation and round-trip logging

---

## Phase 6 — CLI Entrypoint
**Goal:** One command wires the entire pipeline end-to-end.
**Estimate:** 30 min
**File:** `src/blast_radius/__main__.py`

- [ ] **6.1** Implement `analyze` command with `typer`
- [ ] **6.2** Wire: diff → resolve → blast radius → synthesize → run → log
- [ ] **6.3** Implement `--dry-run` flag (stops after printing blast radius)
- [ ] **6.4** Add clear error messages for missing env vars and socket not found
- [ ] **6.5** End-to-end test: real change in target repo → interactions.db row written

---

## Phase 7 — Demo & Documentation
**Goal:** Anyone can clone and run the demo in under 10 minutes.
**Estimate:** 1 hour

- [ ] **7.1** Write `scripts/demo.sh` end-to-end demo runner
- [ ] **7.2** Verify README quickstart works on a fresh clone
- [ ] **7.3** Record a short demo (optional)

---

## Backlog — Post-MVP

- [ ] VS Code extension: show blast radius inline on file save
- [ ] CI/CD PR comment bot: post affected subgraph + generated tests as PR comment
- [ ] Fine-tuned model: after 500+ interactions, distill dataset into a smaller model
- [ ] Multi-repo graph support: cross-repo `CALLS` edge traversal
- [ ] KùzuDB backend: swap connection string in `.env`, keep same Cypher queries
