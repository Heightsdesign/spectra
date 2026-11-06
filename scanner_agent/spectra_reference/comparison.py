from __future__ import annotations

from typing import Any

import numpy as np

from spectra_scanner.common import AgentError

from . import NAMES
from .geometry import displacement, dpi_scale, line, quad, supported_span
from .inputs import candidate_lookup, resolve_candidates, validate_annotation


def inventory(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Numerical duplicate detection, not a statement of indistinguishability in scans."""
    lookup = candidate_lookup(evaluation)
    frames = evaluation["frame_evaluation"]["hypotheses"]
    groups: list[dict[str, Any]] = []
    rows = []
    for frame in frames:
        try:
            candidates = resolve_candidates(frame, lookup)
            normalized = np.array([line(c["line_abc"]) for c in candidates])
            duplicate = next(
                (
                    g
                    for g in groups
                    if np.allclose(g["normalized_lines_abc"], normalized, atol=1e-8, rtol=0)
                ),
                None,
            )
            if duplicate is None:
                duplicate = {
                    "group_id": f"geometry-{len(groups):04}",
                    "hypothesis_ids": [],
                    "normalized_lines_abc": normalized.tolist(),
                }
                groups.append(duplicate)
            duplicate["hypothesis_ids"].append(frame["id"])
            rows.append(
                {
                    "hypothesis_id": frame["id"],
                    "candidate_ids": frame["candidate_ids"],
                    "geometry_group": duplicate["group_id"],
                }
            )
        except (AgentError, ValueError, TypeError) as exc:
            rows.append(
                {
                    "hypothesis_id": frame["id"],
                    "candidate_ids": frame.get("candidate_ids", []),
                    "geometry_group": None,
                    "reason": str(exc),
                }
            )
    combinations: dict[tuple[Any, ...], list[str]] = {}
    for frame in frames:
        combinations.setdefault(tuple(frame.get("candidate_ids", [])), []).append(frame["id"])
    return {
        "hypothesis_count": len(frames),
        "unique_geometries": len(groups),
        "geometry_groups": groups,
        "duplicated_combinations": [ids for ids in combinations.values() if len(ids) > 1],
        "rows": rows,
        "numerical_line_coefficient_tolerance": 1e-8,
        "warning": "Numerical geometry equality is not metrological accuracy or human visual equivalence.",
    }


def compare(
    evaluation: dict[str, Any], reference: dict[str, Any], provenance: dict[str, Any]
) -> dict[str, Any]:
    flags = validate_annotation(reference, evaluation, provenance)
    corners = np.asarray(evaluation["physical_corners_pixels"])
    lookup = candidate_lookup(evaluation)
    frames = evaluation["frame_evaluation"]["hypotheses"]
    exclusion = evaluation["configuration"]["candidate_generation"]["corner_exclusion_fraction"]
    support_config = [exclusion, 1 - exclusion]
    # All comparisons use the same reference-parameter interval per side. Pull
    # candidate support extents back through the reference-normal ray mapping.
    spans: list[Any] = []
    span_reasons = []
    for i, side in enumerate(reference["sides"]):
        limits = [list(side["valid_span_fraction"])]
        reasons = []
        if side["status"] == "annotated" and side.get("line_abc") is not None:
            relevant = set()
            for frame in frames:
                if frame.get("geometrically_valid") is True and not frame.get(
                    "s2_2c_input_exclusion"
                ):
                    try:
                        relevant.add(resolve_candidates(frame, lookup)[i]["id"])
                    except AgentError:
                        pass
            for cid in sorted(relevant):
                try:
                    limits.append(
                        supported_span(
                            corners, i, line(side["line_abc"]), lookup[cid][1], support_config
                        )
                    )
                except (AgentError, ValueError, TypeError):
                    reasons.append(cid + ": no usable support span")
        lo, hi = max(s[0] for s in limits), min(s[1] for s in limits)
        if hi <= lo or reasons:
            spans.append(None)
            reasons.append("no_common_supported_span")
        else:
            spans.append([float(lo), float(hi)])
        span_reasons.append(reasons)
    complete_reference = not flags
    reference_corners = (
        quad([s["line_abc"] for s in reference["sides"]], corners) if complete_reference else None
    )
    rows = []
    for frame in frames:
        row: dict[str, Any] = {
            "hypothesis_id": frame["id"],
            "candidate_ids": frame.get("candidate_ids", []),
            "geometrically_valid": frame.get("geometrically_valid") is True,
            "comparison_availability": "none",
            "per_side": {},
            "aggregate": None,
            "rank": None,
            "exclusion_reasons": [],
        }
        candidates: list[Any] = []
        if not row["geometrically_valid"]:
            row["exclusion_reasons"].append("hypothesis_geometrically_invalid")
        if frame.get("s2_2c_input_exclusion"):
            row["exclusion_reasons"].append(frame["s2_2c_input_exclusion"])
        try:
            candidates = resolve_candidates(frame, lookup)
        except AgentError as exc:
            row["exclusion_reasons"].append(str(exc))
            ids = frame.get("candidate_ids", [])
            candidates = [
                lookup[ids[i]][1]
                if i < len(ids) and ids[i] in lookup and lookup[ids[i]][0] == i
                else None
                for i in range(4)
            ]
        if reference["layout_status"] != "supported":
            row["exclusion_reasons"].append("reference_layout_not_supported")
        errors = []
        for i, name in enumerate(NAMES):
            side = reference["sides"][i]
            if (
                not candidates
                or candidates[i] is None
                or side["status"] != "annotated"
                or reference["layout_status"] != "supported"
                or spans[i] is None
            ):
                row["per_side"][name] = {
                    "available": False,
                    "reason": "reference_" + side["status"]
                    if side["status"] != "annotated"
                    else "missing_candidate_layout_or_common_span",
                }
                continue
            try:
                ts = np.linspace(spans[i][0], spans[i][1], 51)
                signed, origins, targets, normal = displacement(
                    corners, i, side["line_abc"], candidates[i]["line_abc"], ts
                )
                scale = dpi_scale(provenance["dpi"], normal)
                absolute = np.abs(signed)
                row["per_side"][name] = {
                    "available": True,
                    "span_fraction": spans[i],
                    "samples": 51,
                    "reference_points_pixels": origins.tolist(),
                    "hypothesis_points_pixels": targets.tolist(),
                    "signed_displacements_pixels": signed.tolist(),
                    "absolute_displacements_pixels": absolute.tolist(),
                    "mean_signed_pixels": float(signed.mean()),
                    "mean_absolute_pixels": float(absolute.mean()),
                    "maximum_absolute_pixels": float(absolute.max()),
                    "rms_pixels": float(np.sqrt(np.mean(signed**2))),
                    "millimeters_from_reported_dpi": None
                    if scale is None
                    else {
                        "signed_displacements": (signed * scale).tolist(),
                        "mean_signed": float(signed.mean() * scale),
                        "mean_absolute": float(absolute.mean() * scale),
                        "maximum_absolute": float(absolute.max() * scale),
                    },
                }
                errors.append(signed)
            except (AgentError, ValueError, TypeError) as exc:
                row["per_side"][name] = {"available": False, "reason": str(exc)}
        if errors:
            row["comparison_availability"] = "complete" if len(errors) == 4 else "partial"
            all_errors = np.concatenate(errors)
            row["aggregate"] = {
                "compared_sides": len(errors),
                "mean_absolute_pixels": float(np.abs(all_errors).mean()),
                "maximum_absolute_pixels": float(np.abs(all_errors).max()),
                "rms_pixels": float(np.sqrt(np.mean(all_errors**2))),
                "ranking_basis": "equal per-side weight, 51 equal reference-parameter samples per common span",
            }
        if not complete_reference:
            row["exclusion_reasons"].append("reference_incomplete_ambiguous_or_inconsistent")
        if len(errors) != 4:
            row["exclusion_reasons"].append("incomplete_side_comparison")
        if (
            reference_corners is not None
            and candidates
            and all(c is not None for c in candidates)
            and row["geometrically_valid"]
            and not frame.get("s2_2c_input_exclusion")
        ):
            try:
                candidate_corners = quad([c["line_abc"] for c in candidates], corners)
                delta = candidate_corners - reference_corners
                scale = dpi_scale(provenance["dpi"], np.array([1.0, 0.0]))
                row["corner_differences"] = {
                    "delta_pixels": delta.tolist(),
                    "distance_pixels": np.linalg.norm(delta, axis=1).tolist(),
                    "delta_mm_from_reported_dpi": None
                    if scale is None
                    else (delta * 25.4 / np.asarray(provenance["dpi"])).tolist(),
                }
            except (AgentError, ValueError, TypeError) as exc:
                row["corner_exclusion_reason"] = str(exc)
        rows.append(row)
    eligible = sorted(
        [r for r in rows if not r["exclusion_reasons"]],
        key=lambda r: (r["aggregate"]["mean_absolute_pixels"], r["hypothesis_id"]),
    )
    rank, previous = 0, None
    for row in eligible:
        error = row["aggregate"]["mean_absolute_pixels"]
        if previous is None or abs(error - previous) > 1e-9:
            rank += 1
        row["rank"] = rank
        previous = error
    return {
        "status": "review_required",
        "automatic_acceptance": False,
        "reference_quality_flags": flags,
        "upstream_quality_flags": evaluation.get("quality_flags", []),
        "upstream_status": evaluation["status"],
        "search_truncated": evaluation["frame_evaluation"]["search_truncated"],
        "common_spans_fraction": dict(zip(NAMES, spans, strict=True)),
        "span_exclusions": dict(zip(NAMES, span_reasons, strict=True)),
        "hypotheses": rows,
        "ranked_hypothesis_ids": [r["hypothesis_id"] for r in eligible],
        "duplicate_inventory": inventory(evaluation),
        "sign_convention": "Positive = hypothesis inward from reference along reference unit normal oriented toward card interior",
        "interpretation": "Ranking measures agreement with a manual reference, never correctness, detection repeatability, physical accuracy, or a grade. Lowest error is not automatic validation. Support extents do not certify every intervening pixel.",
    }
