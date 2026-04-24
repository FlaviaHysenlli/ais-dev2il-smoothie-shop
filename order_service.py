import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

# Create the FastAPI application
app = FastAPI(title="Order Service")

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

