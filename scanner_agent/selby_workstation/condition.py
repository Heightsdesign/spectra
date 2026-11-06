"""Experimental condition diagnostics. No defect inference or grading decisions."""

from copy import deepcopy
from uuid import UUID, uuid4

import cv2
import numpy as np

from spectra_physical_reference.model import intersections
from spectra_reference import NAMES
from spectra_scanner.common import utc_now

from .inspection import group_valid

CATEGORIES = ("corners", "edges", "surface")
TYPES = (
    "whitening_indicator",
    "local_contrast",
    "color_discontinuity",
    "contour_deviation",
    "scratch",
    "dent",
    "wear",
    "artwork_or_texture",
    "other",
)
LIMITATION = "Experimental visual indicators can be artwork, foil or halftone. No suggestion is a confirmed defect without operator review."


def state(session):
    return session.data.setdefault(
        "condition", dict(schema_version=1, runs=[], findings=[], reviews={})
    )


def physical(session):
    if not group_valid(session, "physical"):
        raise ValueError(
            "Validate all four certain physical boundaries before extracting condition regions"
        )
    return np.asarray(
        intersections(
            [s["line_abc"] for s in session.data["physical"]], session.identity["dimensions"]
        ),
        dtype=float,
    )


def map_points(matrix, points):
    points = np.asarray(points, dtype=float)
    return (np.c_[points, np.ones(len(points))] @ np.asarray(matrix).T)[:, :2]


def extract(rgb, matrix, width, height, category, name, boundary_y=None):
    """One output pixel step equals one original pixel along each orthonormal axis."""
    yy, xx = np.indices((height, width), dtype=np.float32)
    matrix = np.asarray(matrix, dtype=float)
    mx = (matrix[0, 0] * xx + matrix[0, 1] * yy + matrix[0, 2]).astype(np.float32)
    my = (matrix[1, 0] * xx + matrix[1, 1] * yy + matrix[1, 2]).astype(np.float32)
    valid = (mx >= 0) & (my >= 0) & (mx <= rgb.shape[1] - 1) & (my <= rgb.shape[0] - 1)
    image = cv2.remap(rgb, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    meta = dict(
        category=category,
        name=name,
        dimensions=[width, height],
        patch_to_original=matrix.tolist(),
        interpolation="bilinear",
        units="original image pixels",
        boundary_y=boundary_y,
        valid_fraction=float(valid.mean()),
    )
    return dict(rgb=image, valid=valid, metadata=meta)


def regions(session, category):
    corners = physical(session)
    lengths = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    radius = max(12, min(256, int(min(lengths) * 0.06)))
    result = []
    if category == "surface":
        h, w = session.rgb.shape[:2]
        item = dict(
            rgb=session.rgb,
            valid=np.zeros((h, w), np.uint8),
            metadata=dict(
                category=category,
                name="full_scan",
                dimensions=[w, h],
                patch_to_original=np.eye(3).tolist(),
                interpolation="none",
                units="original image pixels",
                boundary_y=None,
            ),
        )
        cv2.fillConvexPoly(item["valid"], np.rint(corners).astype(np.int32), 1)
        item["valid"] = cv2.erode(item["valid"], np.ones((9, 9), np.uint8)).astype(bool)
        item["metadata"]["valid_fraction"] = float(item["valid"].mean())
        return [item]
    for i, name in enumerate(NAMES):
        tangent = (corners[(i + 1) % 4] - corners[i]) / lengths[i]
        normal = np.array([-tangent[1], tangent[0]])
        if category == "corners":
            origin = corners[i] - radius * tangent - radius * normal
            width, height, boundary_y = 2 * radius + 1, 2 * radius + 1, radius
        elif category == "edges":
            origin = corners[i] - radius * normal
            width, height, boundary_y = int(np.ceil(lengths[i])) + 1, 2 * radius + 1, radius
        else:
            raise ValueError("Unknown condition category")
        matrix = np.array(
            [[tangent[0], normal[0], origin[0]], [tangent[1], normal[1], origin[1]], [0, 0, 1]]
        )
        result.append(
            extract(
                session.rgb,
                matrix,
                width,
                height,
                category,
                ("top_left", "top_right", "bottom_right", "bottom_left")[i]
                if category == "corners"
                else name,
                boundary_y,
            )
        )
    return result


def polygon_for_box(meta, box, size):
    x, y, w, h = box
    polygon = map_points(
        meta["patch_to_original"], [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    )
    # Clip to decoded original bounds; invalid sampling pixels never become evidence.
    polygon[:, 0] = np.clip(polygon[:, 0], 0, size[0] - 1)
    polygon[:, 1] = np.clip(polygon[:, 1], 0, size[1] - 1)
    return polygon.tolist()


def indicators(region):
    rgb = region["rgb"]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    valid = cv2.erode(region["valid"].astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    meta = region["metadata"]
    if meta["category"] == "edges":
        # Only the card-facing half is used for photometric suggestions.
        valid[: meta["boundary_y"] + 2] = False
    elif meta["category"] == "corners":
        valid[: meta["boundary_y"] + 2] = False
        valid[:, : meta["boundary_y"] + 2] = False
    if not valid.any():
        return []
    residual = np.abs(gray - cv2.GaussianBlur(gray, (0, 0), 3))
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    gradient = np.maximum.reduce(
        [
            cv2.magnitude(
                cv2.Sobel(rgb[:, :, i].astype(np.float32), cv2.CV_32F, 1, 0, ksize=3) / 8,
                cv2.Sobel(rgb[:, :, i].astype(np.float32), cv2.CV_32F, 0, 1, ksize=3) / 8,
            )
            for i in range(3)
        ]
    )
    median = float(np.median(residual[valid]))
    mad = float(np.median(np.abs(residual[valid] - median)))
    threshold = max(20.0, median + 6 * max(mad, 1.0))
    saturation = rgb.max(axis=2).astype(float) - rgb.min(axis=2)
    masks = [
        (
            "whitening_indicator",
            (gray > 225) & (saturation < 35) & (residual > 10),
            dict(luminance_min=225, chroma_range_max=35, residual_min=10),
        ),
        (
            "local_contrast",
            residual > threshold,
            dict(residual_threshold=threshold, median_residual=median, mad_residual=mad),
        ),
        (
            "color_discontinuity",
            gradient > max(35.0, float(np.percentile(gradient[valid], 99))),
            dict(gradient_threshold=max(35.0, float(np.percentile(gradient[valid], 99)))),
        ),
    ]
    output = []
    for kind, mask, rule in masks:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            (mask & valid).astype(np.uint8), 8
        )
        candidates = sorted(range(1, count), key=lambda i: int(stats[i, 4]), reverse=True)
        for index in candidates:
            x, y, w, h, area = map(int, stats[index])
            if area < 4 or area > valid.sum() * 0.1:
                continue
            selected = labels[y : y + h, x : x + w] == index
            output.append(
                dict(
                    type=kind,
                    box=[x, y, w, h],
                    evidence=dict(
                        rule=rule,
                        connected_pixels=area,
                        mean_luminance=float(gray[y : y + h, x : x + w][selected].mean()),
                        mean_local_residual=float(residual[y : y + h, x : x + w][selected].mean()),
                        mean_gradient=float(gradient[y : y + h, x : x + w][selected].mean()),
                    ),
                )
            )
            if sum(o["type"] == kind for o in output) >= 4:
                break
    if meta["category"] in ("edges", "corners"):
        by = meta["boundary_y"]
        lo, hi = max(1, by - 8), min(gray.shape[0] - 1, by + 9)
        peak = np.argmax(np.abs(gy[lo:hi]), axis=0) + lo
        strength = np.max(np.abs(gy[lo:hi]), axis=0)
        good = (strength > 20) & (np.abs(peak - by) > 3)
        good &= region["valid"][peak, np.arange(len(peak))]
        # Require a contiguous excursion of at least eight pixels, excluding corners.
        good[: by + 4] = False
        good[-(by if meta["category"] == "edges" else 4) :] = False
        count, _, stats, _ = cv2.connectedComponentsWithStats(good[None, :].astype(np.uint8), 8)
        for x, _, w, _, _ in sorted(stats[1:count], key=lambda s: int(s[2]), reverse=True)[:4]:
            if w >= 8:
                output.append(
                    dict(
                        type="contour_deviation",
                        box=[int(x), lo, int(w), hi - lo],
                        evidence=dict(
                            rule="Strongest normal luminance gradient displaced >3 px over >=8 px",
                            median_offset_pixels=float(np.median(peak[x : x + w] - by)),
                            caveat="May be a nearby printed edge, not the physical contour",
                        ),
                    )
                )
    return output


def run_diagnostic(session, category):
    session.validate()
    extracted = regions(session, category)
    run = dict(
        id=str(uuid4()),
        algorithm="selby_condition_visual_0.1.0",
        opencv_version=cv2.__version__,
        parameters=dict(
            whitening_luminance_min=225,
            whitening_channel_range_max=35,
            whitening_residual_min=10,
            residual_sigma_pixels=3,
            residual_floor=20,
            residual_mad_multiplier=6,
            rgb_gradient_floor=35,
            rgb_gradient_percentile=99,
            component_min_pixels=4,
            component_max_valid_fraction=0.1,
            component_limit_per_type_per_region=4,
            contour_search_halfwidth_pixels=8,
            contour_gradient_min=20,
            contour_displacement_pixels=3,
            contour_min_run_pixels=8,
        ),
        category=category,
        at_utc=utc_now(),
        image=deepcopy(session.data["image"]),
        sources=deepcopy(session.data["sources"]),
        physical_validation=deepcopy(session.data["boundary_validation"]["physical"]),
        regions=[r["metadata"] for r in extracted],
        limitation=LIMITATION,
        operator=session.data["operator"],
        face=session.data.get("inspection_face", "unspecified"),
    )
    findings = []
    for region in extracted:
        for indicator in indicators(region):
            findings.append(
                dict(
                    id=str(uuid4()),
                    category=category,
                    region=region["metadata"]["name"],
                    origin="experimental_suggestion",
                    run_id=run["id"],
                    type=indicator["type"],
                    polygon_original=polygon_for_box(
                        region["metadata"], indicator["box"], session.identity["dimensions"]
                    ),
                    evidence=dict(indicator["evidence"], patch_box=indicator["box"]),
                    decision="unreviewed",
                    notes="",
                    operator=None,
                    reviewed_at_utc=None,
                    history=[],
                )
            )
    data = state(session)
    data["runs"].append(run)
    data["findings"].extend(findings)
    data["reviews"].pop(category, None)
    return extracted, findings


def manual_finding(session, category, polygon, kind, notes):
    if not session.data["operator"].strip() or not notes.strip():
        raise ValueError("Manual findings require operator identity and an evidence note")
    finding = dict(
        id=str(uuid4()),
        category=category,
        region="manual",
        origin="manual",
        run_id=None,
        type=kind,
        polygon_original=np.asarray(polygon, dtype=float).tolist(),
        evidence=dict(description=notes),
        decision="confirmed",
        notes=notes,
        operator=session.data["operator"],
        reviewed_at_utc=utc_now(),
        history=[],
    )
    validate_finding(finding, session.identity["dimensions"])
    state(session)["findings"].append(finding)
    state(session)["reviews"].pop(category, None)
    return finding


def decide(session, finding_id, decision, kind, notes):
    if decision not in ("confirmed", "rejected", "reclassified") or kind not in TYPES:
        raise ValueError("Unknown finding decision/type")
    if not session.data["operator"].strip() or not notes.strip():
        raise ValueError("Record operator identity and a reason for the decision")
    finding = next(f for f in state(session)["findings"] if f["id"] == finding_id)
    finding["history"].append(
        {
            k: deepcopy(finding[k])
            for k in ("type", "decision", "notes", "operator", "reviewed_at_utc")
        }
    )
    finding.update(
        decision=decision,
        type=kind,
        notes=notes,
        operator=session.data["operator"],
        reviewed_at_utc=utc_now(),
    )
    state(session)["reviews"].pop(finding["category"], None)


def category_status(session, category):
    data = session.data.get("condition", {})
    findings = current_findings(session, category)
    if not diagnostic_current(session, category):
        return "geometry_changed_review_required"
    stamp = data.get("reviews", {}).get(category)
    if (
        stamp
        and stamp["findings"] == findings
        and stamp["operator"] == session.data["operator"]
        and stamp["physical_validation"]
        == session.data.get("boundary_validation", {}).get("physical")
        and (category == "surface" or group_valid(session, "physical"))
    ):
        return "operator_reviewed"
    if any(f["decision"] == "unreviewed" for f in findings):
        return "suggestions_pending"
    return (
        "in_progress"
        if findings or any(r["category"] == category for r in data.get("runs", []))
        else "not_inspected"
    )


def complete_category(session, category, notes):
    if not session.data["operator"].strip() or not notes.strip():
        raise ValueError("Category review requires operator identity and a review note")
    if not diagnostic_current(session, category):
        raise ValueError(
            "Diagnostic geometry changed; rerun this category before completing review"
        )
    findings = current_findings(session, category)
    if any(f["decision"] == "unreviewed" for f in findings):
        raise ValueError("Review all suggestions in this category first")
    if category != "surface":
        physical(session)
    state(session)["reviews"][category] = dict(
        findings=deepcopy(findings),
        operator=session.data["operator"],
        at_utc=utc_now(),
        notes=notes,
        physical_validation=deepcopy(session.data.get("boundary_validation", {}).get("physical")),
    )


def current_findings(session, category):
    data = session.data.get("condition", {})
    runs = [r for r in data.get("runs", []) if r["category"] == category]
    latest = runs[-1]["id"] if runs else None
    return [
        f
        for f in data.get("findings", [])
        if f["category"] == category
        and (
            f["origin"] == "manual"
            or f["run_id"] == latest
            or f["decision"] in ("confirmed", "reclassified")
        )
    ]


def diagnostic_current(session, category):
    runs = [
        r for r in session.data.get("condition", {}).get("runs", []) if r["category"] == category
    ]
    return not runs or (
        group_valid(session, "physical")
        and runs[-1]["physical_validation"]
        == session.data.get("boundary_validation", {}).get("physical")
    )


def validate_finding(finding, size):
    UUID(finding["id"])
    if (
        finding["category"] not in CATEGORIES
        or finding["type"] not in TYPES
        or finding["decision"] not in ("unreviewed", "confirmed", "rejected", "reclassified")
        or finding["origin"] not in ("manual", "experimental_suggestion")
    ):
        raise ValueError("Invalid condition finding")
    polygon = np.asarray(finding["polygon_original"], dtype=float)
    if (
        polygon.shape != (4, 2)
        or not np.isfinite(polygon).all()
        or (polygon < 0).any()
        or (polygon[:, 0] > size[0] - 1).any()
        or (polygon[:, 1] > size[1] - 1).any()
        or abs(cv2.contourArea(polygon.astype(np.float32))) < 0.5
    ):
        raise ValueError("Finding must have four finite original-image coordinates")
    if finding["decision"] != "unreviewed" and (
        not finding["operator"] or not finding["reviewed_at_utc"] or not finding["notes"].strip()
    ):
        raise ValueError("Reviewed finding requires operator, time and evidence note")


def validate_condition(session):
    data = session.data.get("condition")
    if data is None:
        return
    if (
        data.get("schema_version") != 1
        or not isinstance(data.get("runs"), list)
        or not isinstance(data.get("findings"), list)
        or not isinstance(data.get("reviews"), dict)
    ):
        raise ValueError("Invalid condition schema")
    ids = set()
    for run in data["runs"]:
        UUID(run["id"])
        if (
            run["id"] in ids
            or run["category"] not in CATEGORIES
            or run["image"] != session.data["image"]
            or any(s not in session.data["sources"] for s in run["sources"])
        ):
            raise ValueError("Condition diagnostic provenance mismatch")
        ids.add(run["id"])
    finding_ids = set()
    for finding in data["findings"]:
        validate_finding(finding, session.identity["dimensions"])
        if finding["id"] in finding_ids or (
            finding["origin"] == "experimental_suggestion" and finding["run_id"] not in ids
        ):
            raise ValueError("Missing diagnostic provenance or duplicate finding")
        finding_ids.add(finding["id"])
    if data["reviews"].keys() - set(CATEGORIES):
        raise ValueError("Unknown category review")
