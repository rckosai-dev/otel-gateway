"""Synthetic log emission via OTLP, with severity varying by
service.error_rate — that variation is what makes the "error-signal-upgrade"
rule in the routing policy (policy/routing-policy.yaml) actually kick in."""
import logging
import random

from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

_INFO_MESSAGES = [
    "request handled",
    "cache hit",
    "background job tick",
    "health check ok",
]
_DEBUG_MESSAGES = [
    "entering handler",
    "computed intermediate value",
    "row processed",
]
_ERROR_MESSAGES = [
    "upstream timeout",
    "unhandled exception in handler",
    "database connection refused",
]


def build_logger(service_name: str, otlp_endpoint: str) -> logging.Logger:
    # logger_provider=provider below uses the LOCAL provider directly (not
    # the global _logs.set_logger_provider registry), for the same reason
    # described in traces_gen.build_tracer/metrics_gen.build_meter: a
    # process-wide global provider would break the resource for the other
    # services in the load.
    resource = Resource.create({"service.name": service_name})
    provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    handler = LoggingHandler(level=logging.DEBUG, logger_provider=provider)
    logger = logging.getLogger(f"telemetry-generator.{service_name}")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def emit_one(logger: logging.Logger, error_rate: float) -> None:
    roll = random.random()
    if roll < error_rate:
        logger.error(random.choice(_ERROR_MESSAGES))
    elif roll < error_rate + 0.15:
        logger.debug(random.choice(_DEBUG_MESSAGES))
    else:
        logger.info(random.choice(_INFO_MESSAGES))
