#!/usr/bin/env python3
"""Valida o resultado do parquetize.py: lista objetos Parquet em
`processed/` no bucket warm-tier, baixa um deles e imprime schema + contagem
de linhas — o passo 5 do checklist de validação end-to-end."""
import argparse
import io

import boto3
import pyarrow.parquet as pq


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-url", default="http://localhost:9000")
    parser.add_argument("--bucket", default="warm-tier")
    parser.add_argument("--prefix", default="processed/")
    args = parser.parse_args()

    s3 = boto3.client("s3", endpoint_url=args.endpoint_url)
    resp = s3.list_objects_v2(Bucket=args.bucket, Prefix=args.prefix)
    objects = resp.get("Contents", [])

    if not objects:
        print(f"[check-minio-parquet] nenhum objeto encontrado em "
              f"s3://{args.bucket}/{args.prefix} — rode `python3 scripts/parquetize.py` primeiro.")
        raise SystemExit(1)

    print(f"[check-minio-parquet] {len(objects)} arquivo(s) Parquet encontrados.")
    sample_key = objects[0]["Key"]
    body = s3.get_object(Bucket=args.bucket, Key=sample_key)["Body"].read()
    table = pq.read_table(io.BytesIO(body))

    print(f"[check-minio-parquet] amostra: {sample_key}")
    print(f"[check-minio-parquet] schema:\n{table.schema}")
    print(f"[check-minio-parquet] linhas: {table.num_rows}")


if __name__ == "__main__":
    main()
