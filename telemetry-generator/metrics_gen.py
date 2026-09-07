"""Emissão de métricas sintéticas via OTLP. Serviços com emits_slo_metrics=true
emitem métricas cujos nomes casam com a allowlist SLO-relevante do
policy-compiler (*_latency_seconds, *_error_rate, *_request_count) — essas
sempre tendem a hot. Os demais serviços emitem só métricas de debug, que
seguem a classificação base por tier (frequentemente warm/drop)."""
import random

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource


def build_meter(service_name: str, otlp_endpoint: str):
    # Mesma razão do traces_gen.build_tracer: usa provider.get_meter()
    # diretamente em vez do registro global (metrics.set_meter_provider),
    # que é um singleton por processo e quebraria o resource dos demais
    # serviços rodando na mesma carga sintética.
    resource = Resource.create({"service.name": service_name})
    exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    return provider.get_meter(f"telemetry-generator.{service_name}")


class ServiceMetrics:
    def __init__(self, meter, emits_slo_metrics: bool):
        self.emits_slo_metrics = emits_slo_metrics
        self.debug_gauge = meter.create_gauge(
            "debug_gc_pause_ms", description="pausa de GC simulada (métrica de baixo valor)"
        )
        if emits_slo_metrics:
            self.latency_hist = meter.create_histogram(
                "http_server_request_duration_latency_seconds",
                unit="s",
                description="latência de request (SLO-relevante)",
            )
            self.error_counter = meter.create_counter(
                "http_server_error_rate", description="contagem de erros (SLO-relevante)"
            )
            self.request_counter = meter.create_counter(
                "http_server_request_count", description="contagem de requests (SLO-relevante)"
            )

    def emit_one(self, error_rate: float) -> None:
        self.debug_gauge.set(random.uniform(1, 50))
        if not self.emits_slo_metrics:
            return
        is_error = random.random() < error_rate
        self.latency_hist.record(random.uniform(0.01, 0.9))
        self.request_counter.add(1)
        if is_error:
            self.error_counter.add(1)
