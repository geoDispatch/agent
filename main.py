"""GeoDispatch AI triage service — FastAPI application entrypoint.

Run locally with:
    uvicorn main:app --host 0.0.0.0 --port 8000

Exposes:
    GET  /health   liveness probe
    POST /decide   triage one zone batch (see routes/decide.py)
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from routes.decide import router as decide_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="GeoDispatch AI Agent", version="0.1.0")
app.include_router(decide_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
