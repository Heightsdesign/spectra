"""FastAPI entry point for SPECTRA."""

import logging

from fastapi import FastAPI

from app.cards import router
from app.boundary_review import router as review_router
from app.auth import router as auth_router
from app.submissions import router as submission_router
from app.pricing_api import router as pricing_router
from app.checkout_api import router as checkout_router
from app.intake import router as intake_router
from app.customer_operations import router as customer_operations_router
from app.physical_labels import router as labels_router
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI(title="SPECTRA")
app.include_router(router)
app.include_router(review_router)
app.include_router(auth_router)
app.include_router(pricing_router)
app.include_router(checkout_router)
app.include_router(submission_router)
app.include_router(intake_router)
app.include_router(customer_operations_router)
app.include_router(labels_router)


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request, exc):
    if request.url.path.startswith(("/api/auth/", "/api/submissions", "/api/addresses", "/internal/intake", "/internal/customer-operations", "/internal/labels")):
        # FastAPI's default error response includes submitted input (passwords).
        return JSONResponse({"detail": "invalid_input"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(SQLAlchemyError)
async def safe_database_error(request, exc):
    return JSONResponse({"detail": "Service unavailable"}, status_code=503)


@app.middleware("http")
async def private_auth_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/auth/", "/api/submissions", "/api/addresses", "/internal/intake", "/internal/customer-operations", "/internal/labels")):
        response.headers["Cache-Control"] = "no-store"
        if request.url.path.startswith(('/internal/customer-operations', '/internal/labels')):
            response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report that the application is running."""
    return {"status": "ok", "application": "SPECTRA"}
