import hashlib
import json
from uuid import UUID

import cv2
import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.boundary import BoundaryConfig, detect_boundary, order_corners
from app.boundary_storage import analyze_original
from app.models import CardImage


CORNERS = np.array([[240, 160], [492, 160], [492, 512], [240, 512]], np.float32)


def scene(points=CORNERS, background=(35, 35, 35), color=(180, 205, 235), noise=8, frame=False):
    """Render a known physical silhouette; its internal artwork has no required frame."""
    rng = np.random.default_rng(42)
    texture = np.clip(np.array(color) + rng.integers(-noise, noise + 1, (353, 253, 3)), 0, 255).astype(np.uint8)
    if frame:
        cv2.rectangle(texture, (18, 18), (234, 334), (25, 25, 25), 8)
    canvas = np.full((760, 760, 3), background, dtype=np.uint8)
    transform = cv2.getPerspectiveTransform(np.array([[0, 0], [252, 0], [252, 352], [0, 352]], np.float32), np.asarray(points, np.float32))
    rendered = cv2.warpPerspective(texture, transform, (760, 760))
    mask = cv2.warpPerspective(np.full((353, 253), 255, np.uint8), transform, (760, 760), flags=cv2.INTER_NEAREST)
    canvas[mask != 0] = rendered[mask != 0]
    return canvas


def assert_detected(image, expected, tolerance=4):
    original = image.copy()
    detection = detect_boundary(image)
    result = detection.result
    assert result.status == "detected", result.to_dict()
    assert result.failure_reason is None
    assert np.max(np.linalg.norm(np.array(result.corners) - expected, axis=1)) <= tolerance
    assert result.image_dimensions == {"width": 760, "height": 760}
    assert result.normalized_dimensions == {"width": 630, "height": 880}
    assert detection.normalized_image.shape == (880, 630, 3)
    assert result.metrics["candidate_count"] == 1
    assert np.array_equal(image, original)
    # Each reported corner is supported by the observed silhouette, not a fitted box.
    assert cv2.isContourConvex(np.array(result.corners, np.float32))
    return detection


@pytest.mark.parametrize("background", [(15, 15, 15), (245, 245, 245), (60, 150, 50), (180, 70, 100), (150, 80, 30)])
def test_centered_card_different_backgrounds(background):
    assert_detected(scene(background=background), CORNERS)


@pytest.mark.parametrize("angle,permutation", [(24, [0, 1, 2, 3]), (-30, [0, 1, 2, 3]), (85, [3, 0, 1, 2])])
def test_rotated_card(angle, permutation):
    radians = np.radians(angle)
    rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
    points = (CORNERS - CORNERS.mean(axis=0)) @ rotation.T + [380, 380]
    assert_detected(scene(points), points[permutation])


def test_perspective_distortion_and_rectification():
    points = np.array([[260, 150], [485, 185], [510, 525], [220, 495]], np.float32)
    detection = assert_detected(scene(points), points)
    projected = cv2.perspectiveTransform(np.array(detection.result.corners, np.float32).reshape(-1, 1, 2), detection.transform).reshape(-1, 2)
    assert np.allclose(projected, [[0, 0], [629, 0], [629, 879], [0, 879]], atol=0.01)
    assert np.isfinite(detection.transform).all()
    assert detection.normalized_image[440, 315].mean() > 150


def test_printed_frame_is_not_physical_boundary():
    assert_detected(scene(frame=True), CORNERS)


def assert_rejected(image, reasons=None, config=None):
    result = detect_boundary(image, config)
    assert result.result.status == "rejected"
    assert result.result.failure_reason
    if reasons:
        assert result.result.failure_reason in reasons
    assert result.result.corners is None
    assert result.normalized_image is None
    assert result.transform is None
    return result


def test_low_contrast():
    assert_rejected(scene(background=(200, 200, 200), color=(204, 204, 204), noise=1), {"no_card_outline"})


@pytest.mark.parametrize("points", [CORNERS - [280, 0], CORNERS - [0, 190], CORNERS + [280, 0], CORNERS + [0, 280]])
def test_clipped_card_even_with_printed_frame(points):
    assert_rejected(scene(points, frame=True), {"clipped_boundary", "nonuniform_background_or_clipping"})


def test_no_card():
    assert_rejected(np.full((760, 760, 3), 55, np.uint8), {"no_card_outline"})


def test_multiple_objects():
    first = scene(CORNERS - [190, 80])
    second = scene(CORNERS + [210, 130])
    assert_rejected(np.maximum(first, second), {"ambiguous_foreground"})


def test_invalid_aspect_ratio():
    square = np.array([[240, 160], [520, 160], [520, 440], [240, 440]], np.float32)
    assert_rejected(scene(square), {"implausible_aspect_ratio"})


def test_minimum_area():
    small = (CORNERS - CORNERS.mean(axis=0)) * 0.3 + [380, 380]
    assert_rejected(scene(small), {"invalid_geometry"})


def test_nonconvex_or_missing_corner():
    image = scene()
    cv2.fillPoly(image, [np.array([[430, 100], [530, 100], [530, 250], [430, 250]], np.int32)], (35, 35, 35))
    assert_rejected(image, {"not_convex_quadrilateral", "invalid_geometry"})


def test_unsharp_image():
    blurred = cv2.GaussianBlur(scene(), (31, 31), 2)
    assert_rejected(blurred, {"insufficient_sharpness_or_texture"})


def test_severely_blurred_image_is_also_rejected():
    assert_rejected(cv2.GaussianBlur(scene(), (31, 31), 6))


def test_visible_printed_frame_without_visible_physical_edge_is_rejected():
    image = scene(background=(200, 200, 200), color=(200, 200, 200), noise=0, frame=True)
    assert_rejected(image, {"insufficient_silhouette_support"})


def test_large_and_smaller_card_are_ambiguous():
    first = scene(CORNERS - [190, 80])
    smaller = (CORNERS - CORNERS.mean(axis=0)) * 0.6 + [575, 450]
    assert_rejected(np.maximum(first, scene(smaller)), {"ambiguous_foreground"})


def test_transform_validation():
    assert_rejected(scene(), {"invalid_perspective_transform"}, BoundaryConfig(max_transform_condition=1.01))


def test_nonuniform_background():
    image = scene()
    image[:20, :380] = (255, 255, 255)
    assert_rejected(image, {"nonuniform_background_or_clipping"})


@pytest.mark.parametrize("image", [None, np.zeros((10, 10, 3), np.uint8), np.zeros((100, 100), np.uint8), np.zeros((100, 100, 3), np.float32)])
def test_invalid_image_input(image):
    assert_rejected(image, {"invalid_image"})


def test_pixel_limit():
    assert_rejected(scene(), {"image_too_large"}, BoundaryConfig(max_input_pixels=100))


def test_corner_order_is_independent_of_input_order():
    assert np.array_equal(order_corners(CORNERS[[2, 0, 3, 1]]), CORNERS)
    diamond = np.array([[200, 0], [400, 200], [200, 400], [0, 200]], np.float32)
    assert np.array_equal(order_corners(diamond[[2, 1, 3, 0]]), diamond)
    with pytest.raises(ValueError):
        order_corners(np.array([[0, 0], [1, 1], [2, 2], [3, 3]]))


@pytest.mark.parametrize("settings", [{"min_area_fraction": 0}, {"min_aspect_ratio": 0.9}, {"max_background_variation": 20}, {"normalized_width": 0}])
def test_invalid_config(settings):
    with pytest.raises(ValidationError):
        BoundaryConfig(**settings)


@pytest.fixture
def stored_original(api, tmp_path):
    client, session, settings = api
    settings.max_image_size_bytes = 2_000_000
    settings.boundary_output_dir = tmp_path / "diagnostics"
    card = client.post("/api/cards", json={"card_name": "Pikachu", "set_name": "Base Set", "collector_number": "58"}).json()
    ok, encoded = cv2.imencode(".png", scene(frame=True))
    assert ok
    original = encoded.tobytes()
    response = client.post(f"/api/cards/{card['id']}/images", data={"side": "front"}, files={"file": ("front.png", original, "image/png")})
    assert response.status_code == 201
    record = session.get(CardImage, UUID(response.json()["id"]))
    return record, settings, session, original


def test_stored_original_and_separate_repeatable_diagnostics(stored_original):
    record, settings, session, original = stored_original
    source = settings.card_image_dir / record.storage_key
    before = source.stat()
    first = analyze_original(record, settings)
    second = analyze_original(record, settings)
    assert first.result.status == second.result.status == "detected"
    assert first.run_id != second.run_id
    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert hashlib.sha256(source.read_bytes()).hexdigest() == record.sha256
    assert session.scalar(select(func.count()).select_from(CardImage)) == 1
    for run in (first, second):
        folder = settings.boundary_output_dir / run.run_id.hex
        metadata = json.loads((folder / "result.json").read_text())
        assert metadata["source_sha256"] == record.sha256
        assert metadata["image_id"] == str(record.id)
        assert metadata["result"]["corners"] == run.result.corners
        assert "storage_key" not in metadata
        assert "confidence" not in metadata["result"]
        assert cv2.imread(str(folder / "normalized.png")).shape == (880, 630, 3)
        assert (folder / "mask.png").exists()
        assert (folder / "overlay.png").exists()


def test_original_integrity_failure(stored_original):
    record, settings, _, _ = stored_original
    source = settings.card_image_dir / record.storage_key
    source.write_bytes(b"simulated external corruption")
    result = analyze_original(record, settings)
    assert result.result.failure_reason == "original_integrity_mismatch"
    assert result.result.corners is None
    assert not (settings.boundary_output_dir / result.run_id.hex / "normalized.png").exists()
    assert source.read_bytes() == b"simulated external corruption"


def test_diagnostic_write_failure_preserves_original(stored_original, monkeypatch):
    record, settings, _, original = stored_original

    def fail(*args):
        raise OSError("simulated diagnostic failure")

    monkeypatch.setattr("app.boundary_storage.cv2.imencode", fail)
    with pytest.raises(OSError, match="simulated"):
        analyze_original(record, settings)
    assert list(settings.boundary_output_dir.iterdir()) == []
    assert (settings.card_image_dir / record.storage_key).read_bytes() == original


def test_diagnostics_cannot_overlap_originals(stored_original):
    record, settings, _, original = stored_original
    settings.boundary_output_dir = settings.card_image_dir / "diagnostics"
    with pytest.raises(ValueError, match="separate"):
        analyze_original(record, settings)
    assert (settings.card_image_dir / record.storage_key).read_bytes() == original


def test_invalid_storage_key_rejected(stored_original):
    record, settings, _, _ = stored_original
    record.storage_key = "../secret"
    with pytest.raises(ValueError, match="storage key"):
        analyze_original(record, settings)
