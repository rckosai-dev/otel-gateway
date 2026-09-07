#!/usr/bin/env python3
"""
Warm-tier ETL job (the plan's "future query path"): reads the raw
OTLP/JSON objects the Collector's awss3exporter wrote to `otel/` (local
MinIO bucket, or real S3 in production) and rewrites them as Parquet,
partitioned as `processed/cost_center=.../dt=.../service_name=...`, in the
shape expected by the Glue table (terraform/modules/glue-catalog).

In real production, the recommended path is Kinesis Firehose or a managed
Glue ETL job — this script is the pragmatic equivalent for the local demo,
documenting the same schema contract.

Usage:
    python3 scripts/parquetize.py \
        --endpoint-url http://localhost:9000 \
        --bucket warm-tier

Requires AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY credentials in the
environment (the same ones from .env — MINIO_ROOT_USER/MINIO_ROOT_PASSWORD).
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema([
    ("ts", pa.int64()),
    ("signal_type", pa.string()),
    ("team", pa.string()),
    ("telemetry_tier", pa.string()),
    ("severity", pa.string()),
    ("trace_id", pa.string()),
    ("span_id", pa.string()),
    ("status_code", pa.string()),
    ("body", pa.string()),
    ("policy_version", pa.string()),
])


def attrs_to_dict(attrs: list) -> dict:
    out = {}
    for kv in attrs or []:
        key = kv.get("key")
        value = kv.get("value", {})
        out[key] = (
            value.get("stringValue")
            or value.get("boolValue")
            or value.get("intValue")
            or value.get("doubleValue")
        )
    return out


def rows_from_resource_logs(payload: dict) -> list:
    rows = []
    for rl in payload.get("resourceLogs", []):
        res_attrs = attrs_to_dict(rl.get("resource", {}).get("attributes", []))
        for sl in rl.get("scopeLogs", []):
            for rec in sl.get("logRecords", []):
                rows.append({
                    "ts": int(rec.get("timeUnixNano", 0)) // 1_000_000,
                    "signal_type": "log",
                    "team": res_attrs.get("team"),
                    "telemetry_tier": res_attrs.get("telemetry.tier"),
                    "severity": rec.get("severityText"),
                    "trace_id": rec.get("traceId"),
                    "span_id": rec.get("spanId"),
                    "status_code": None,
                    "body": (rec.get("body", {}) or {}).get("stringValue"),
                    "policy_version": res_attrs.get("policy.version"),
                    "cost_center": res_attrs.get("cost_center"),
                    "service_name": res_attrs.get("service.name"),
                })
    return rows


def rows_from_resource_spans(payload: dict) -> list:
    rows = []
    for rs in payload.get("resourceSpans", []):
        res_attrs = attrs_to_dict(rs.get("resource", {}).get("attributes", []))
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                rows.append({
                    "ts": int(span.get("startTimeUnixNano", 0)) // 1_000_000,
                    "signal_type": "trace",
                    "team": res_attrs.get("team"),
                    "telemetry_tier": res_attrs.get("telemetry.tier"),
                    "severity": None,
                    "trace_id": span.get("traceId"),
                    "span_id": span.get("spanId"),
                    "status_code": (span.get("status", {}) or {}).get("code"),
                    "body": span.get("name"),
                    "policy_version": res_attrs.get("policy.version"),
                    "cost_center": res_attrs.get("cost_center"),
                    "service_name": res_attrs.get("service.name"),
                })
    return rows


def partition_key(row: dict) -> tuple:
    dt = datetime.fromtimestamp(row["ts"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if row["ts"] else "unknown"
    return (row.get("cost_center") or "unknown", dt, row.get("service_name") or "unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-url", default="http://localhost:9000")
    parser.add_argument("--bucket", default="warm-tier")
    parser.add_argument("--raw-prefix", default="otel/")
    parser.add_argument("--processed-prefix", default="processed/")
    args = parser.parse_args()

    s3 = boto3.client("s3", endpoint_url=args.endpoint_url)

    paginator = s3.get_paginator("list_objects_v2")
    partitions = defaultdict(list)
    object_count = 0

    for page in paginator.paginate(Bucket=args.bucket, Prefix=args.raw_prefix):
        for obj in page.get("Contents", []):
            object_count += 1
            body = s3.get_object(Bucket=args.bucket, Key=obj["Key"])["Body"].read()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                continue
            rows = rows_from_resource_logs(payload) + rows_from_resource_spans(payload)
            for row in rows:
                partitions[partition_key(row)].append(row)

    if object_count == 0:
        print(f"[parquetize] no objects in s3://{args.bucket}/{args.raw_prefix} — nothing to do.")
        return

    for (cost_center, dt, service_name), rows in partitions.items():
        columns = {field.name: [r.get(field.name) for r in rows] for field in SCHEMA}
        table = pa.table(columns, schema=SCHEMA)
        key = (f"{args.processed_prefix}cost_center={cost_center}/dt={dt}/"
               f"service_name={service_name}/part-{datetime.now(tz=timezone.utc).strftime('%H%M%S')}.parquet")

        buf = pa.BufferOutputStream()
        pq.write_table(table, buf, compression="snappy")
        s3.put_object(Bucket=args.bucket, Key=key, Body=buf.getvalue().to_pybytes())
        print(f"[parquetize] {len(rows)} records -> s3://{args.bucket}/{key}")

    print(f"[parquetize] OK — {object_count} raw objects processed, "
          f"{len(partitions)} partitions written.")


if __name__ == "__main__":
    main()
