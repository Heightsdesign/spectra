"""FastAPI entry point for SPECTRA."""

import logging

from fastapi import FastAPI

from app.cards import router
from app.boundary_review import router as review_router
from app.auth import router as auth_router
from app.submissions import router as submission_router
from app.submission_photos import router as submission_photo_router
from app.library import router as library_router, orders as library_order_router, staff_router as library_staff_router
from app.pricing_api import router as pricing_router
from app.checkout_api import router as checkout_router
from app.intake import router as intake_router
from app import production  # noqa: F401 -- registers bridge routes on intake router
from app import thermal_labels  # noqa: F401 -- operator-controlled label audit routes
from app.customer_operations import router as customer_operations_router
from app.physical_labels import router as labels_router
from app.inspection import router as inspection_router
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO, format="%(message)s")
from app.access_privacy import IntakeAccessPrivacy
logging.getLogger('uvicorn.access').addFilter(IntakeAccessPrivacy())

from app.tcg_api import router as tcg_router

app = FastAPI(title="SPECTRA")
app.include_router(tcg_router)
app.include_router(router)
app.include_router(review_router)
app.include_router(auth_router)
app.include_router(pricing_router)
app.include_router(checkout_router)
app.include_router(submission_router)
app.include_router(submission_photo_router)
app.include_router(library_router)
app.include_router(library_order_router)
app.include_router(library_staff_router)
app.include_router(intake_router)
app.include_router(customer_operations_router)
app.include_router(labels_router)
app.include_router(inspection_router)


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request, exc):
    if request.url.path.startswith(("/api/library", "/api/auth/", "/api/catalog", "/api/submissions", "/api/addresses", "/internal/intake", "/internal/customer-operations", "/internal/labels", "/internal/inspection")):
        # FastAPI's default error response includes submitted input (passwords).
        return JSONResponse({"detail": "invalid_input"}, status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(SQLAlchemyError)
async def safe_database_error(request, exc):
    return JSONResponse({"detail": "Service unavailable"}, status_code=503)


@app.middleware("http")
async def private_auth_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/library", "/api/auth/", "/api/catalog", "/api/submissions", "/api/addresses", "/internal/intake", "/internal/customer-operations", "/internal/labels", "/internal/inspection")):
        response.headers["Cache-Control"] = "no-store"
        if any(segment in request.url.path for segment in ('/photos/', '/pre-shipment-photos/')) or request.url.path.startswith(('/internal/customer-operations', '/internal/labels', '/internal/inspection')):
            response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report that the application is running."""
    return {"status": "ok", "application": "SPECTRA"}

from app.commercial_api import router as commercial_router
app.include_router(commercial_router)

from app.stripe_api import router as stripe_router
app.include_router(stripe_router)

from app.logistics_api import router as logistics_router
app.include_router(logistics_router)
