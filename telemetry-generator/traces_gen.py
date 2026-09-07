"""Emissão de traces sintéticos via OTLP, com status ERROR variável por
service.error_rate e latência ocasionalmente alta — alimenta tanto a regra
de upgrade por erro quanto o tail_sampling do Collector."""
import random
import time

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

_ROUTES = ["/cart", "/checkout", "/search", "/recommend", "/health"]


def build_tracer(service_name: str, otlp_endpoint: str):
    # Usa provider.get_tracer() diretamente em vez de trace.set_tracer_provider()
    # + trace.get_tracer(): o provider global é um singleton por processo, e
    # como cada worker de serviço tem seu próprio TracerProvider/Resource,
    # passar pelo registro global faria todos os spans, exceto os do primeiro
    # serviço registrado, carregarem o resource (service.name) errado.
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
