import json
import sys

import pytest

from spectra_scanner import cli, common
from spectra_scanner.common import AgentError, agent_lock, confined_data_dir
from spectra_scanner.supervisor import supervise


def test_native_worker_crash_is_a_diagnostic_not_parent_crash(tmp_path):
    result = supervise(
        {"operation": "discover", "data_dir": str(tmp_path)},
        5,
        command=[sys.executable, "-c", "import sys;sys.stdin.read();sys.exit(87)"],
    )
    assert result["status"] == "driver_crash"
    assert result["worker_exit_code"] == 87
    assert result["physical_scan_performed"] is False


def test_native_worker_timeout_is_bounded_and_keeps_artifacts(tmp_path):
    result = supervise(
        {"operation": "acquire", "data_dir": str(tmp_path)},
        0.25,
        command=[sys.executable, "-c", "import sys,time;sys.stdin.read();time.sleep(20)"],
    )
    assert result["status"] == "timeout"
    assert result["physical_scan_performed"] == "unknown_worker_interrupted"
    assert (tmp_path / result["worker_artifacts"] / "driver.log").exists()


def test_timeout_retains_completed_discovery_checkpoint(tmp_path):
    script = """
import sys,json,time
from pathlib import Path
job=json.load(sys.stdin)
folder=next((Path(job['data_dir'])/'.work').iterdir())
(folder/'checkpoint_0001.json').write_text(json.dumps({'phase':'opening_source','devices':[{'name':'EPSON Perfection V39II'}]}))
time.sleep(20)
"""
    result = supervise(
        {"operation": "discover", "data_dir": str(tmp_path)},
        0.75,
        command=[sys.executable, "-c", script],
    )
    assert result["status"] == "timeout"
    assert result["phase"] == "opening_source"
    assert result["devices"][0]["name"] == "EPSON Perfection V39II"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object containment")
def test_worker_helper_processes_are_contained(tmp_path):
    from ctypes import WinDLL, wintypes

    script = """
import sys,json,subprocess
from pathlib import Path
job=json.load(sys.stdin)
helper=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
(Path(job['data_dir'])/'helper.pid').write_text(str(helper.pid))
"""
    result = supervise(
        {"operation": "discover", "data_dir": str(tmp_path)},
        5,
        command=[sys.executable, "-c", script],
    )
    assert (
        result["status"] == "driver_crash"
    )  # Deliberate missing result, despite helper outliving worker.
    pid = int((tmp_path / "helper.pid").read_text())
    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 2000) == 0
        finally:
            kernel.CloseHandle(handle)


def test_output_cannot_target_production():
    with pytest.raises(AgentError):
        confined_data_dir(common.AGENT_ROOT.parent / "backend" / "data")


def test_concurrent_local_agent_is_busy(tmp_path):
    with agent_lock(tmp_path), pytest.raises(AgentError, match="Another S1 process"):
        with agent_lock(tmp_path):
            pytest.fail("Lock was not exclusive")


def test_cli_negative_result_is_machine_readable(tmp_path, monkeypatch, capsys):
    root = tmp_path / "local_data"
    monkeypatch.setattr(cli, "DATA_ROOT", root)
    monkeypatch.setattr(common, "DATA_ROOT", root)
    monkeypatch.setattr(
        cli,
        "supervise",
        lambda *args: {"status": "device_absent", "physical_scan_performed": False},
    )
    assert cli.main(["discover"]) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "device_absent"
    assert summary["report"]
    assert len(list(root.glob("reports/*.json"))) == 1


@pytest.mark.parametrize("value", ["0", "nan", "inf", "-1"])
def test_invalid_timeout_is_reported(tmp_path, monkeypatch, value):
    root = tmp_path / "local_data"
    monkeypatch.setattr(cli, "DATA_ROOT", root)
    monkeypatch.setattr(common, "DATA_ROOT", root)
    assert cli.main(["discover", "--timeout", value]) == 2
    report = json.loads(next(root.glob("reports/*.json")).read_text())
    assert report["status"] == "invalid_input"
