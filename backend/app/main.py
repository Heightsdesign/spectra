"""FastAPI entry point for SPECTRA."""

import logging

from fastapi import FastAPI

from app.cards import router

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(title="SPECTRA")
app.include_router(router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report that the application is running."""
    return {"status": "ok", "application": "SPECTRA"}
