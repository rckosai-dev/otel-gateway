# Cost model — how the showback numbers are calculated

## What's actually measured vs. what's estimated

The Collector's `countconnector` measures **record counts** routed by
`service.name`/`team`/`cost_center`/`telemetry.tier` — that's a real
measurement, exposed on `:8888`/`:8889` and scraped by Prometheus. **It is
not a measurement of network or disk bytes.**

To convert a count into an estimated GB (needed to express cost in USD), we
use an average size per signal type, defined in
`policy-compiler/compile.py::BYTES_PER_RECORD`:

| Signal | Bytes/record (estimated) |
|---|---|
| logs | 256 |
| spans (traces) | 512 |
| datapoints (metrics) | 64 |

These numbers are **documented approximations**, not a precise measurement
of serialized payload size. For a demo/portfolio project that's acceptable,
and it's stated explicitly here and in the article — the routing-by-value
methodology doesn't depend on byte-level precision, only on the relative
proportion between services/tiers. In production, the ideal would be to
instrument the exporter to report real bytes (some recent Collector
versions expose payload-size metrics per exporter).

## Cost constants

`COST_PER_GB_HOT` (default 0.50 USD/GB) and `COST_PER_GB_WARM` (default
0.023 USD/GB) — the latter is close to S3 Standard's public price; the
former is an approximation of the ingestion cost of a commercial
volume-priced observability platform. Adjustable via `.env` and via
`policy-compiler` flags (`--cost-per-gb-hot`/`--cost-per-gb-warm`).

## The three showback metrics

- **`cost:residual_usd:by_service_tier`** — what's still being paid (hot +
  warm).
- **`cost:downgrade_saving_usd:by_service`** — volume that went to warm
  instead of hot, multiplied by the price difference. **Deliberate
  simplification**: this mixes "true reclassification" (a signal that
  would be hot but got downgraded) with "natural warm baseline" (a signal
  that would never be hot, e.g. an INFO log from a standard-tier service).
  We don't separate the two because it would require tracking the
  counterfactual "what would have happened without rule X" — out of scope
  for the demo, but documented here for anyone adapting this into a real
  implementation.
- **`cost:drop_saving_usd:by_service`** — dropped volume × hot cost (total
  saving, no simplification — dropped is dropped).

## Query cost (Athena) — why partitioning matters

Athena charges by TB **scanned**, not by query time. The Glue table
(`terraform/modules/glue-catalog`) is partitioned by `cost_center`/`dt`/
`service_name` precisely so a question like "checkout-api logs on 09/07"
scans only the relevant partition, not the entire bucket. A warm tier
without correct partitioning is a common trap: the ingestion saving gets
wiped out by the cost of every subsequent query.
