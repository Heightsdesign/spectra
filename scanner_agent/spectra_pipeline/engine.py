from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from spectra_scanner.common import (
    AGENT_ROOT,
    DATA_ROOT,
    AgentError,
    confined_data_dir,
    identifier,
    utc_now,
    write_json_new,
)
from spectra_scanner.storage import sha256_file

from . import __version__
from .contracts import (
    artifact_paths,
    frame_report,
    physical_report,
    read_json,
    resolve_resume,
    verify_source,
)
from .dashboard import STAGES, batch_dashboard, run_dashboard

ROOT = DATA_ROOT / "rd_pipeline"
Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def run_process(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=AGENT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def token(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise AgentError(
            "invalid_identifier",
            "Card/batch identifiers use 1..64 letters, numbers, hyphens or underscores",
        )
    return value


class Execution:
    def __init__(self, options: dict[str, Any], runner: Runner):
        self.options, self.runner = options, runner
        self.root = confined_data_dir(ROOT)
        self.output = self.root / "runs" / identifier()
        self.output.mkdir(parents=True, exist_ok=False)
        self.value: dict[str, Any] = {
            "schema_version": 1,
            "kind": "rd_pipeline_run",
            "orchestrator_version": __version__,
            "run_id": self.output.name,
            "card_id": token(options["card"]),
            "batch_id": token(options.get("batch", "cross-card")),
            "operation": options["operation"],
            "created_at_utc": utc_now(),
            "status": "not_run",
            "execution_status": "running",
            "automatic_acceptance": False,
            "physical_scan_performed_this_execution": False,
            "image": None,
            "policy": "S2.1 review_required or any failed physical validation blocks ALL dependent S2.2 stages. S2.2a/b are sibling experiments; valid S2.2b can prepare a human editor, never approve a result.",
            "stages": {
                name: {
                    "status": "not_run",
                    "execution_status": "not_run",
                    "analytical_status": None,
                    "reused": False,
                }
                for name in STAGES
            },
            "protected_files": {},
            "finalized": False,
            "dashboard": str((self.output / "dashboard.html").resolve()),
        }
        self.current = "acquisition"
        self.checkpoint_number = 0
        self.previous: dict[str, Any] | None = None
        self.reports: dict[str, Path] = {}
        # A cache is tied to executable code as well as immutable input/report bytes.
        sources = [
            AGENT_ROOT / name
            for name in (
                "acquire.py",
                "analyze_boundaries.py",
                "analyze_printed_frame.py",
                "evaluate_printed_frames.py",
                "reference_frames.py",
            )
        ]
        for package in (
            "spectra_scanner",
            "spectra_boundary",
            "spectra_centering",
            "spectra_frame_evaluation",
            "spectra_reference",
            "spectra_pipeline",
        ):
            sources += [
                p
                for p in (AGENT_ROOT / package).rglob("*")
                if p.is_file()
                and p.suffix in {".py", ".js", ".html"}
                and "__pycache__" not in p.parts
            ]
        for path in sources:
            self.protect(path)
        self.checkpoint()

    def protect(self, path: Path) -> None:
        key = str(path.resolve())
        digest = sha256_file(path)
        old = self.value["protected_files"].get(key)
        if old and old != digest:
            raise AgentError("integrity_error", f"Input changed during execution: {key}")
        self.value["protected_files"][key] = digest

    def checkpoint(self) -> None:
        self.checkpoint_number += 1
        write_json_new(
            self.output / "checkpoints" / f"{self.checkpoint_number:04d}_{identifier()}.json",
            self.value,
        )

    def invoke(
        self,
        stage: str,
        script: str,
        args: list[str],
        python: str | None = None,
        timeout: float | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        self.current = stage
        item = self.value["stages"][stage]
        command = [python or sys.executable, str(AGENT_ROOT / script), *args]
        folder = self.output / "logs" / stage
        folder.mkdir(parents=True)
        item.update(
            execution_status="running",
            command=command,
            stdout_log=str(folder / "stdout.txt"),
            stderr_log=str(folder / "stderr.txt"),
        )
        stdout, stderr = "", ""
        try:
            result = self.runner(command, timeout or float(self.options.get("timeout", 300)))
            stdout, stderr = result.stdout or "", result.stderr or ""
            item["return_code"] = result.returncode
            lines = [line for line in stdout.splitlines() if line.strip()]
            if not lines:
                raise AgentError("missing_cli_output", "CLI returned no JSON result")
            response = json.loads(lines[-1])
            if not isinstance(response, dict) or not response.get("report"):
                raise AgentError("invalid_cli_output", "Expected final JSON with a report path")
            report = confined_data_dir(Path(response["report"]))
            self.protect(report)
            body = read_json(report)
            item["cli_report"] = str(report)
            expected = (
                0
                if response.get("status") in {"success", "acquired"}
                else 2
                if response.get("status") in {"review_required", "not_applicable"}
                else 3
            )
            if body.get("status") != response.get("status") or result.returncode != expected:
                raise AgentError(
                    "subprocess_failed",
                    "Exit status and report status disagree; no success inferred from a file alone",
                )
            item["execution_status"] = "completed"
            return report, body
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else exc.stdout
            ) or ""
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else exc.stderr
            ) or ""
            raise AgentError(
                "subprocess_timeout", f"{stage} exceeded its timeout; logs preserved"
            ) from exc
        finally:
            for name, text in (("stdout.txt", stdout), ("stderr.txt", stderr)):
                with (folder / name).open("x", encoding="utf-8") as handle:
                    handle.write(text)

    def adopt(self, stage: str, path: Path, value: dict[str, Any], reused: bool) -> None:
        self.protect(path)
        artifacts = artifact_paths(path, value.get("artifacts", {}))
        for artifact in artifacts:
            self.protect(artifact)
        self.value["stages"][stage].update(
            report=str(path.resolve()),
            report_sha256=sha256_file(path),
            reused=reused,
            execution_status="completed",
            analytical_status=value["status"],
            artifacts=[str(p) for p in artifacts],
        )

    def source(self) -> Path:
        options = self.options
        if options["operation"] == "scan-and-analyze":
            config = Path(options["acquire_config"]).resolve()
            self.protect(config)
            args = [
                "--config",
                str(config),
                "--data-dir",
                str(self.output / "acquisition"),
                "--timeout",
                str(options.get("scan_timeout", 300)),
            ]
            for name in ("device", "dsm"):
                if options.get(name):
                    args += ["--" + name, str(options[name])]
            for name in ("show_ui", "strict_options"):
                if options.get(name):
                    args.append("--" + name.replace("_", "-"))
            report, body = self.invoke(
                "acquisition",
                "acquire.py",
                args,
                options.get("acquisition_python"),
                float(options.get("scan_timeout", 300)) + 30,
            )
            if body["status"] != "acquired":
                raise AgentError("acquisition_failed", "No completed capture asserted")
            self.value["physical_scan_performed_this_execution"] = (
                body.get("physical_scan_performed") is True
            )
            image, _, _, protected = resolve_resume(report, options.get("capture_id"))
            self.value["stages"]["acquisition"]["report"] = str(report)
            for path in protected:
                self.protect(path)
            return image
        if options["operation"] == "resume":
            path = Path(options["from"]).resolve()
            image, self.reports, self.previous, protected = resolve_resume(
                path, options.get("capture_id")
            )
            self.value["resumed_from"] = {"path": str(path), "sha256": sha256_file(path)}
            if self.previous:
                if self.previous["card_id"] != options["card"] or self.previous[
                    "batch_id"
                ] != options.get("batch", "cross-card"):
                    raise AgentError(
                        "resume_identity_mismatch",
                        "Previous run belongs to a different card or batch",
                    )
                for name, digest in self.previous.get("protected_files", {}).items():
                    if sha256_file(Path(name)) != digest:
                        raise AgentError(
                            "resume_integrity_error", f"Changed previous artifact: {name}"
                        )
                    self.protect(Path(name))
                if sha256_file(image) != self.previous["image"]["sha256"]:
                    raise AgentError(
                        "resume_integrity_error", "Original differs from previous execution"
                    )
            for protected_path in protected:
                self.protect(protected_path)
            return image
        return Path(options["image"]).resolve()

    def analyze(self) -> None:
        image = self.source().resolve()
        self.protect(image)
        metadata = image.parent / "metadata.json"
        if metadata.is_file():
            self.protect(metadata)
        evidence = verify_source(image)
        self.value["image"] = {
            "path": str(image),
            "sha256": evidence["sha256"],
            "image": evidence["image"],
            "acquisition": evidence.get("acquisition"),
        }
        acquisition = self.value["stages"]["acquisition"]
        acquisition.update(
            status="completed",
            execution_status="completed",
            analytical_status="original_integrity_verified",
            reused=self.options["operation"] != "scan-and-analyze",
        )
        if metadata.is_file():
            committed = read_json(metadata)
            acquisition["quality_control"] = committed.get("quality_control")
            if committed.get("quality_control", {}).get("status") == "fail":
                raise AgentError("acquisition_qc_failed", "Existing S1 quality checks failed")
        self.checkpoint()
        self.current = "s2_1"
        reused = "s2_1" in self.reports
        if reused:
            physical = self.reports["s2_1"]
        else:
            index, index_value = self.invoke(
                "s2_1", "analyze_boundaries.py", ["analyze", str(image)]
            )
            if (
                index_value.get("kind") != "analysis_index"
                or index_value.get("schema_version") != 1
            ):
                raise AgentError("malformed_report", "Expected S2.1 analysis index")
            physical = (index.parent / index_value["analysis"]).resolve()
            if not physical.is_relative_to(index.parent):
                raise AgentError("invalid_report_path", "S2.1 index escapes output")
        physical_value, reasons = physical_report(physical, image)
        if not reused and index_value.get("status") != physical_value["status"]:
            raise AgentError("malformed_report", "S2.1 index and per-image status disagree")
        self.adopt("s2_1", physical, physical_value, reused)
        baseline = physical_value.get("baseline", {})
        diagnostics = {
            "minimum_side_coverage": physical_value["configuration"]["minimum_side_coverage"],
            "failed_checks": [
                key
                for key, passed in baseline.get("geometry", {}).get("validation", {}).items()
                if passed is not True
            ],
            "sides": [],
        }
        for side in baseline.get("sides", []):
            item = {
                key: side.get(key)
                for key in (
                    "index",
                    "coverage",
                    "rms_pixels",
                    "support_count",
                    "ambiguous_parallel_edge",
                    "selected_layer_id",
                    "ambiguity_reasons",
                )
            }
            item["minimum_side_coverage"] = diagnostics["minimum_side_coverage"]
            item["candidate_layers"] = [
                {
                    key: layer.get(key)
                    for key in (
                        "id",
                        "coverage",
                        "support_count",
                        "criterion_failures",
                        "disposition",
                        "raw_evidence",
                    )
                }
                for layer in side.get("candidate_layers", [])
            ]
            diagnostics["sides"].append(item)
        stage = self.value["stages"]["s2_1"]
        stage.update(
            physical_diagnostics=diagnostics,
            status="analysis_failed"
            if physical_value["status"] == "failure"
            else "review_required"
            if reasons
            else "completed",
            reason="; ".join(reasons),
        )
        self.checkpoint()
        if reasons:
            for name in ("s2_2a", "s2_2b", "s2_2c"):
                self.value["stages"][name].update(
                    status="blocked_upstream", reason="S2.1 gate refused: " + "; ".join(reasons)
                )
            return
        # These are siblings: S2.2a review does not substitute for or veto S2.2b.
        for name, script in (
            ("s2_2a", "analyze_printed_frame.py"),
            ("s2_2b", "evaluate_printed_frames.py"),
        ):
            self.current = name
            try:
                reused = name in self.reports
                path = (
                    self.reports[name]
                    if reused
                    else self.invoke(name, script, [str(image), str(physical)])[0]
                )
                value = frame_report(path, image, physical, name)
                self.adopt(name, path, value, reused)
                self.value["stages"][name].update(
                    status="analysis_failed"
                    if value["status"] == "analysis_failed"
                    else "review_required",
                    reason=value.get(
                        "explanation", "Experimental printed-frame result; no acceptance"
                    ),
                )
                if name == "s2_2b":
                    self.value["stages"][name]["frame_summary"] = {
                        key: value.get("frame_evaluation", {}).get(key)
                        for key in (
                            "valid_count",
                            "possible_combinations",
                            "search_truncated",
                            "selected_geometric_hypothesis_id",
                        )
                    }
            except (AgentError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                self.failure(name, exc)
            self.checkpoint()
        if self.value["stages"]["s2_2b"]["status"] == "analysis_failed":
            self.value["stages"]["s2_2c"].update(
                status="blocked_upstream",
                reason="S2.2b report is invalid or analysis failed; editor unavailable",
            )
            return
        self.current = "s2_2c"
        old = self.previous["stages"]["s2_2c"] if self.previous else {}
        if old.get("interface") and old.get("status") == "review_required":
            interface = Path(old["interface"])
            self.protect(interface)
            self.value["stages"]["s2_2c"].update(
                interface=str(interface), reused=True, execution_status="completed"
            )
        else:
            # This CLI returns an interface, not a report, so preserve its distinct contract.
            self.prepare_editor(image, Path(self.value["stages"]["s2_2b"]["report"]))
        self.value["stages"]["s2_2c"].update(
            status="review_required",
            analytical_status="awaiting_operator_annotation",
            reason="Human reference required; ranking is unavailable until an operator annotates and explicitly runs compare",
        )
        self.checkpoint()

    def prepare_editor(self, image: Path, report: Path) -> None:
        item = self.value["stages"]["s2_2c"]
        command = [
            sys.executable,
            str(AGENT_ROOT / "reference_frames.py"),
            "prepare",
            str(image),
            str(report),
        ]
        folder = self.output / "logs" / "s2_2c"
        folder.mkdir(parents=True)
        item.update(
            command=command,
            execution_status="running",
            stdout_log=str(folder / "stdout.txt"),
            stderr_log=str(folder / "stderr.txt"),
        )
        # Shared execution/logging semantics without changing the existing editor CLI.
        stdout, stderr = "", ""
        try:
            result = self.runner(command, float(self.options.get("timeout", 300)))
            stdout, stderr = result.stdout or "", result.stderr or ""
            item["return_code"] = result.returncode
            value = json.loads(stdout.strip().splitlines()[-1])
            if result.returncode != 0 or value.get("status") != "awaiting_operator_annotation":
                raise AgentError(
                    "editor_prepare_failed", "Existing annotation CLI rejected its input"
                )
            interface = confined_data_dir(Path(value["interface"]))
            if interface.suffix.lower() != ".html" or not interface.is_file():
                raise AgentError("invalid_editor_artifact", "No generated HTML interface")
            self.protect(interface)
            if value.get("inventory"):
                self.protect(confined_data_dir(Path(value["inventory"])))
            item.update(interface=str(interface), execution_status="completed")
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode("utf-8", errors="replace")
                if isinstance(exc.stdout, bytes)
                else exc.stdout
            ) or ""
            stderr = (
                exc.stderr.decode("utf-8", errors="replace")
                if isinstance(exc.stderr, bytes)
                else exc.stderr
            ) or ""
            raise AgentError("subprocess_timeout", "Editor preparation timed out") from exc
        finally:
            for name, text in (("stdout.txt", stdout), ("stderr.txt", stderr)):
                with (folder / name).open("x", encoding="utf-8") as handle:
                    handle.write(text)

    def failure(self, stage: str, exc: Exception) -> None:
        self.value["stages"][stage].update(
            status="analysis_failed",
            execution_status="failed",
            error={"code": getattr(exc, "status", "invalid_input_or_report"), "message": str(exc)},
        )


def execute(options: dict[str, Any], runner: Runner = run_process) -> dict[str, Any]:
    execution = Execution(options, runner)
    value = execution.value
    try:
        execution.analyze()
    except (
        AgentError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
    ) as exc:
        execution.failure(execution.current, exc)
        value["error"] = str(exc)
        for stage in STAGES:
            if value["stages"][stage]["status"] == "not_run":
                value["stages"][stage].update(
                    status="blocked_upstream",
                    reason="Prior stage failed; no automatic retry or acquisition",
                )
    changed = [
        name
        for name, digest in value["protected_files"].items()
        if not Path(name).is_file() or sha256_file(Path(name)) != digest
    ]
    value["integrity"] = {
        "verified": not changed,
        "changed_files": changed,
        "original_sha256_after": sha256_file(Path(value["image"]["path"]))
        if value.get("image") and Path(value["image"]["path"]).is_file()
        else None,
    }
    statuses = [item["status"] for item in value["stages"].values()]
    value["status"] = (
        "analysis_failed"
        if changed or "analysis_failed" in statuses
        else "blocked_upstream"
        if "blocked_upstream" in statuses
        else "review_required"
        if "review_required" in statuses
        else "completed"
    )
    value["execution_status"] = "failed" if value["status"] == "analysis_failed" else "completed"
    value.update(finalized=True, finished_at_utc=utc_now())
    execution.checkpoint()
    manifest = execution.output / "manifest.json"
    write_json_new(manifest, value)
    run_dashboard(value, execution.output / "dashboard.html")
    overview = batch_dashboard(execution.root, value["batch_id"])
    return {
        "status": value["status"],
        "execution_status": value["execution_status"],
        "manifest": str(manifest),
        "dashboard": value["dashboard"],
        "batch_dashboard": str(overview),
        "automatic_acceptance": False,
    }
