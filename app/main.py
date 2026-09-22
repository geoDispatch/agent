from fastapi import FastAPI
from app.routers.decide import router as decide_router

app = FastAPI(title="Disaster Response API", description="API for disaster response and triage.", version="1.0.0")

app.include_router(decide_router)