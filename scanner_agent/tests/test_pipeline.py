# ruff: noqa: E402
"""Isolated orchestrator fixtures; fake acquisition never touches scanner hardware."""

import contextlib
import io
import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")
from test_centering import fixture

import reference_frames
from spectra_boundary.config import load as physical_defaults
from spectra_centering.analysis import analyze as analyze_a
from spectra_centering.config import validate as frame_defaults
from spectra_frame_evaluation.analysis import analyze as analyze_b
from spectra_frame_evaluation.analysis import configuration
from spectra_pipeline import engine
from spectra_pipeline.contracts import read_json
from spectra_pipeline.dashboard import batch_dashboard
from spectra_scanner.common import identifier, write_json_new
from spectra_scanner.storage import sha256_file


class FixtureRunner:
    def __init__(self, root: Path, image: Path, physical: Path):
        self.root, self.image, self.physical = root, image, physical
        self.calls: list[str] = []

    def __call__(self, command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        script = Path(command[1]).name
        self.calls.append(script)
        folder = self.root / identifier()
        folder.mkdir(parents=True)
        if script == "analyze_boundaries.py":
            value = read_json(self.physical)
            scan = folder / "scan-000"
            scan.mkdir()
            write_json_new(scan / "report.json", value)
            write_json_new(
                folder / "report.json",
                {
                    "schema_version": 1,
                    "kind": "analysis_index",
                    "status": value["status"],
                    "analysis": "scan-000/report.json",
                },
            )
            status = value["status"]
        elif script == "analyze_printed_frame.py":
            value = analyze_a(
                Path(command[2]), Path(command[3]), folder / "scan", frame_defaults({})
            )
            folder = folder / "scan"
            status = value["status"]
        elif script == "evaluate_printed_frames.py":
            value = analyze_b(
                Path(command[2]), Path(command[3]), folder / "scan", configuration({})
            )
            folder = folder / "scan"
            status = value["status"]
        elif script == "reference_frames.py":
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = reference_frames.main(command[2:])
            return subprocess.CompletedProcess(command, code, stream.getvalue(), "")
        elif script == "acquire.py":
            acquisition = Path(command[command.index("--data-dir") + 1])
            capture = acquisition / "captures" / "synthetic-capture"
            capture.mkdir(parents=True)
            original = capture / "original.bmp"
            original.write_bytes(self.image.read_bytes())
            digest = sha256_file(original)
            write_json_new(
                capture / "metadata.json",
                {
                    "schema_version": 2,
                    "complete": True,
                    "capture_id": "synthetic-capture",
                    "original": "original.bmp",
                    "sha256": digest,
                    "provenance": {},
                    "quality_control": {"status": "pending"},
                },
            )
            reports = acquisition / "reports"
            reports.mkdir()
            report = reports / "synthetic.json"
            write_json_new(
                report,
                {
                    "schema_version": 1,
                    "operation": "acquire",
                    "status": "acquired",
                    "physical_scan_performed": False,
                    "captures": [
                        {
                            "capture_id": "synthetic-capture",
                            "original": "captures/synthetic-capture/original.bmp",
                            "sha256": digest,
                        }
                    ],
                },
            )
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"status": "acquired", "report": str(report)}), ""
            )
        else:
            raise AssertionError(script)
        code = 0 if status == "success" else 2
        return subprocess.CompletedProcess(
            command, code, json.dumps({"status": status, "report": str(folder / "report.json")}), ""
        )


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    image, physical = fixture(tmp_path)
    value = read_json(physical)
    value.update(
        status="success",
        configuration=physical_defaults(None),
        artifacts={},
        coordinate_system="original image pixels; x right, y down; no spatial transform",
    )
    value["source"]["path"] = str(image.resolve())
    value["baseline"]["status"] = "success"
    for side in value["baseline"]["sides"]:
        side.update(coverage=1.0, support_count=120, rms_pixels=0.0, p95_residual_pixels=0.0)
    physical.write_text(json.dumps(value))
    monkeypatch.setattr(engine, "ROOT", tmp_path / "pipeline")
    monkeypatch.setattr(engine, "confined_data_dir", lambda path: path.resolve())
    monkeypatch.setattr(reference_frames, "DATA_ROOT", tmp_path / "reference")
    monkeypatch.setattr(reference_frames, "confined_data_dir", lambda path: path.resolve())
    return image, physical, FixtureRunner(tmp_path / "cli-output", image, physical)


def options(image: Path, **extra: object) -> dict:
    return {
        "operation": "analyze-existing",
        "card": "D",
        "batch": "cross-card",
        "image": str(image),
        **extra,
    }


def test_successful_progression_and_idempotent_resume(environment: tuple) -> None:
    image, physical, runner = environment
    digest = sha256_file(image)
    result = engine.execute(options(image), runner)
    manifest = read_json(Path(result["manifest"]))
    assert manifest["status"] == "review_required"
    assert manifest["execution_status"] == "completed"
    assert manifest["stages"]["s2_1"]["status"] == "completed"
    assert manifest["stages"]["s2_2c"]["interface"]
    assert runner.calls == [
        "analyze_boundaries.py",
        "analyze_printed_frame.py",
        "evaluate_printed_frames.py",
        "reference_frames.py",
    ]

    def forbidden(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise AssertionError("Resume must not rerun any completed CLI")

    resumed = engine.execute(
        {"operation": "resume", "card": "D", "batch": "cross-card", "from": result["manifest"]},
        forbidden,
    )
    new = read_json(Path(resumed["manifest"]))
    assert result["manifest"] != resumed["manifest"]
    assert all(new["stages"][name]["reused"] for name in ("s2_1", "s2_2a", "s2_2b", "s2_2c"))
    assert new["stages"]["s2_2c"]["interface"] == manifest["stages"]["s2_2c"]["interface"]
    assert sha256_file(image) == digest
    assert new["automatic_acceptance"] is False


def test_block_review_even_when_pixel_checks_pass(environment: tuple) -> None:
    image, physical, runner = environment
    value = read_json(physical)
    value["status"] = "review_required"
    physical.write_text(json.dumps(value))
    result = engine.execute(options(image), runner)
    manifest = read_json(Path(result["manifest"]))
    assert result["status"] == "blocked_upstream"
    assert runner.calls == ["analyze_boundaries.py"]
    assert all(
        manifest["stages"][name]["status"] == "blocked_upstream"
        for name in ("s2_2a", "s2_2b", "s2_2c")
    )
    assert "Editor unavailable" in Path(result["dashboard"]).read_text()


def test_invalid_geometry_blocks_despite_success_status(environment: tuple) -> None:
    image, physical, runner = environment
    value = read_json(physical)
    value["baseline"]["geometry"]["validation"]["side_support"] = False
    value["baseline"]["sides"][2]["coverage"] = 0.625
    physical.write_text(json.dumps(value))
    result = engine.execute(options(image), runner)
    assert result["status"] == "blocked_upstream"
    html = Path(result["dashboard"]).read_text()
    assert "0.625" in html and "0.65" in html


@pytest.mark.parametrize(
    "failure", ["nonzero", "malformed_stdout", "timeout", "os_error", "malformed_report"]
)
def test_failed_processes_and_malformed_reports(environment: tuple, failure: str) -> None:
    image, physical, runner = environment
    if failure == "malformed_report":
        value = read_json(physical)
        value.pop("baseline")
        physical.write_text(json.dumps(value))

    def fail(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(
                command, timeout, output="partial output", stderr="partial error"
            )
        if failure == "os_error":
            raise OSError("Executable unavailable")
        if failure == "malformed_stdout":
            return subprocess.CompletedProcess(command, 0, "not-json", "")
        value = runner(command, timeout)
        if failure == "nonzero":
            value.returncode = 99
        return value

    result = engine.execute(options(image), fail)
    manifest = read_json(Path(result["manifest"]))
    assert result["status"] == "analysis_failed"
    assert manifest["stages"]["s2_2b"]["status"] == "blocked_upstream"
    assert (Path(result["manifest"]).parent / "logs/s2_1/stdout.txt").is_file()
    if failure == "timeout":
        assert (
            "partial output"
            in (Path(result["manifest"]).parent / "logs/s2_1/stdout.txt").read_text()
        )


def test_resume_mismatch_and_immutable_original_check(environment: tuple) -> None:
    image, physical, runner = environment
    value = read_json(physical)
    value["source"]["sha256"] = "0" * 64
    physical.write_text(json.dumps(value))
    result = engine.execute({"operation": "resume", "card": "D", "from": str(physical)}, runner)
    assert result["status"] == "analysis_failed"
    assert not runner.calls


def test_resume_detects_modified_evidence(environment: tuple) -> None:
    image, physical, runner = environment
    result = engine.execute(options(image), runner)
    manifest = read_json(Path(result["manifest"]))
    Path(manifest["stages"]["s2_2b"]["report"]).write_text("{}")
    calls = len(runner.calls)
    resumed = engine.execute(
        {"operation": "resume", "card": "D", "from": result["manifest"]}, runner
    )
    assert resumed["status"] == "analysis_failed"
    assert len(runner.calls) == calls


def test_subprocess_cannot_mutate_original_without_failure(environment: tuple) -> None:
    image, physical, runner = environment

    def mutate(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        result = runner(command, timeout)
        image.write_bytes(b"corrupted by test double")
        return result

    result = engine.execute(options(image), mutate)
    manifest = read_json(Path(result["manifest"]))
    assert result["status"] == "analysis_failed"
    assert str(image.resolve()) in manifest["integrity"]["changed_files"]


def test_scan_mode_and_resume_from_acquisition(environment: tuple, tmp_path: Path) -> None:
    image, physical, runner = environment
    config = tmp_path / "acquisition.json"
    config.write_text("{}")
    result = engine.execute(
        {"operation": "scan-and-analyze", "card": "E", "acquire_config": str(config)}, runner
    )
    manifest = read_json(Path(result["manifest"]))
    assert runner.calls[0] == "acquire.py"
    assert manifest["image"]["path"] != str(image)
    acquisition = Path(manifest["stages"]["acquisition"]["report"])
    before = len(runner.calls)
    resumed = engine.execute({"operation": "resume", "card": "E", "from": str(acquisition)}, runner)
    assert resumed["status"] == "review_required"
    assert "acquire.py" not in runner.calls[before:]


def test_batch_incremental_cards(environment: tuple) -> None:
    image, _, runner = environment
    first = engine.execute(options(image), runner)
    engine.execute(options(image, card="E"), runner)
    output = batch_dashboard(engine.ROOT, "cross-card")
    overview = read_json(output.parent / "overview.json")
    assert [c["card_id"] for c in overview["cards"]] == ["D", "E", "F", "G", "H"]
    assert overview["cards"][2]["status"] == "not_run"
    assert Path(first["batch_dashboard"]).is_file()


def test_resume_checkpoint_keeps_completed_physical_analysis(environment: tuple) -> None:
    image, _, runner = environment
    result = engine.execute(options(image), runner)
    checkpoints = sorted((Path(result["manifest"]).parent / "checkpoints").glob("*.json"))
    checkpoint = next(
        p
        for p in checkpoints
        if read_json(p)["stages"]["s2_1"].get("report")
        and read_json(p)["stages"]["s2_2a"]["status"] == "not_run"
    )
    before = len(runner.calls)
    resumed = engine.execute({"operation": "resume", "card": "D", "from": str(checkpoint)}, runner)
    assert resumed["status"] == "review_required"
    assert runner.calls[before:] == [
        "analyze_printed_frame.py",
        "evaluate_printed_frames.py",
        "reference_frames.py",
    ]


def test_dashboard_skips_malformed_manifest_and_escapes_text(environment: tuple) -> None:
    image, _, runner = environment
    result = engine.execute(options(image), runner)
    broken = engine.ROOT / "runs" / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("[]")
    output = batch_dashboard(engine.ROOT, "cross-card")
    assert read_json(output.parent / "overview.json")["warnings"]
    assert Path(result["dashboard"]).is_file()


def test_invalid_cli_identifier_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    from spectra_pipeline.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["analyze-existing", "--card", "../D", "--image", "original.bmp"])
    assert exc.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


def test_card_d_real_blocked_regression(environment: tuple) -> None:
    _, _, runner = environment
    report = Path(
        "local_data/s2_1/20261018T062229_355f5070499942f190627e4cad430cd8/scan-000/report.json"
    )
    if not report.exists():
        pytest.skip("Local Card D evidence is not distributed")
    source = Path(read_json(report)["source"]["path"])
    digest = sha256_file(source)
    result = engine.execute({"operation": "resume", "card": "D", "from": str(report)}, runner)
    manifest = read_json(Path(result["manifest"]))
    assert result["status"] == "blocked_upstream"
    assert not runner.calls
    assert manifest["stages"]["s2_1"]["physical_diagnostics"]["sides"][2]["coverage"] == 0.625
    assert not manifest["stages"]["s2_2c"].get("interface")
    assert "0.625" in Path(result["dashboard"]).read_text()
    assert "0.65" in Path(result["dashboard"]).read_text()
    assert (
        digest
        == sha256_file(source)
        == "2935dd598b6f793eabbac2d6c290cc911a05183342fda2cd0d3afa2d53b0e129"
    )
