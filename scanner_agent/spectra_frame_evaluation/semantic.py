"""Reference-free optical compatibility diagnostics; never a validity/selection gate."""

from __future__ import annotations

from typing import Any

import numpy as np

VERSION = "0.1.0-semantic-exp1"
PHASES = (-0.5, 0.0, 0.5)
OBJECTIVES = ("continuity", "collar_consistency", "global_band_consistency", "region_difference")


def sample(rgb: Any, xy: Any) -> tuple[Any, Any]:
    """Exact bilinear sampling, explicit invalid pixels (never black border fill)."""
    x, y = xy[..., 0], xy[..., 1]
    valid = (x >= 0) & (y >= 0) & (x <= rgb.shape[1] - 1) & (y <= rgb.shape[0] - 1)
    x = np.clip(x, 0, rgb.shape[1] - 1)
    y = np.clip(y, 0, rgb.shape[0] - 1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    jx, jy = np.minimum(ix + 1, rgb.shape[1] - 1), np.minimum(iy + 1, rgb.shape[0] - 1)
    fx, fy = (x - ix)[..., None], (y - iy)[..., None]
    values = (
        (1 - fx) * (1 - fy) * rgb[iy, ix]
        + fx * (1 - fy) * rgb[iy, jx]
        + (1 - fx) * fy * rgb[jy, ix]
        + fx * fy * rgb[jy, jx]
    )
    return values, valid


def histogram(values: Any) -> Any:
    v = np.asarray(values).reshape(-1, 3)
    return np.array([np.histogram(v[:, i], bins=16, range=(0, 256))[0] / len(v) for i in range(3)])


def distance(a: Any, b: Any) -> float:
    return float(np.abs(a - b).sum(axis=1).mean() / 2)


def side_samples(rgb: Any, physical: Any, index: int, line: Any, exclusion: float) -> dict:
    ends = physical[[index, (index + 1) % 4]]
    tangent = ends[1] - ends[0]
    tangent /= np.linalg.norm(tangent)
    normal = np.array([-tangent[1], tangent[0]])
    origins = ends[0] + np.linspace(exclusion, 1 - exclusion, 96)[:, None] * (ends[1] - ends[0])
    abc = np.asarray(line, dtype=float)
    if abc.shape != (3,) or not np.isfinite(abc).all():
        raise ValueError("Invalid finite candidate line")
    denominator = abc[:2] @ normal
    if abs(denominator) < 1e-8:
        raise ValueError("Candidate parallel to sampling rays")
    shifts = -(origins @ abc[:2] + abc[2]) / denominator
    if (shifts <= 0).any():
        raise ValueError("Nonpositive physical-to-frame corridor")
    centers = origins + shifts[:, None] * normal
    result = {}
    for phase in PHASES:
        raw = {}
        for name, offsets in (("outside", [-8, -4, -2]), ("inside", [2, 4, 8])):
            xy = centers[:, None, :] + (np.array(offsets)[None, :, None] + phase) * normal
            raw[name], raw[name + "_valid"] = sample(rgb, xy)
        xy = (
            origins[:, None, :]
            + (shifts[:, None, None] * np.linspace(0.1, 0.9, 16)[None, :, None] + phase) * normal
        )
        raw["corridor"], raw["corridor_valid"] = sample(rgb, xy)
        result[str(phase)] = raw
    return result


def describe(raw: dict, subset: slice) -> dict:
    out, inside, band = [raw[k][subset] for k in ("outside", "inside", "corridor")]
    valid = np.concatenate(
        [raw[k + "_valid"][subset].ravel() for k in ("outside", "inside", "corridor")]
    )
    if not valid.all():
        return {"available": False, "valid_fraction": float(valid.mean())}
    delta = inside[:, 0] - out[:, -1]  # symmetric +/-2px, unchanged geometry
    median = np.median(delta, axis=0)
    denom = np.linalg.norm(delta, axis=1) * np.linalg.norm(median)
    cosine = np.divide(delta @ median, denom, out=np.zeros(len(delta)), where=denom > 1e-8)
    ho, hi, hb = [histogram(v) for v in (out, inside, band)]
    return dict(
        available=True,
        valid_fraction=1.0,
        continuity=float(np.maximum(cosine, 0).mean()),
        transition_p10_rgb_rms=float(np.percentile(np.sqrt((delta**2).mean(axis=1)), 10)),
        along_side_rgb_rms=float(np.sqrt((np.diff(out.mean(axis=1), axis=0) ** 2).mean())),
        outside_median_rgb=np.median(out, axis=(0, 1)).tolist(),
        inside_median_rgb=np.median(inside, axis=(0, 1)).tolist(),
        corridor_std_rgb=np.std(band, axis=(0, 1)).tolist(),
        region_difference=distance(ho, hi),
        outside_histogram=ho.tolist(),
        inside_histogram=hi.tolist(),
        corridor_histogram=hb.tolist(),
    )


def objectives(sides: list[dict]) -> dict | None:
    if not all(s["available"] for s in sides):
        return None
    collar = [np.array(s["outside_histogram"]) for s in sides]
    bands = [np.array(s["corridor_histogram"]) for s in sides]
    return dict(
        continuity=min(s["continuity"] for s in sides),
        collar_consistency=1 - max(distance(a, b) for a in collar for b in collar),
        global_band_consistency=1 - max(distance(a, b) for a in bands for b in bands),
        region_difference=min(s["region_difference"] for s in sides),
    )


def fronts(values: list[dict | None]) -> list[int | None]:
    """Partial order; no ID/order/margin/area tie-breaking."""
    vectors = {
        i: np.array([v[k] for k in OBJECTIVES]) for i, v in enumerate(values) if v is not None
    }
    remaining = set(vectors)
    ranks: list[int | None] = [None] * len(values)
    rank = 1
    while remaining:
        top = []
        for i in remaining:
            a = vectors[i]
            dominated = False
            for j in remaining - {i}:
                b = vectors[j]
                if (b >= a - 1e-10).all() and (b > a + 1e-10).any():
                    dominated = True
                    break
            if not dominated:
                top.append(i)
        if not top:
            # Tolerance cycles cannot be resolved into an artificial preference.
            top = list(remaining)
        for i in top:
            ranks[i] = rank
        remaining.difference_update(top)
        rank += 1
    return ranks


def analyze(rgb: Any, evaluation: dict) -> dict:
    """Accept image + S2.2b only; manual references are absent from this API."""
    physical = np.array(evaluation["physical_corners_pixels"], dtype=float)
    lookup = {c["id"]: c for s in evaluation["sides"] for c in s["candidates"]}
    exclusion = evaluation["configuration"]["candidate_generation"]["corner_exclusion_fraction"]
    cache = {}
    rows = []
    for frame in evaluation["frame_evaluation"]["hypotheses"]:
        row = dict(
            hypothesis_id=frame["id"],
            candidate_ids=frame["candidate_ids"],
            existing_geometrically_valid=frame["geometrically_valid"],
            views={},
            unavailable_reason=None,
        )
        try:
            for phase in PHASES:
                for label, subset in (
                    ("full", slice(None)),
                    ("even", slice(0, None, 2)),
                    ("odd", slice(1, None, 2)),
                ):
                    sides = []
                    for i, cid in enumerate(frame["candidate_ids"]):
                        if cid not in cache:
                            cache[cid] = side_samples(
                                rgb, physical, i, lookup[cid]["line_abc"], exclusion
                            )
                        sides.append(describe(cache[cid][str(phase)], subset))
                    row["views"][f"{phase}:{label}"] = dict(
                        sides=sides, objectives=objectives(sides)
                    )
        except (ValueError, KeyError, FloatingPointError) as exc:
            row["unavailable_reason"] = str(exc)
            row["views"] = {}
        rows.append(row)
    view_keys = [f"{p}:{s}" for p in PHASES for s in ("full", "even", "odd")]
    leaders = {}
    for key in view_keys:
        values = [
            r["views"].get(key, {}).get("objectives") if r["existing_geometrically_valid"] else None
            for r in rows
        ]
        ranks = fronts(values)
        leaders[key] = [
            r["hypothesis_id"] for r, rank in zip(rows, ranks, strict=True) if rank == 1
        ]
        for row, rank in zip(rows, ranks, strict=True):
            if key in row["views"]:
                row["views"][key]["pareto_front"] = rank
    baseline = leaders["0.0:full"]
    complete = all(
        r["views"].get(k, {}).get("objectives") is not None for r in rows for k in view_keys
    )
    stable = len(baseline) == 1 and all(v == baseline for v in leaders.values())
    truncated = evaluation["frame_evaluation"]["search_truncated"]
    preferred = baseline[0] if len(rows) >= 2 and complete and stable and not truncated else None
    return dict(
        algorithm_version=VERSION,
        kind="semantic_frame_diagnostics",
        schema_version=1,
        status="review_required",
        automatic_acceptance=False,
        measurements=None,
        existing_status=evaluation["status"],
        existing_search_truncated=truncated,
        existing_selected_geometric_hypothesis_id=evaluation["frame_evaluation"][
            "selected_geometric_hypothesis_id"
        ],
        criteria_or_geometry_changed=False,
        manual_reference_used=False,
        objectives=list(OBJECTIVES),
        hypotheses=rows,
        leaders_by_view=leaders,
        diagnostic_preference=preferred,
        abstained=preferred is None,
        interpretation="Optical compatibility partial order only; never semantic truth, validity, physical accuracy or acceptance.",
    )
