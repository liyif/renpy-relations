# Benchmark methods and saved evidence

These experiments measure rule loading, queries, writes, and native fact snapshots in isolated processes. Begin with the [English summary of saved measurements](results/current/REPORT.md), then follow its raw-data links. The directory name `current` is an archive label: it does not establish that its runtime matches the code you are reading.

For the runtime's query modes and lifecycle contracts, see the [reference](../docs/reference.md). For setup and the SDK target, see [maintenance](../docs/maintaining.md). The [project introduction](../README.md) describes what the experiment is intended to investigate.

Current tooling measures `renpy_relations/runtime.py`; copied workers receive that core under the historical module filename. New source records include the core/compiler package files. Archived results retain their original single-file identities and measurements.

## Four experiment families

| Family and entry point | Workload and measured phases |
| --- | --- |
| Fact volume — `run.py` | Palace rules over generated characters. A seed worker measures empty initialization, public-interface ingestion, and an explicit snapshot. Fresh measurement workers restore that fixture, then measure cold `has`, warm `has` and `query`, snapshot, single and batched commits, the first read after each change, same-rule reload, and restore after edits. |
| Condition panel — `conditions.py`, using `rules.py` | Generated SQL and dependency metadata over 32 domains. Measures bundle load, ingestion, a first complete panel of condition checks, a second panel, and local/global/unrelated commits followed by another complete panel. Independent validation workers compare complete relations against a Python oracle through state changes. |
| Snapshots — `snapshots.py` | A simple Seed/Visible world populated with native SQL outside timing. Measures a full snapshot after an edit, unchanged snapshot reuse, ordinary commit, commit with a snapshot callback, and restore. Driver and process repeats are separate dimensions. |
| Long chains — `graph.py` | Generated SQL outputs form a dependency chain. Measures load and one final-output read, then checks that a removal invalidates the answer. These are single observations per length/backend, not repeated gameplay medians. |

The controlled suite also runs DuckDB condition **loading probes** at larger counts. These measure load, ingestion, and one selected `has` in cached mode with a 120-second task budget. They do not execute a complete panel or the mutation matrix. Generated condition and chain SQL bypass Logica compilation. Fact-volume records include a separate compiler timing; do not interpret a graph's `load` as compiler performance.

### Sizes, layouts, modes, and variants

Fact-volume `--sizes` counts **characters**, not all rows. For size N, the five fact relations contain N Member rows, 128 FactionAccess rows, ceil(N/10) Sponsor rows, ceil(N/3) Knows rows, and ceil(N/11) RewardClaimed rows. Thus 10,000, 100,000, and 1,000,000 characters produce 15,372, 152,553, and 1,524,372 fact rows. Derived row counts differ again: CanEnter alone contains 4N + ceil(N/10) rows. Read each record's `cardinalities` rather than treating its `size` as a database row count.

Condition `--conditions` counts requested condition checks. The generated bundle also contains **64 shared helper outputs**. `--ratios 1 10` expresses the approximate output-to-fact ratio: the implementation chooses ceil((conditions + 64)/ratio) fact rows. For example, 1,000 conditions generate 1,064 outputs and either 1,064 or 107 facts. `partitioned` uses one state relation per domain; `shared_table` keeps a domain column in one state relation. Invalidation operates at relation boundaries, so the shared-table layout makes a local edit touch dependencies beyond that row's domain.

All three modes are available: `cached` builds derived relations on demand, `materialized` rebuilds affected outputs during commits, and `live` evaluates views. Compare **commit plus the subsequent read/panel** when assessing an action; a small commit can defer work to the next query.

Condition tools offer `native` and a pinned SQLite `baseline` runtime. Historical sources come from the bundled baseline manifest and verified hashes. A `baseline_ref` field is configuration, not evidence of a comparison: the saved controlled suite ran only `native`. Snapshot tools can optionally compare a legacy runtime with `--baseline-ref`; the saved snapshot records have `legacy: false` throughout.

### What each metric means

`seconds` is wall time; `cpu_seconds` is process CPU time where recorded. Linux `rss_bytes` is resident memory at that checkpoint, while `peak_rss_bytes` is the process lifetime high-water mark. Missing memory fields are unavailable, not zero. Peak RSS is not incremental memory allocated by the named phase.

Cold reads are first reads after initialization or fixture restoration, not reads after clearing OS page caches. Warm reads follow earlier work in the same process. A panel's total wall time is the complete sequence of checks; its request median/p95 describe individual checks within that panel. A p95 request latency is not a p95 panel latency. Fact-volume JSON retains request samples; condition JSON records each panel's request statistics. Keep independent-process variation separate from within-process samples when aggregating.

Timing runs and validation runs serve different purposes. The condition matrix has three fresh timing workers and one complete validation worker per configuration. Fact-volume measurements use three workers per mode and one seed per size/backend. Snapshot records distinguish `process_repetitions` from sequential `repetitions` inside a process; the saved suite used three processes with one sequential sample each. Graphs and loading probes have one observation per configuration. Failed, timed-out, missing, and incomplete groups must remain visible; never fill them with zero or present successful subsets as a complete group.

Phases within a worker are sequential, not independently reset experiments. Fact-volume reads follow fixture restoration; a single edit remains present during the subsequent batch and reload, and only `restore_after_edits` returns to the initial fixture. Its measurement-worker phase named `snapshot` occurs before those edits and reuses the image retained by `restore_initial`; the seed worker's separate `snapshot` phase generates the changed world's image after ingestion. Do not read that measurement-worker snapshot time as full serialization cost.

Condition panels first read the seeded world, then a local edit disables domain 0's `v0`, then a global edit disables GlobalState, then an unrelated Note edit occurs with both prior changes still present. Independent validation workers follow the same sequence and additionally re-enable GlobalState while blocking `v0`. Snapshot workers add an untimed marker before full serialization, immediately measure image reuse, make an ordinary edit, restore the saved image into a second callback-bound world and make a history edit there, then restore the first world. If multiple sequential repetitions are requested, the restored snapshot markers accumulate across them. Later phases therefore inherit earlier state and warming; compare like phase sequences.

Fact and condition query workloads record `history_bound: false`: no snapshot receiver is installed, so ordinary commits do not pay the save-history publication cost. Snapshot `history_commit` binds a callback that accepts the latest native image and does not accumulate a retained rollback history. `snapshot_reused` measures the unchanged-image path; it is distinct from serializing a changed world. None of these experiments measures a full Ren’Py frame rate, retained rollback history, save archive cost, skewed game data, or performance across hardware.

## Read the saved suite honestly

The [suite record](results/current/results.json) reports eight completed tasks. Its 19 original [checksum entries](results/current/SHA256SUMS) match the preserved raw JSON/CSV files. These checks establish artifact integrity, not wider experimental coverage.

| Saved task | Actual completed coverage |
| --- | --- |
| [conditions-sqlite](results/current/conditions-sqlite/results.json) | 1,000/3,000/10,000 conditions × ratios 1/10 × both layouts × three modes; 108 timing runs and 36 validations. |
| [conditions-duckdb](results/current/conditions-duckdb/results.json) | 1,000 conditions, ratio 10, partitioned layout, three modes; 9 timing runs and 3 validations. |
| [facts-sqlite](results/current/facts-sqlite/results.json) | 10,000/100,000/1,000,000 characters, three modes, three repeats; 27 measurement workers and 3 seeds. |
| [facts-duckdb](results/current/facts-duckdb/results.json) | 10,000 characters, three modes, three repeats; 9 measurement workers and 1 seed. |
| [snapshots](results/current/snapshots/results.json) | 10,000/100,000/1,000,000 Seed rows, pysqlite3 and DuckDB, three processes each; 18 records. |
| [graph](results/current/graph/results.json) | Chain lengths 128/512/1,050, both backends; 6 single observations. |
| [duckdb-load-3000](results/current/duckdb-load-3000/results.json), [duckdb-load-10000](results/current/duckdb-load-10000/results.json) | One cached, partitioned, ratio-10 loading probe at each count. |

Each task's `measured_source` is authoritative for that workload; the suite's `measured_source.sha256` is their union. The recorded checkout was dirty at commit `c96c103578e646c5617483f482a78ff161a77506`. Its measured runtime hash is `400c16af67966c93403461ba1fb4f73a08f2167a8337067d44585ffdf80d7bdd`; its measured lockfile hash is `270ae36251a36cf873b4a04a28770234191e8037bc60ed8602b3f8619bdb000d`. Both differ from this source copy. The compiler and benchmark scripts matched their recorded hashes when this guide was authored. The English summary derives values from those existing records; it is not a fresh benchmark of the copy.

Keep `report_generation_source` distinct from `measured_source`. Re-rendering a report under a newer runtime or reporter cannot make old numbers measurements of that newer code. Child result hashes, bundle/fixture hashes, per-task execution records, driver versions, and environment fields provide the next level of attribution. A dirty commit alone cannot recover the exact measured tree.

## Reproduce into a new directory

From the source root, install locked development dependencies and stage Palace with both drivers. Set paths to the pinned Linux x86_64 / Python 3.12 SDK and fresh output locations:

```sh
uv sync --locked --extra duckdb --group renpy-linux
SDK=/path/to/renpy-8.5.3-sdk
GAME=/tmp/relations-benchmark-game
uv run --locked --extra duckdb python -m tools.prepare_game \
  --game examples/palace --out "$GAME" --backend duckdb --sdk "$SDK"
uv run --locked --extra duckdb python benchmarks/suite.py --profile controlled --smoke \
  --python "$SDK/lib/py3-linux-x86_64/python" \
  --packages "$GAME/game/python-packages" --out /tmp/relations-benchmark-smoke
```

Smoke reduces characters/facts and condition counts and uses one timing repeat. It verifies the pipeline and produces fresh evidence for the code actually executed; it is not a substitute for the saved workload. The worker imports this checkout's runtime; `--packages` provides the staged dependencies. Omitting both worker arguments uses the local interpreter and its dependencies, which is a different measurement environment.

For a deliberate larger experiment, choose one of these profiles and a fresh output path:

```sh
uv run --locked --extra duckdb python benchmarks/suite.py --profile controlled \
  --python "$SDK/lib/py3-linux-x86_64/python" \
  --packages "$GAME/game/python-packages" --out /tmp/relations-benchmark-controlled
uv run --locked --extra duckdb python benchmarks/suite.py --profile full \
  --python "$SDK/lib/py3-linux-x86_64/python" \
  --packages "$GAME/game/python-packages" --out /tmp/relations-benchmark-full
```

`controlled` reproduces the asymmetric scope above. `full` requests both backends across the complete condition and fact-volume matrices, plus snapshots and chains; it does not include the separate loading probes. Full runs can be expensive and can hit worker budgets. They are unnecessary for validating prose. Individual family scripts expose smaller scopes through `--help`; preserve their selected parameters with any published results.

## Render reports without changing the archive

The checked-in English summary is an independently derived reading aid. The existing report generators emit Chinese reports. Rendering is a write operation: `report.py` writes a root REPORT.md and replaces SHA256SUMS; suite `--collect` also revalidates tasks and writes suite metadata and reports. Use a copied result tree, never the preserved archive:

```sh
REPORT_COPY=$(mktemp -d /tmp/relations-report-copy.XXXXXX)
cp -R benchmarks/results/current/. "$REPORT_COPY/"
uv run --locked python benchmarks/report.py "$REPORT_COPY"
```

To recollect copied execution records, use `benchmarks/suite.py --collect --profile controlled --out "$REPORT_COPY"` with the original worker arguments if you want that reporting configuration recorded. Collection does not rerun workloads. Preserve the copied per-task identities, inspect any hash conflicts or missing tasks, and retain the untouched archive for comparison. Rewriting a checksum list for a derived report does not replace the original 19-entry integrity record.
