"""Minimal HTTP application; match and emulator operations are added in later milestones."""

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    emulator: str = "not_started"


app = FastAPI(title="AW2 Lab API", version="0.1.0")


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Report that the HTTP process is responsive; this does not imply a match is running."""
    return HealthResponse()
