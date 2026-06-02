"""OpenTelemetry configuration – exports traces to Application Insights."""

import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

_tracer: trace.Tracer | None = None


def configure_telemetry() -> trace.Tracer:
    """Initialize Azure Monitor trace exporter and return a tracer (singleton).

    If APPINSIGHTS_CONNECTION_STRING is not set, returns a no-op tracer.
    """
    global _tracer
    if _tracer is not None:
        return _tracer

    connection_string = os.environ.get("APPINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.warning("APPINSIGHTS_CONNECTION_STRING not set – telemetry disabled, using no-op tracer.")
        _tracer = trace.get_tracer("petstoresupplychain-orchestrator-agent")
        return _tracer

    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        resource = Resource.create({"service.name": "petstoresupplychain-orchestrator-agent"})
        exporter = AzureMonitorTraceExporter(connection_string=connection_string)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("Application Insights telemetry configured.")
    except Exception as e:
        logger.warning("Failed to configure App Insights exporter: %s – using no-op tracer.", e)

    _tracer = trace.get_tracer("petstoresupplychain-orchestrator-agent")
    return _tracer
