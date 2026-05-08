from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource

# Configure OpenTelemetry tracing
resource = Resource.create({"service.name": "order-service"})
trace.set_tracer_provider(TracerProvider(resource=resource))
# This is going to export the tracing data to Jaeger
otlp_exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))

from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Instrument logging to automatically inject trace context into all log records

def log_hook(span, record):
    if not hasattr(record, "tags"):
        record.tags = {}
    record.tags["service_name"] = resource.attributes["service.name"]
    record.tags["trace_id"] = format(span.get_span_context().trace_id, "032x")

LoggingInstrumentor().instrument(log_hook=log_hook)

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

# Create the FastAPI application
app = FastAPI(title="Order Service")

# This is going to hook into FastAPI and automatically create traces for all HTTP requests
# We exclude "receive" and "send" spans because they are not relevant for us and just add noise to the traces
FastAPIInstrumentor.instrument_app(app)
# This is going to hook into HTTPX to automatically create traces for all outgoing HTTP requests and to
# connect traces between services with each other
HTTPXClientInstrumentor().instrument()

# Data model: Defines what an order looks like
class Order(BaseModel):
    flavor: str

@app.on_event("startup")
async def startup_event():
    logger.info(f"{app.title} online and ready for customers")

# Endpoint: Receives customer orders
@app.post("/order")
async def create_order(order: Order):

    # Log incoming request
    logger.info(f"Customer wants a {order.flavor} smoothie")

    # Create an HTTP client to communicate with the kitchen service
    async with httpx.AsyncClient() as client:
        try:
            # Log the outgoing call to the kitchen
            logger.debug(f"Sending {order.flavor} request to Kitchen Service ...")

            # Send the order to the kitchen service
            response = await client.post(
                "http://localhost:8001/prepare",
                json={"flavor": order.flavor}
            )
            # Raise an error if the kitchen returned an error status code
            response.raise_for_status()

            logger.info(f"Order for {order.flavor} successful!")

            return {"status": "completed", "kitchen_response": response.json()}
        except httpx.HTTPStatusError as e:
            # Log Kitchen-specific failures (e.g. 503 Busy)
            logger.warning(f"kitchen rejected {order.flavor}: Status {e.response.status_code}")

            # Kitchen returned an error (e.g., 503 if all cooks are busy)
            raise HTTPException(status_code=e.response.status_code, detail="Kitchen failed to process order")
        except httpx.RequestError:
            # Log network failures (e.g. Kitchen is offline)
            logger.error(f"Network Error: Could not connect to Kitchen. {e}")

            # Could not connect to the kitchen service
            raise HTTPException(status_code=503, detail="Kitchen unavailable")

