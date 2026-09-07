"""Synthetic metric emission via OTLP. Services with emits_slo_metrics=true
emit metrics whose names match the policy-compiler's SLO-relevant allowlist
(*_latency_seconds, *_error_rate, *_request_count) — these tend to always
go hot. The remaining services only emit debug metrics, which follow the
base tier classification (frequently warm/drop)."""
import random

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource


def build_meter(service_name: str, otlp_endpoint: str):
    # Same reason as traces_gen.build_tracer: uses provider.get_meter()
    # directly instead of the global registry (metrics.set_meter_provider),
    # which is a process-wide singleton and would break the resource for
    # the other services running in the same synthetic load.
    resource = Resource.create({"service.name": service_name})
    exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    return provider.get_meter(f"telemetry-generator.{service_name}")


class ServiceMetrics:
    def __init__(self, meter, emits_slo_metrics: bool):
        self.emits_slo_metrics = emits_slo_metrics
        self.debug_gauge = meter.create_gauge(
            "debug_gc_pause_ms", description="simulated GC pause (low-value metric)"
        )
        if emits_slo_metrics:
            self.latency_hist = meter.create_histogram(
                "http_server_request_duration_latency_seconds",
                unit="s",
                description="request latency (SLO-relevant)",
            )
            self.error_counter = meter.create_counter(
                "http_server_error_rate", description="error count (SLO-relevant)"
            )
            self.request_counter = meter.create_counter(
                "http_server_request_count", description="request count (SLO-relevant)"
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
