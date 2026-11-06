"""Offline semantic experiment runner; exclusive outputs, references post-scoring only."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from spectra_reference.inputs import load_bundle, read_json
from spectra_scanner.storage import sha256_file

from .semantic import OBJECTIVES, VERSION, analyze


def write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def transform(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(
        np.asarray(points, dtype=float).reshape(-1, 1, 2), matrix
    ).reshape(-1, 2)


def register(source: Any, target: Any, sc: Any, tc: Any) -> dict:
    """Independent print registration; no boundary/candidate geometry in the fit."""
    sift = cv2.SIFT_create(nfeatures=8000)  # type: ignore[attr-defined]  # OpenCV stub omits SIFT.
    features = []
    for rgb, corners in ((source, sc), (target, tc)):
        center = corners.mean(axis=0)
        mask = np.zeros(rgb.shape[:2], np.uint8)
        cv2.fillConvexPoly(
            mask, np.asarray(center + (corners - center) * 0.70, dtype=np.int32), 255
        )
        features.append(sift.detectAndCompute(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), mask))
    (ks, ds), (kt, dt) = features
    if ds is None or dt is None or min(len(ds), len(dt)) < 2:
        return dict(reliable=False, reason="insufficient_print_features")
    good = [
        m
        for pair in cv2.BFMatcher().knnMatch(ds, dt, k=2)
        if len(pair) == 2
        for m, n in [pair]
        if m.distance < 0.70 * n.distance
    ]
    if len(good) < 30:
        return dict(reliable=False, reason="insufficient_ratio_matches", matches=len(good))
    src = np.asarray([ks[m.queryIdx].pt for m in good], dtype=float)
    dst = np.asarray([kt[m.trainIdx].pt for m in good], dtype=float)
    cv2.setRNGSeed(2102)
    matrix, keep = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=2, maxIters=10000
    )
    if matrix is None:
        return dict(reliable=False, reason="registration_failed")
    selected = keep.ravel().astype(bool)
    src, dst = src[selected], dst[selected]
    span = np.ptp(dst, axis=0) / np.ptp(tc, axis=0)
    if len(src) < 30 or min(span) < 0.4:
        return dict(
            reliable=False,
            reason="insufficient_spatial_support",
            inliers=len(src),
            span_fraction=span.tolist(),
        )
    order = np.lexsort((src[:, 1], src[:, 0]))
    test = order[::5]
    train = np.setdiff1d(np.arange(len(src)), test)
    fitted, _ = cv2.estimateAffinePartial2D(src[train], dst[train], method=cv2.LMEDS)
    if fitted is None:
        return dict(reliable=False, reason="holdout_fit_failed")
    errors = np.linalg.norm(
        transform(src[test], np.vstack([fitted, [0, 0, 1]])) - dst[test], axis=1
    )
    p95 = float(np.percentile(errors, 95))
    return dict(
        reliable=p95 <= 2.5,
        reason="passed" if p95 <= 2.5 else "holdout_error",
        matrix=np.vstack([matrix, [0, 0, 1]]).tolist(),
        inliers=len(src),
        landmark_span_fraction=span.tolist(),
        holdout_n=len(test),
        holdout_rms_px=float(np.sqrt((errors**2).mean())),
        holdout_p95_px=p95,
    )


def associate(source: dict, target: dict, registration: dict) -> list[dict]:
    if not registration["reliable"]:
        return []
    ss = [h for h in source["frame_evaluation"]["hypotheses"] if h["geometrically_valid"]]
    tt = [h for h in target["frame_evaluation"]["hypotheses"] if h["geometrically_valid"]]
    if not ss or not tt:
        return []
    costs = np.zeros((len(ss), len(tt)))
    mappings = {}
    for i, s in enumerate(ss):
        points = transform(np.array(s["corners_pixels"]), np.array(registration["matrix"]))
        for j, t in enumerate(tt):
            candidates = [
                np.linalg.norm(
                    np.roll(points, shift, axis=0) - np.array(t["corners_pixels"]), axis=1
                )
                for shift in range(4)
            ]
            shift = min(range(4), key=lambda k: candidates[k].mean())
            costs[i, j] = candidates[shift].mean()
            mappings[i, j] = (shift, candidates[shift])
    result = []
    for i, s in enumerate(ss):
        j = int(np.argmin(costs[i]))
        shift, errors = mappings[i, j]
        others = sorted(costs[i])
        inverse = sorted(costs[:, j])
        gap = min(
            others[1] - others[0] if len(others) > 1 else float("inf"),
            inverse[1] - inverse[0] if len(inverse) > 1 else float("inf"),
        )
        mutual = int(np.argmin(costs[:, j])) == i
        matched = mutual and errors.max() <= 5 and gap > 2 * registration["holdout_p95_px"]
        result.append(
            dict(
                source_hypothesis=s["id"],
                target_hypothesis=tt[j]["id"] if matched else None,
                nearest_target=tt[j]["id"],
                reliable_match=bool(matched),
                reason="matched" if matched else "ambiguous_or_geometry_mismatch",
                cyclic_corner_shift=shift,
                corner_distances_px=errors.tolist(),
                separation_gap_px=float(gap) if np.isfinite(gap) else None,
            )
        )
    return result


def visual(rgb: np.ndarray, evaluation: dict, result: dict, path: Path) -> None:
    lookup = {c["id"]: c for s in evaluation["sides"] for c in s["candidates"]}
    frame_lookup = {h["id"]: h for h in evaluation["frame_evaluation"]["hypotheses"]}
    rows = result["hypotheses"]
    panel = Image.new("RGB", (1200, max(1, (len(rows) + 2) // 3) * 520), "white")
    if not rows:
        draw = ImageDraw.Draw(panel)
        draw.text(
            (20, 20),
            "No existing four-sided hypotheses; semantic evaluation abstains.",
            fill="black",
        )
        draw.text(
            (20, 45),
            f"Existing search truncated: {result['existing_search_truncated']}; existing status: {result['existing_status']}",
            fill="black",
        )
    for i, row in enumerate(rows):
        tile = Image.fromarray(rgb)
        draw = ImageDraw.Draw(tile)
        corners = np.array(frame_lookup[row["hypothesis_id"]].get("corners_pixels", []))
        if corners.shape == (4, 2):
            draw.line([tuple(p) for p in corners] + [tuple(corners[0])], fill="magenta", width=4)
        # Never draw a reference or promote the diagnostic leader to selected geometry.
        tile.thumbnail((400, 440))
        x, y = i % 3 * 400, i // 3 * 520
        panel.paste(tile, (x, y))
        text = ImageDraw.Draw(panel)
        base = row["views"].get("0.0:full", {})
        text.text(
            (x + 5, y + 445),
            f"{row['hypothesis_id']} Pareto front={base.get('pareto_front')}",
            fill="black",
        )
        obj = base.get("objectives") or {}
        text.text(
            (x + 5, y + 465),
            f"Continuity {obj.get('continuity', 0):.3f} | collar {obj.get('collar_consistency', 0):.3f}",
            fill="black",
        )
        text.text(
            (x + 5, y + 483),
            f"Global band {obj.get('global_band_consistency', 0):.3f} | difference {obj.get('region_difference', 0):.3f}",
            fill="black",
        )
        text.text((x + 5, y + 502), "Diagnostic only - review_required", fill="black")
        assert all(cid in lookup for cid in row["candidate_ids"])
    panel.save(path)


def run(data: Path, output: Path, reference_comparison: Path | None) -> None:
    output.mkdir(parents=True, exist_ok=False)
    reports = sorted((data / "s2_2b_validation").glob("*/pair-*-b/report.json"))
    if not reports:
        raise ValueError("No existing S2.2b validation reports")
    records: list[dict] = []
    unique: dict[str, tuple[Any, dict, dict, dict]] = {}
    protected = {}
    for i, path in enumerate(reports):
        saved = read_json(path)
        image = Path(saved["inputs"]["image_path"])
        rgb, evaluation, provenance = load_bundle(image, path)
        for p in (path, image, Path(provenance["s2_1"]["path"])):
            protected[str(p)] = sha256_file(p)
        before = json.dumps(evaluation, sort_keys=True)
        result = analyze(rgb, evaluation)
        assert before == json.dumps(evaluation, sort_keys=True)
        folder = output / f"capture-{i:03}"
        folder.mkdir()
        result.update(source_provenance=provenance, original_report=str(path.resolve()))
        write(folder / "semantic.json", result)
        visual(rgb, evaluation, result, folder / "hypotheses.png")
        records.append(
            dict(
                report=str(path.resolve()),
                image=str(image),
                image_sha256=provenance["image_sha256"],
                output=str(folder),
                hypotheses=len(result["hypotheses"]),
                leaders=result["leaders_by_view"]["0.0:full"],
                diagnostic_preference=result["diagnostic_preference"],
                abstained=result["abstained"],
                existing_status=evaluation["status"],
                truncated=result["existing_search_truncated"],
            )
        )
        unique.setdefault(provenance["image_sha256"], (rgb, evaluation, result, provenance))
        print(
            f"{i + 1}/{len(reports)} {len(result['hypotheses'])} hypotheses; leaders {records[-1]['leaders']}",
            flush=True,
        )
    # Commit all reference-free outputs before any manual comparison is read.
    write(
        output / "scores-complete.json",
        dict(
            algorithm_version=VERSION,
            manual_reference_used=False,
            records=records,
            unique_captures=len(unique),
        ),
    )
    groups = defaultdict(list)
    for sha, bundle in unique.items():
        groups[Path(bundle[3]["s2_1"]["path"]).parent.parent.name].append(sha)
    stability = []
    for group, keys in groups.items():
        for i in range(len(keys)):
            for j in range(i):
                source, target = unique[keys[i]], unique[keys[j]]
                registration = register(
                    source[0],
                    target[0],
                    np.array(source[1]["physical_corners_pixels"]),
                    np.array(target[1]["physical_corners_pixels"]),
                )
                matches = associate(source[1], target[1], registration)
                for match in matches:
                    if match["reliable_match"]:
                        a = next(
                            r
                            for r in source[2]["hypotheses"]
                            if r["hypothesis_id"] == match["source_hypothesis"]
                        )
                        b = next(
                            r
                            for r in target[2]["hypotheses"]
                            if r["hypothesis_id"] == match["target_hypothesis"]
                        )
                        av, bv = a["views"]["0.0:full"], b["views"]["0.0:full"]
                        match["objective_changes_source_minus_target"] = {
                            k: av["objectives"][k] - bv["objectives"][k] for k in OBJECTIVES
                        }
                        match["pareto_front_source_target"] = [
                            av["pareto_front"],
                            bv["pareto_front"],
                        ]
                stability.append(
                    dict(
                        series=group,
                        source_sha256=keys[i],
                        target_sha256=keys[j],
                        registration=registration,
                        associations=matches,
                    )
                )
    write(output / "stability.json", stability)
    post = None
    if reference_comparison is not None:
        reference_result = read_json(reference_comparison)
        protected[str(reference_comparison)] = sha256_file(reference_comparison)
        key = reference_result["provenance"]["image_sha256"]
        if key not in unique:
            raise ValueError("Reference image not among scored captures")
        scored = unique[key][2]
        metrics = {h["hypothesis_id"]: h for h in reference_result["hypotheses"]}
        post = dict(
            reference_comparison=str(reference_comparison),
            scored_before_reference_read=True,
            manual_reference_was_scoring_input=False,
            hypotheses=[
                dict(
                    hypothesis_id=h["hypothesis_id"],
                    semantic_front=h["views"]["0.0:full"]["pareto_front"],
                    reference_rank=metrics[h["hypothesis_id"]]["rank"],
                    reference_mae_px=metrics[h["hypothesis_id"]]["aggregate"][
                        "mean_absolute_pixels"
                    ],
                )
                for h in scored["hypotheses"]
            ],
            diagnostic_preference=scored["diagnostic_preference"],
            prior_exposure="exposed; manual geometry, not blinded ground truth",
        )
        write(output / "post-reference-evaluation.json", post)
    assert all(sha256_file(Path(p)) == sha for p, sha in protected.items())
    write(
        output / "evaluation.json",
        dict(
            records=records,
            unique_captures=len(unique),
            stability_pairs=len(stability),
            reference_evaluation=post,
            status="review_required",
            automatic_acceptance=False,
        ),
    )
    write(output / "integrity.json", dict(all_existing_inputs_unchanged=True, sha256=protected))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("local_data"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-comparison", type=Path)
    args = parser.parse_args()
    run(args.data_root.resolve(), args.output.resolve(), args.reference_comparison)


if __name__ == "__main__":
    main()
