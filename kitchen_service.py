from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource

# Configure OpenTelemetry tracing
resource = Resource.create({"service.name": "kitchen-service"})
trace.set_tracer_provider(TracerProvider(resource=resource))
# This is going to export the tracing data to Jaeger
otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))

import asyncio
import random
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

# Create the FastAPI application
app = FastAPI(title="Kitchen Service")

# This is going to hook into FastAPI and automatically create traces for all HTTP requests
# We exclude "receive" and "send" spans because they are not relevant for us and just add noise to the traces
FastAPIInstrumentor.instrument_app(app, exclude_spans=["receive", "send"])
# This is going to hook into HTTPX to automatically create traces for all outgoing HTTP requests and to
# connect traces between services with each other
HTTPXClientInstrumentor().instrument()

from prometheus_fastapi_instrumentator import Instrumentator
# Initialize Prometheus metrics instrumentation
Instrumentator().instrument(app).expose(app)

# Custom metric: Count smoothies ordered by flavor
from prometheus_client import Counter
smoothies_ordered = Counter(
    'smoothies_ordered_total',
    'Total number of smoothies ordered',
    ['flavor']
)
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Instrument logging to automatically inject trace context into all log records

def log_hook(span, record):
    if not hasattr(record, "tags"):
        record.tags = {}
    record.tags["service_name"] = resource.attributes["service.name"]
    record.tags["trace_id"] = format(span.get_span_context().trace_id, "032x")

LoggingInstrumentor().instrument(log_hook=log_hook)

# Configuration: How many cooks are available in the kitchen
NUM_COOKS = 1

# Semaphore: Controls how many smoothies can be prepared at the same time
# (one per cook). If all cooks are busy, new orders must wait.
cook_semaphore = asyncio.Semaphore(NUM_COOKS)

# Data model: Defines what a smoothie order looks like
class SmoothieOrder(BaseModel):
    flavor: str

# Challenge 1: Startup Log
@app.on_event("startup")
async def startup_event():
    logger.info(f"{app.title} started | Cooks: {NUM_COOKS}")

# Endpoint: Receives requests to prepare a smoothie
@app.post("/prepare")
async def prepare_smoothie(order: SmoothieOrder):
    logger.info(f"Received order to prepare a smoothie with flavor {order.flavor}")

    # Increment the counter for this flavor
    smoothies_ordered.labels(flavor=order.flavor).inc()

    # Get a tracer named after this module (same pattern as getLogger(__name__) for loggers).
    # The name identifies which part of the code created the tracer and will show up
    # as `otel.library.name` in Jaeger, so you can see which module produced a span.
    tracer = trace.get_tracer(__name__)

    # Custom span: Waiting for cook to become available
    with tracer.start_as_current_span("wait_for_cook") as wait_span:
        wait_span.set_attribute("flavor", order.flavor)
        wait_span.set_attribute("num_cooks", NUM_COOKS)
        try:
            logger.debug(f"Waiting for a cook to become available")
            await asyncio.wait_for(cook_semaphore.acquire(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.error(f"Can't process the order: {NUM_COOKS} cooks are currently busy. Consider increasing NUM_COOKS.")
            raise HTTPException(status_code=503, detail="All cooks are currently busy")

    try:
        # Custom span: Preparing the smoothie
        with tracer.start_as_current_span("prepare_smoothie") as prep_span:
            prep_span.set_attribute("flavor", order.flavor)
            preparation_time = random.uniform(1.5, 2.5)
            await asyncio.sleep(preparation_time)
            logger.debug(f"Smoothie with flavor {order.flavor} prepared")

        return {"status": "done", "flavor": order.flavor}
    finally:
        cook_semaphore.release()