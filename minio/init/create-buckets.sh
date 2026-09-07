#!/bin/sh
# Runs as an ephemeral container (mc) in docker-compose, after MinIO comes
# up "healthy". Creates the warm-tier bucket used by the awss3/warm exporter.
set -eu

MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000"
export MC_HOST_local

echo "Waiting for MinIO..."
until mc ls local >/dev/null 2>&1; do
  sleep 1
done

mc mb --ignore-existing "local/${MINIO_BUCKET}"
mc anonymous set download "local/${MINIO_BUCKET}" || true

echo "Bucket ${MINIO_BUCKET} ready."
