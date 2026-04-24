import asyncio
import random
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

# Create the FastAPI application
app = FastAPI(title="Kitchen Service")

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
    # Increment the counter for this flavor
    smoothies_ordered.labels(flavor=order.flavor).inc()
    logger.info(
        "Processing %s order with %s cooks available",
        order.flavor,
        NUM_COOKS,
        extra={"tags": {"flavor": order.flavor, "num_cooks": str(NUM_COOKS)}}
    )
    try:
        # Try to get a cook (wait max 2 seconds)
        logger.debug(f"Waiting for a cook to become available")
        await asyncio.wait_for(cook_semaphore.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        # All cooks are busy and timeout reached -> reject the order
        logger.error(f"Can't process the order: {NUM_COOKS} cooks are currently busy. Consider increasing NUM_COOKS.")
        raise HTTPException(status_code=503, detail="All cooks are currently busy")

    try:
        # Simulate preparing the smoothie (takes 1.5 to 2.5 seconds)

        await asyncio.sleep(random.uniform(1.5, 2.5))
        logger.info(f"Smoothie with flavor {order.flavor} prepared")
        return {"status": "done", "flavor": order.flavor}
    finally:
        # Release the cook so they can prepare the next smoothie
        cook_semaphore.release()