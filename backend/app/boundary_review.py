"""Opt-in, loopback-only manual validation. No arbitrary file serving."""

import hashlib
import io
import ipaddress
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import cv2
import numpy as np
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image

from app.boundary_storage import analyze_original
from app.cards import Config, Db
from app.models import CardImage


def local_request(request: Request, settings: Config):
    if not settings.boundary_review_enabled:
        raise HTTPException(404, "Local review is disabled")
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    host = request.url.hostname
    if not local or host not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "Loopback access required")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Same-origin access required")
    if request.method == "POST" and request.headers.get("x-spectra-review") != "1":
        raise HTTPException(403, "Local review header required")


router = APIRouter(prefix="/internal/boundary", dependencies=[Depends(local_request)])


def roots(settings):
    original = settings.card_image_dir.resolve()
    diagnostic = settings.boundary_output_dir.resolve()
    if original == diagnostic or original in diagnostic.parents or diagnostic in original.parents:
        raise HTTPException(503, "Storage configuration invalid")
    return original, diagnostic


def safe_file(root: Path, *parts: str) -> Path:
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or path.is_junction() or path.resolve().parent != path.parent.resolve():
            raise HTTPException(404, "Artifact not found")
    if not path.is_file():
        raise HTTPException(404, "Artifact not found")
    return path


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Stored metadata unavailable") from None


def load_run(run_id, settings):
    _, root = roots(settings)
    data = read_json(safe_file(root, run_id.hex, "result.json"))
    try:
        if UUID(data["run_id"]) != run_id:
            raise ValueError()
        UUID(data["image_id"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, "Stored metadata invalid") from None
    return data


def run_response(run_id, settings):
    data = load_run(run_id, settings)
    _, root = roots(settings)
    images = {"original": f"/internal/boundary/images/{data['image_id']}/preview"}
    for name in ("mask", "overlay", "normalized"):
        try:
            safe_file(root, run_id.hex, name + ".png")
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        else:
            images[name] = f"/internal/boundary/runs/{run_id}/diagnostics/{name}"
    reviews = []
    for path in sorted((root / run_id.hex).glob("review-*.json")):
        if re.fullmatch(r"review-[0-9a-f]{32}\.json", path.name):
            reviews.append(read_json(safe_file(root, run_id.hex, path.name)))
    reviews.sort(key=lambda item: (item["created_at"], item["review_id"]))
    return {**data, "images": images, "reviews": reviews}


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/images/{image_id}/analyses", status_code=201)
def create_analysis(image_id: UUID, session: Db, settings: Config, payload: AnalysisRequest = Body(default=AnalysisRequest())):
    roots(settings)
    original = session.get(CardImage, image_id)
    if original is None:
        raise HTTPException(404, "Image not found")
    try:
        analysis = analyze_original(original, settings)
    except (OSError, ValueError):
        raise HTTPException(503, "Analysis storage unavailable") from None
    return run_response(analysis.run_id, settings)


@router.get("/runs")
def list_runs(settings: Config):
    _, root = roots(settings)
    try:
        ids = sorted(p.name for p in root.iterdir()) if root.exists() else []
        return [run_response(UUID(hex=name), settings) for name in ids if re.fullmatch(r"[0-9a-f]{32}", name)]
    except OSError:
        raise HTTPException(503, "Analysis storage unavailable") from None


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, settings: Config):
    return run_response(run_id, settings)


@router.get("/runs/{run_id}/diagnostics/{name}")
def diagnostic(run_id: UUID, name: Literal["mask", "overlay", "normalized"], settings: Config):
    load_run(run_id, settings)
    _, root = roots(settings)
    try:
        data = safe_file(root, run_id.hex, name + ".png").read_bytes()
    except OSError:
        raise HTTPException(503, "Diagnostic unavailable") from None
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/images/{image_id}/preview")
def preview(image_id: UUID, session: Db, settings: Config):
    root, _ = roots(settings)
    original = session.get(CardImage, image_id)
    if original is None:
        raise HTTPException(404, "Image not found")
    if not re.fullmatch(r"[0-9a-f]{32}", original.storage_key):
        raise HTTPException(404, "Image not found")
    path = safe_file(root, original.storage_key)
    try:
        with path.open("rb") as stream:
            data = stream.read(settings.max_image_size_bytes + 1)
        if len(data) > settings.max_image_size_bytes or len(data) != original.file_size or hashlib.sha256(data).hexdigest() != original.sha256:
            raise HTTPException(409, "Original integrity check failed")
        # Match the adapter's pixel/frame checks before decoding, including TIFFs.
        with Image.open(io.BytesIO(data)) as header:
            if header.width * header.height > 24_000_000 or getattr(header, "n_frames", 1) != 1:
                raise HTTPException(422, "Preview requires a single image of at most 24 million pixels")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if image is None:
            raise ValueError()
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise ValueError()
    except (OSError, ValueError, cv2.error, Image.DecompressionBombError):
        raise HTTPException(503, "Preview unavailable") from None
    return Response(encoded.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["correct", "incorrect", "uncertain"]
    notes: str = Field(default="", max_length=4000)


@router.post("/runs/{run_id}/reviews", status_code=201)
def save_review(run_id: UUID, payload: Review, settings: Config):
    metadata = load_run(run_id, settings)
    _, root = roots(settings)
    review_id = uuid4()
    record = {"schema_version": 1, "review_id": str(review_id), "run_id": str(run_id),
              "image_id": metadata["image_id"], "source_sha256": metadata["source_sha256"],
              "analysis_reference": f"{run_id.hex}/result.json",
              "created_at": datetime.now(timezone.utc).isoformat(), **payload.model_dump()}
    path = root / run_id.hex / f"review-{review_id.hex}.json"
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.rename(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise HTTPException(503, "Review persistence failed") from None
    return record


@router.get("/review", response_class=HTMLResponse)
def review_page():
    return HTMLResponse(Path(__file__).with_name("boundary_review.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
