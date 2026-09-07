#!/usr/bin/env python3
"""Orquestra a carga sintética: um worker por serviço (de services.yaml),
emitindo logs/traces/métricas via OTLP para o Gateway Collector, na taxa
definida pelo serviço x multiplicador do perfil escolhido.

Uso:
    python3 generator.py --profile steady --duration 300
    python3 generator.py --profile smoke --duration 30
"""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

import yaml

import logs_gen
import metrics_gen
import traces_gen

PROFILE_MULTIPLIER = {"smoke": 0.1, "steady": 1.0, "burst": 3.0}


def load_services(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["services"]


def run_service_worker(service: dict, otlp_endpoint: str, multiplier: float, stop_at: float) -> None:
    name = service["name"]
    error_rate = service["error_rate"]

    logger = logs_gen.build_logger(name, otlp_endpoint)
    tracer = traces_gen.build_tracer(name, otlp_endpoint)
    meter = metrics_gen.build_meter(name, otlp_endpoint)
    svc_metrics = metrics_gen.ServiceMetrics(meter, service.get("emits_slo_metrics", False))

    log_rate = max(service["log_volume_per_min"] * multiplier / 60.0, 0.01)
    trace_rate = max(service["trace_volume_per_min"] * multiplier / 60.0, 0.01)

    next_log_at = next_trace_at = next_metric_at = time.time()

    while time.time() < stop_at:
        now = time.time()
        if now >= next_log_at:
            logs_gen.emit_one(logger, error_rate)
            next_log_at = now + 1.0 / log_rate
        if now >= next_trace_at:
            traces_gen.emit_one(tracer, error_rate)
            next_trace_at = now + 1.0 / trace_rate
        if now >= next_metric_at:
            svc_metrics.emit_one(error_rate)
            next_metric_at = now + 5.0
        time.sleep(0.01)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=list(PROFILE_MULTIPLIER), default="steady")
    parser.add_argument("--duration", type=int, default=300, help="segundos de carga")
    parser.add_argument("--services-file", default=str(Path(__file__).with_name("services.yaml")))
    parser.add_argument("--otlp-endpoint",
                         default=os.environ.get("OTLP_ENDPOINT", "localhost:4317"))
    args = parser.parse_args()

    services = load_services(Path(args.services_file))
    multiplier = PROFILE_MULTIPLIER[args.profile]
    stop_at = time.time() + args.duration

    print(f"[telemetry-generator] profile={args.profile} duration={args.duration}s "
          f"services={len(services)} endpoint={args.otlp_endpoint}")

    threads = [
        threading.Thread(target=run_service_worker, args=(svc, args.otlp_endpoint, multiplier, stop_at),
                          name=svc["name"], daemon=True)
        for svc in services
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("[telemetry-generator] carga concluída.")

    # Os providers OTel registram atexit hooks que fazem force_flush()
    # síncrono com retry/backoff exponencial do exporter OTLP — se o
    # Collector estiver indisponível ou lento, isso pode travar a saída do
    # processo por muito mais tempo que --duration. Como esta é uma carga
    # de demonstração (perder o último lote em trânsito é aceitável), saímos
    # explicitamente sem passar pelo shutdown padrão do interpretador.
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
