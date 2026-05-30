"""OpenTelemetry configuration – exports traces to Application Insights."""

import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource


_tracer: trace.Tracer | None = None


def configure_telemetry() -> trace.Tracer:
    """Initialize Azure Monitor trace exporter and return a tracer (singleton)."""
    global _tracer
    if _tracer is not None:
        return _tracer

    connection_string = os.environ.get("APPINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        raise EnvironmentError("APPINSIGHTS_CONNECTION_STRING is required for telemetry.")

    # Lazy import to handle version compatibility
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    resource = Resource.create({"service.name": "supplychain-orchestrator-agent"})
    exporter = AzureMonitorTraceExporter(connection_string=connection_string)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _tracer = trace.get_tracer("supplychain-orchestrator-agent")
    return _tracer
