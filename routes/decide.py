"""FastAPI router for the GeoDispatch triage endpoint.

POST /decide takes one AgentRequest (one zone batch), runs it through the
Ollama-backed agent, and returns an AgentResponse.

Contract enforcement is deliberately split by layer:
* Request schema violations are rejected by FastAPI/Pydantic *before* this
  handler runs, yielding an automatic 422 — that is the correct behavior, so we
  do NOT try to catch or reshape it.
* Anything that goes wrong inside call_agent surfaces as a clean 500 with a
  short message; the full traceback is logged server-side only, never returned
  to the caller.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from models.schemas import AgentRequest, AgentResponse
from services.ollama import call_agent

logger = logging.getLogger("geodispatch.decide")

router = APIRouter()


# Async def on purpose: call_agent is a coroutine that fans out one Ollama call
# per device concurrently (asyncio.gather), so we await it directly on the event
# loop rather than running a blocking call in the threadpool.
@router.post("/decide", response_model=AgentResponse)
async def decide(request: AgentRequest) -> AgentResponse:
    started = time.perf_counter()
    # Per-request context for the logs — no phone numbers / PII.
    ctx = (
        f"event_id={request.event_id} zone={request.zone} "
        f"batch_index={request.batch_index} devices={len(request.devices)}"
    )

    try:
        response = await call_agent(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        # logger.exception records the full traceback in the SERVER log only.
        logger.exception("/decide FAILED %s latency_ms=%.1f", ctx, elapsed_ms)
        # Caller gets a short, generic message — no internals, no stack trace.
        raise HTTPException(
            status_code=500, detail="Failed to process decision request"
        ) from None

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info("/decide OK %s latency_ms=%.1f", ctx, elapsed_ms)
    return response
