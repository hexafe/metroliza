from __future__ import annotations

import os
import platform
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from metroliza.parsing import frozen_ocr_worker as worker
from metroliza.parsing import header_ocr_backend as backend


def test_worker_entry_does_not_import_qt_or_ocr_native_before_request():
    root = Path(__file__).resolve().parents[1]
    code = (
        "import runpy,sys; runpy.run_path(sys.argv[1], run_name='import_probe'); "
        "assert not any(n.split('.')[0] in {'PyQt6','onnxruntime','rapidocr','cv2'} "
        "for n in sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-c", code, str(root / "packaging/metroliza_ocr_worker_entry.py")],
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
        check=True, capture_output=True,
    )


def _request(root: Path) -> dict:
    return {
        "schema_version": 1,
        "nonce": "a" * 32,
        "config": {
            "model_paths": {
                "det": str(root / "det.onnx"), "cls": str(root / "cls.onnx"),
                "rec": str(root / "rec.onnx"), "keys": None,
            },
            "params": {}, "source": "rapidocr_latin",
        },
    }


def test_worker_version_fallback_uses_native_windows_tuple_without_shell(monkeypatch):
    fake_sys = SimpleNamespace(
        frozen=True, platform="win32",
        getwindowsversion=lambda: SimpleNamespace(platform_version=(10, 0, 20348)),
    )
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(worker, "sys", fake_sys)
    monkeypatch.setattr(platform, "_syscmd_ver", lambda *_args, **_kwargs: pytest.fail("shell fallback called"))

    worker._use_native_windows_version()

    assert platform._syscmd_ver() == ("", "", "10.0.20348")
    assert platform._syscmd_ver(version="unchanged", supported_platforms=()) == (
        "", "", "unchanged",
    )


@pytest.mark.parametrize("native", (None, (10, 0), (10, "0", 20348), (0, 0, 0)))
def test_worker_rejects_invalid_native_windows_version(monkeypatch, native):
    monkeypatch.setattr(worker, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(worker, "sys", SimpleNamespace(
        frozen=True, platform="win32",
        getwindowsversion=lambda: SimpleNamespace(platform_version=native),
    ))
    with pytest.raises(worker.OcrWorkerFailure, match="^ocr_windows_version_unavailable$"):
        worker._use_native_windows_version()


@pytest.mark.skipif(os.name != "nt", reason="native Windows version API")
def test_native_worker_version_fallback_does_not_launch_shell():
    root = Path(__file__).resolve().parents[1]
    code = (
        "import platform,sys\n"
        "from metroliza.parsing.frozen_ocr_worker import _use_native_windows_version\n"
        "sys.frozen=True\n"
        "def unavailable(*_args): raise OSError('controlled WMI unavailable')\n"
        "platform._wmi_query=unavailable\n"
        "platform._uname_cache=None\n"
        "_use_native_windows_version()\n"
        "def no_shell(event,_args):\n"
        "    if event=='subprocess.Popen': raise RuntimeError('unexpected shell')\n"
        "sys.addaudithook(no_shell)\n"
        "assert platform.win32_ver()[1]=='.'.join(map(str,sys.getwindowsversion().platform_version))\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
        check=True, capture_output=True,
    )


def test_worker_runs_real_protocol_without_qt_or_native_output(tmp_path, monkeypatch, capsys):
    (tmp_path / "header.png").write_bytes(b"synthetic-image")
    worker._write_json(tmp_path / "request.json", _request(tmp_path), worker.REQUEST_LIMIT)
    calls = []

    def recognize(self, image, *, _in_process=False):
        calls.append((Path(image).name, _in_process))
        return backend.HeaderOcrRun(records=(
            backend.HeaderOcrRecord(
                "OCR WIDGET", 0.91,
                ((1.0, 2.0), (3.0, 2.0), (3.0, 4.0), (1.0, 4.0)),
                "rapidocr_latin",
            ),
        ), diagnostics={})

    monkeypatch.setattr(backend.RapidOcrLatinBackend, "recognize", recognize)
    assert worker.worker_main([str(tmp_path)]) == 0
    result = worker._read_json(tmp_path / "result.json", worker.RESULT_LIMIT)
    assert result["nonce"] == "a" * 32
    assert worker._validated_records(result["records"], "rapidocr_latin")[0].text == "OCR WIDGET"
    assert calls == [("header.png", True)]
    assert capsys.readouterr() == ("", "")


def test_worker_rejects_modified_or_oversized_private_protocol(tmp_path):
    (tmp_path / "header.png").write_bytes(b"synthetic-image")
    payload = _request(tmp_path)
    payload["config"]["source"] = "arbitrary"
    worker._write_json(tmp_path / "request.json", payload, worker.REQUEST_LIMIT)
    assert worker.worker_main([str(tmp_path)]) == 1
    assert not (tmp_path / "result.json").exists()
    (tmp_path / "request.json").write_bytes(b"X" * (worker.REQUEST_LIMIT + 1))
    assert worker.worker_main([str(tmp_path)]) == 1


def test_parent_rejects_unbounded_or_nonfinite_worker_result(tmp_path):
    record = {
        "text": "synthetic", "confidence": 0.9,
        "box": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "source": "rapidocr_latin",
    }
    assert worker._validated_records([record], "rapidocr_latin")[0].text == "synthetic"
    with pytest.raises(ValueError, match="invalid_ocr_record"):
        worker._validated_records([{**record, "confidence": float("nan")}], "rapidocr_latin")
    with pytest.raises(ValueError, match="invalid_ocr_record"):
        worker._validated_records([{**record, "text": "x" * 4097}], "rapidocr_latin")
    with pytest.raises(ValueError, match="invalid_ocr_records"):
        worker._validated_records([record] * 257, "rapidocr_latin")
    path = tmp_path / "result.json"
    path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="duplicate_field"):
        worker._read_json(path, worker.RESULT_LIMIT)


def test_failed_owned_worker_terminates_job_and_waits_before_reporting(tmp_path, monkeypatch):
    from metroliza.shared import windows_owned_job

    events = []

    class Process:
        pid = 73
        _handle = 73

        def wait(self, timeout):
            events.append("wait")
            return 7

        def poll(self):
            return 7

    class Job:
        def __init__(self):
            events.append("job_created")

        def assign(self, _process):
            events.append("assigned")

        def resume(self, _process):
            events.append("resumed")

        def terminate(self, *, deadline):
            events.append("terminated")

        def close(self):
            events.append("closed")

    monkeypatch.setattr(windows_owned_job, "WindowsOwnedJob", Job)
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    with pytest.raises(worker.OcrWorkerFailure, match="^ocr_worker_failed$"):
        worker._run_owned_worker(tmp_path / "worker.exe", tmp_path)
    assert events == [
        "job_created", "assigned", "resumed", "wait", "terminated", "wait", "closed",
    ]


def test_parent_removes_private_image_and_result_after_worker_failure(tmp_path, monkeypatch):
    image = tmp_path / "input.png"
    image.write_bytes(b"synthetic-image")
    private = tmp_path / "private"
    private.mkdir()

    class Owner:
        name = str(private)
        cleaned = False

        def cleanup(self):
            assert (private / "header.png").exists()
            assert (private / "request.json").exists()
            for child in private.iterdir():
                child.unlink()
            private.rmdir()
            self.cleaned = True

    owner = Owner()
    monkeypatch.setattr(worker, "_private_work_directory", lambda: owner)
    monkeypatch.setattr(worker, "_worker_executable", lambda: tmp_path / "worker.exe")

    def failed_worker(_executable, _root):
        raise worker.OcrWorkerFailure("ocr_worker_failed")

    monkeypatch.setattr(worker, "_run_owned_worker", failed_worker)
    config = backend.RapidOcrLatinBackendConfig(model_paths=backend.RapidOcrLatinModelPaths(
        tmp_path / "det.onnx", tmp_path / "cls.onnx", tmp_path / "rec.onnx",
    ))
    with pytest.raises(worker.OcrWorkerFailure, match="^ocr_worker_failed$"):
        worker.recognize_in_frozen_worker(config, image)
    assert owner.cleaned and not private.exists()
    assert image.read_bytes() == b"synthetic-image"


@pytest.mark.skipif(os.name != "nt", reason="native Windows Job ownership only")
def test_native_worker_job_owns_process_before_resume():
    import subprocess
    import sys
    import time

    from metroliza.shared.windows_owned_job import WindowsOwnedJob

    job = WindowsOwnedJob()
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(0)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x4 | 0x08000000,
        )
        job.assign(process)
        job.resume(process)
        assert process.wait(timeout=10) == 0
        job.drain(deadline=time.monotonic() + 10)
        assert job.active() == 0
    finally:
        if process is not None and process.poll() is None:
            job.terminate(deadline=time.monotonic() + 10)
            process.wait(timeout=10)
        job.close()


@pytest.mark.skipif(os.name != "nt", reason="native pinned Windows directory only")
def test_native_worker_private_directory_is_pinned_and_removed():
    owner = worker._private_work_directory()
    private = Path(owner.name)
    try:
        assert private.is_dir()
        assert owner._handle
    finally:
        owner.cleanup()
    assert not private.exists()
