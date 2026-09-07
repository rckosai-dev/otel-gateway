#!/bin/sh
# Roda como container efêmero (mc) no docker-compose, depois do MinIO subir
# "healthy". Cria o bucket warm-tier usado pelo exporter awss3/warm.
set -eu

MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000"
export MC_HOST_local

echo "Aguardando MinIO..."
until mc ls local >/dev/null 2>&1; do
  sleep 1
done

mc mb --ignore-existing "local/${MINIO_BUCKET}"
mc anonymous set download "local/${MINIO_BUCKET}" || true

echo "Bucket ${MINIO_BUCKET} pronto."
