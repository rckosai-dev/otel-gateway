"""Synthetic trace emission via OTLP, with ERROR status varying by
service.error_rate and occasionally high latency — feeds both the
error-upgrade rule and the Collector's tail_sampling."""
import random
import time

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

_ROUTES = ["/cart", "/checkout", "/search", "/recommend", "/health"]


def build_tracer(service_name: str, otlp_endpoint: str):
    # Uses provider.get_tracer() directly instead of trace.set_tracer_provider()
    # + trace.get_tracer(): the global provider is a process-wide singleton,
    # and since each service worker has its own TracerProvider/Resource,
    # going through the global registry would make every span except the
    # first registered service's carry the wrong resource (service.name).
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider.get_tracer(f"telemetry-generator.{service_name}")


def emit_one(tracer, error_rate: float) -> None:
    route = random.choice(_ROUTES)
    is_error = random.random() < error_rate
    is_slow = random.random() < 0.05

    with tracer.start_as_current_span(f"HTTP {route}") as span:
        span.set_attribute("http.route", route)
        if is_slow:
            time.sleep(random.uniform(0.5, 0.9))
            span.set_attribute("slo.relevant", True)
        if is_error:
            span.set_attribute("http.status_code", 500)
            span.set_status(Status(StatusCode.ERROR, "downstream failure"))
        else:
            span.set_attribute("http.status_code", 200)
            span.set_status(Status(StatusCode.OK))
