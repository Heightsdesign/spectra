# Physical boundary detector (milestone 3.1)

This is an acquisition-constrained, deterministic prototype, validated on synthetic fixtures. It does not identify cards, measure centering, authenticate cards, assign grades, or establish statistically calibrated confidence. Every result requires visual review.

## Entry points

`app.boundary.detect_boundary(image, BoundaryConfig(...))` accepts an 8-bit BGR NumPy array and never mutates it. It returns a `BoundaryDetection`: structured `result`, a normalized BGR image on success, diagnostic foreground mask and overlay when available, and the source-to-output transformation. `result.to_dict()` is JSON-compatible.

`app.boundary_storage.analyze_original(card_image, settings, config)` accepts an existing SQLAlchemy `CardImage` record. It reads the generated storage key from `settings.card_image_dir`, verifies recorded size and SHA-256 before decoding, and performs no database writes. Example from a Python session started in `backend`:

```python
from uuid import UUID
from sqlalchemy.orm import Session
from app.boundary import BoundaryConfig
from app.boundary_storage import analyze_original
from app.config import get_settings
from app.database import get_engine
from app.models import CardImage

with Session(get_engine()) as session:
    original = session.get(CardImage, UUID("REPLACE-WITH-EXISTING-IMAGE-ID"))
    if original is None:
        raise ValueError("Image not found")
    analysis = analyze_original(original, get_settings(), BoundaryConfig())
    print(analysis.result.to_dict())
```

The opt-in [local real-image validation workflow](REAL_IMAGE_VALIDATION.md) exposes internal analysis, diagnostic and review endpoints. Existing card API behavior and database schemas are unchanged.

## Coordinates and diagnostics

Coordinates are floating point `(x, y)` in decoded source pixels, with `(0, 0)` at the image top-left. Four corners are clockwise: top-left, top-right, bottom-right, bottom-left. The start is the minimum `x+y` corner, breaking diagonal ties by smaller `y`, then smaller `x`. This image-relative convention does not identify the top of the printed artwork. Sorting never substitutes a minimum-area rectangle or extrapolates a hidden corner.

Normalized output defaults to 630 × 880 pixels, using the nominal Pokémon 63:88 portrait format. When the first ordered edge is the long edge, the normalization cycles the corner list once; `normalization_corner_rotation` records that shift. The reported corners retain their image-relative order. `transform` maps source pixels to normalized pixels and is saved in diagnostics. Perspective resampling affects only the derived image.

`BOUNDARY_OUTPUT_DIR` defaults to `backend/data/boundary_diagnostics`, separate from original storage. Each run gets a generated UUID directory containing `result.json`, and, when available, `mask.png`, `overlay.png`, and `normalized.png`. Metadata records the original image ID and checksum, algorithm version, UTC run timestamp, library versions, configuration, metrics, warnings and transformation. No original filename or API-provided path selects an output location. Storage keys, resolved source containment and separation of the two storage trees are validated. Files are created exclusively; repeated analyses cannot overwrite prior runs. Partial diagnostic runs are removed on write errors, which propagate to the caller. Failed source checks/detection still produce a structured rejected result and metadata, without a normalized image.

The adapter explicitly disables automatic EXIF rotation. Coordinates therefore address the encoded raster, not an EXIF-oriented viewer. Only single-frame images are analyzed; multi-page TIFF is rejected rather than selecting a page silently. Analysis converts supported images to 8-bit BGR; original bytes, EXIF, bit depth, and color profiles remain preserved in original storage. ICC profiles are not applied during analysis.

## Detection approach

1. Apply a 3 × 3 Gaussian blur for segmentation and convert to OpenCV's 8-bit Lab representation.
2. Estimate the background from the median perimeter color and reject excessive perimeter variation.
3. Threshold distance from that background and inspect **external** connected contours. This does not depend on a printed border. Require strong foreground fill so a hollow printed frame alone cannot establish a physical silhouette.
4. Approximate observed contours with polygons. Require four vertices, convexity, sufficient area and side lengths, plausible aspect ratio, solidity, small polygon approximation error, bounded angles, and bounded opposite-edge asymmetry. Do not fit a replacement rectangle. Reject contours near the image boundary and multiple substantial silhouettes, including smaller distractors.
5. Measure Laplacian variance within the silhouette eroded by seven pixels, excluding the physical edge. Reject insufficient sharpness/texture.
6. Check finite, nonsingular and conditioned projective transforms, inverse sampling bounds and absence of a projective horizon across the output before warping.

Rejected results contain a failure reason and available dimensions/metrics; they do not contain accepted corners, a transform, or a normalized image. An overlay may show a rejected geometric proposal for diagnosis only.

## Default thresholds

All thresholds are validated fields of immutable `BoundaryConfig`; pass overrides explicitly and retain them in the run metadata. They are engineering heuristics, not measured error probabilities.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `background_distance` | 18 | Euclidean distance in OpenCV 8-bit Lab for foreground segmentation; not standard Delta E |
| `max_background_variation` | 12 | Maximum 95th-percentile perimeter distance from background |
| `min_area_fraction` | 0.10 | Minimum accepted quadrilateral area / image area |
| `min_ambiguity_area_fraction` | 0.01 | Significant silhouette area; multiple such objects reject the image |
| `min_aspect_ratio`, `max_aspect_ratio` | 0.58, 0.86 | Short/long mean opposite-edge ratio; nominal card ratio is about 0.716 |
| `min_solidity` | 0.97 | Contour area / convex hull area |
| `min_foreground_fill` | 0.90 | Segmented foreground coverage inside a candidate silhouette |
| `max_polygon_area_error` | 0.04 | Relative area difference between contour and approximated quadrilateral |
| `approximation_fraction` | 0.015 | Polygon simplification tolerance / contour perimeter |
| `min_corner_angle` | 50° | Angles must lie between 50° and 130° |
| `max_opposite_side_ratio` | 1.8 | Maximum asymmetry between opposite sides |
| `border_margin_pixels` | 4 | Required clearance from all image boundaries |
| `min_side_pixels` | 30 | Minimum observed quadrilateral side length |
| `min_sharpness` | 20 | Interior grayscale Laplacian variance; texture and resolution dependent |
| `max_input_pixels` | 24,000,000 | Decoded pixel ceiling; adapter checks dimensions before OpenCV decoding |
| `normalized_width`, `normalized_height` | 630, 880 | Derived image dimensions |
| `max_transform_condition` | 10,000 | Maximum matrix condition number in unit source/output coordinates |

## Limitations and acquisition guidance

Use a contrasting matte, uniform surface, diffuse light, one unsleeved card, all edges visible, and a roughly overhead camera. The detector deliberately rejects some valid photographs: strongly textured/gradient backgrounds, low contrast, reflections, large shadows, blank/blurred interiors, severe perspective, small cards and heavy damage. Rounded corners may shift contour-supported corner estimates; synthetic corner tolerance is four pixels, not a real-photo accuracy guarantee. Approximate edge ratios are perspective-dependent; rectification imposes a nominal card ratio and cannot recover physical dimensions without camera calibration.

Uniform-background segmentation cannot prove that a contour is a physical card. A solid printed rectangle on an otherwise invisible card, a sleeve, slab, shadow or another similarly shaped object can be indistinguishable from a physical silhouette. The hollow-frame safeguard only addresses one such failure mode. No detector based on these pixels can recover boundaries with no visible evidence. Do not treat successful detection as certification or use it without reviewing overlay and source. Real photographs, annotated ground truth and controlled acquisition testing are required before production use or downstream quantitative measurements.

Diagnostic outputs are private local artifacts and are ignored by Git under `data/`. This adapter retains the existing filesystem/database crash-consistency limitation; production still needs reconciliation and backup policy. No new image-analysis database records are created.

## Tests

From `backend`, run `.\.venv\Scripts\python.exe -m pytest` for all tests, including PostgreSQL-backed original-storage integration. Pure synthetic tests can run without PostgreSQL with `.\.venv\Scripts\python.exe -m pytest tests/test_boundary.py -k "not stored and not original and not diagnostic and not storage_key"`. Test/cache directories remain configured by `pytest.ini`.
