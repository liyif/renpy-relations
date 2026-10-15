# Saved controlled suite: English measurement summary

This report derives tables from the preserved JSON records. No benchmark was run to create it. It describes the measured historical source, not the current runtime. Read the [methods guide](../../README.md) before comparing modes or backends.

## Measurement and reporting identity

All eight tasks in [results.json](results.json) are recorded complete, with no unknown task source identities or union hash conflicts. Each task’s `measured_source` and child result hashes remain the authority for its workload. The measured Git checkout was dirty at commit `c96c103578e646c5617483f482a78ff161a77506`. A commit identifier alone cannot reconstruct those uncommitted changes.

- Measured runtime SHA256: `400c16af67966c93403461ba1fb4f73a08f2167a8337067d44585ffdf80d7bdd`.
- Measured lockfile SHA256: `270ae36251a36cf873b4a04a28770234191e8037bc60ed8602b3f8619bdb000d`.
- Both differ from this copy; the compiler and benchmark scripts matched their recorded hashes when the English guide was authored.
- Saved suite report-generation identity was captured at `2026-10-15T01:09:18.632796+08:00`, also with a dirty checkout. This English summary is a later derivation and does not rewrite that field.

Host: AMD Ryzen 9 7900X 12-Core Processor; Linux-7.1.9-zen1-2-zen-x86_64-with-glibc2.44; 24 logical CPUs. Recorded workers use the SDK’s Python 3.12.8, SQLAlchemy 2.0.43, pysqlite3/SQLite 3.51.1 and DuckDB 1.5.6. Worker executable and dependency paths in JSON describe the measurement environment; they are not reusable installation locations.

The original [SHA256SUMS](SHA256SUMS) contains 19 entries covering the preserved raw JSON/CSV files. All entries matched when this summary was derived. The file is unchanged and does not cover this added Markdown summary. Completion and integrity do not establish unmeasured configurations.

## Recorded coverage

| Task / raw record | Timing or probe records | Separate validation records |
| --- | ---: | ---: |
| [conditions-sqlite](conditions-sqlite/results.json) | 108 | 36 |
| [conditions-duckdb](conditions-duckdb/results.json) | 9 | 3 |
| [facts-sqlite](facts-sqlite/results.json) | 30 | 0 |
| [facts-duckdb](facts-duckdb/results.json) | 10 | 0 |
| [snapshots](snapshots/results.json) | 18 | 0 |
| [graph](graph/results.json) | 6 | 0 |
| [duckdb-load-3000](duckdb-load-3000/results.json) | 1 | 0 |
| [duckdb-load-10000](duckdb-load-10000/results.json) | 1 | 0 |

The SQLite condition matrix spans 1,000/3,000/10,000 conditions, ratios 1/10, both layouts and all three modes. DuckDB’s complete matrix covers only 1,000 conditions, ratio 10, partitioned layout and three modes. Fact-volume SQLite covers 10,000/100,000/1,000,000 characters; DuckDB covers only 10,000. The fact counts include one seed worker per size/backend, not another independent timing repeat. All saved condition variants are `native`; a stored baseline reference does not supply a measured baseline comparison.

## Fact-volume example: 10,000 characters

Both backends have 15,372 fact rows here. Values below are medians of exactly three successful measurement workers per backend/mode. Warm has is the median of the pooled 12 request samples from each worker (36 samples per row). Wall times are milliseconds. Commit rows have no snapshot history receiver. The snapshot column measures reuse of the fixture image retained by initial restore, before edits; full snapshot generation occurs in the separate seed worker. Single edit, batch, reload and restoration are sequential phases, so later phases inherit earlier changes until the fixture is restored.

| Backend | Mode | First has | Warm has/request | Single commit | First has after single | Snapshot reuse | Restore after edits |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sqlite | cached | 18.981 | 0.187 | 0.438 | 4.348 | 0.001 | 2.801 |
| sqlite | live | 7.657 | 6.678 | 0.402 | 6.714 | 0.001 | 3.239 |
| sqlite | materialized | 1.256 | 0.198 | 4.453 | 0.210 | 0.001 | 20.943 |
| duckdb | cached | 13.528 | 0.858 | 3.065 | 5.956 | 0.001 | 49.297 |
| duckdb | live | 3.441 | 2.039 | 1.516 | 2.314 | 0.001 | 51.682 |
| duckdb | materialized | 1.433 | 0.860 | 8.621 | 1.037 | 0.001 | 61.181 |

This selection illustrates where work occurs; it does not summarize the larger SQLite sizes. Full stages, CPU/RSS, fixture hashes and cardinalities are in [SQLite JSON](facts-sqlite/results.json), [DuckDB JSON](facts-duckdb/results.json) and their [SQLite CSV](facts-sqlite/phases.csv) / [DuckDB CSV](facts-duckdb/phases.csv). Public ingestion and fixture creation are separate from the three measurement repeats.

## Condition example: 1,000 checks, ratio 10, partitioned facts

These matched configurations contain 107 fact rows and 1,064 derived outputs including 64 helpers. Each row uses exactly three successful timing workers, and a separate successful full-relation validation worker. Values are medians of complete phase wall times in milliseconds; a panel contains all 1,000 requests. The warm request columns are medians across workers of each worker’s request median/p95, not pooled percentiles. Local, global and unrelated edits occur in that order without resetting: the global panel still includes the local edit, and the unrelated panel includes both.

| Backend | Mode | Load | Cold panel | Warm panel | Local commit + panel | Global commit + panel | Warm request median / p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sqlite | cached | 58.974 | 542.646 | 255.748 | 225.771 | 445.772 | 0.198 / 0.254 |
| sqlite | materialized | 206.549 | 277.298 | 219.734 | 263.731 | 336.394 | 0.199 / 0.260 |
| sqlite | live | 109.862 | 342.873 | 269.227 | 311.158 | 306.295 | 0.249 / 0.308 |
| duckdb | cached | 665.706 | 2898.281 | 702.602 | 778.173 | 2762.565 | 0.699 / 0.729 |
| duckdb | materialized | 1465.304 | 740.073 | 702.973 | 745.189 | 1487.062 | 0.697 / 0.744 |
| duckdb | live | 916.159 | 1326.471 | 1275.177 | 1262.853 | 1208.106 | 1.277 / 1.360 |

See [SQLite conditions](conditions-sqlite/results.json) and [DuckDB conditions](conditions-duckdb/results.json) for other parameters, ingestion, unrelated edits, invalidations/rebuilds, memory and complete validation evidence. No failed or incomplete groups were included in these tables.

## Snapshot path

Each row is the median of three independent processes, with one sequential sample per process. Setup uses native SQL outside timing. Times are milliseconds; image size is MiB. History commit publishes the latest image to a callback without retaining a complete rollback history. Reused snapshot follows an unchanged snapshot and is a distinct path from full serialization. The phases run sequentially: a marker edit precedes full snapshot/reuse, an ordinary edit follows, the callback-bound world restores that saved image before its history edit, and the original world then restores it. These are different states along one sequence, not separately reset baselines.

| Seed rows | Backend / driver | Ordinary commit | History commit | Full snapshot | Reused snapshot | Restore | Image MiB |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | sqlite / pysqlite3 | 0.371 | 0.873 | 0.794 | 0.000761 | 2.149 | 0.418 |
| 10,000 | duckdb / duckdb | 2.920 | 16.378 | 12.927 | 0.001022 | 40.784 | 1.262 |
| 100,000 | sqlite / pysqlite3 | 0.476 | 3.554 | 4.097 | 0.000691 | 9.894 | 4.148 |
| 100,000 | duckdb / duckdb | 3.303 | 100.226 | 95.687 | 0.001022 | 95.467 | 5.262 |
| 1,000,000 | sqlite / pysqlite3 | 0.653 | 31.392 | 32.966 | 0.001122 | 93.626 | 41.492 |
| 1,000,000 | duckdb / duckdb | 3.578 | 956.410 | 939.366 | 0.001072 | 665.593 | 46.012 |

The [raw snapshot record](snapshots/results.json) provides individual samples, driver/runtime identity and parameters. These are simple Seed rows, not the Palace fact distribution or story-condition workload.

## Chains and loading probes

One observation per row, in milliseconds. Chains check the last output then validate invalidation after a removal. Loading probes check one selected condition after ingestion. Neither measures Logica compilation or a complete large DuckDB panel.

| Chain length | Backend | Load | First final-output read |
| ---: | --- | ---: | ---: |
| 128 | sqlite | 6.404 | 13.228 |
| 128 | duckdb | 102.199 | 64.166 |
| 512 | sqlite | 20.791 | 56.083 |
| 512 | duckdb | 293.026 | 241.068 |
| 1,050 | sqlite | 48.650 | 102.344 |
| 1,050 | duckdb | 542.450 | 489.619 |

| DuckDB condition probe | Facts | Load | Ingest | One selected has |
| ---: | ---: | ---: | ---: | ---: |
| 3,000 | 307 | 1863.104 | 251.205 | 6.184 |
| 10,000 | 1,007 | 6005.009 | 799.627 | 5.722 |

Raw records: [chains](graph/results.json), [3,000-condition probe](duckdb-load-3000/results.json), [10,000-condition probe](duckdb-load-10000/results.json). The completed probes do not fill the missing DuckDB matrix at those counts. DuckDB’s 100,000/1,000,000-character fact-volume workloads, full-engine frame rate, long retained rollback histories, save archive cost, skewed data and cross-hardware comparisons remain unmeasured in this suite.

Interpret phase costs together with mode, layout, output row count and driver path. These observations do not establish a universal backend ranking or guarantee a game’s frame time. New measurements need their own source and environment identity. Report rendering and suite collection write files; follow the [copied-tree workflow](../../README.md#render-reports-without-changing-the-archive) to preserve this archive.
