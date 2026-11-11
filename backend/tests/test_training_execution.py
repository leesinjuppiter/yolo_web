"""Behavior checks for training configuration, device ownership and diagnostics."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.training import devices
from app.training.catalog import ModelOption, expand_arguments, validate_model_config
from app.training.resources import gpu_sample
from app.training.runner import _callbacks, _watch_parent
from app.training.runner_io import failure_for
from app.training.runner_process import child_environment
from app.training.runtime import public_runtime
from app.training.schemas import TrainingConfig


def configuration(**updates):
    return {"name": "execution test", "datasetId": str(uuid4()), "task": "detect", "modelId": "yolo11n",
            "deviceId": "cpu", "epochs": 2, "batchSize": 2, "imageSize": 64, "optimizer": "AdamW",
            "learningRate": 0.001, "finalLearningRate": 0.01, "seed": 42, "patience": 0,
            "augmentation": "standard", **updates}


def test_old_configuration_keeps_defaults_and_gpu_arguments_are_not_overridden():
    old = TrainingConfig.model_validate(configuration())
    assert (old.freeze, old.workers, old.amp) == (0, 0, False)
    arguments = expand_arguments(configuration(deviceId="cuda:1", amp=True, freeze=5, workers=3))
    assert {key: arguments[key] for key in ("device", "amp", "freeze", "workers")} == {
        "device": "cuda:1", "amp": True, "freeze": 5, "workers": 3,
    }


@pytest.mark.parametrize("updates", [{"deviceId": "auto"}, {"deviceId": "0,1"}, {"deviceId": "cuda:-1"},
                                     {"deviceId": "cpu", "amp": True}, {"freeze": -1}, {"workers": 1.5}])
def test_unsupported_or_contradictory_configuration_is_rejected(updates):
    with pytest.raises(ValidationError):
        TrainingConfig.model_validate(configuration(**updates))


def test_freezing_random_initialization_is_rejected_but_full_parameter_finetuning_is_allowed():
    architecture = ModelOption("yolo11n", "test", "YOLO11", "detect", "yolo11n.yaml", False)
    with pytest.raises(ValueError, match="随机初始化"):
        validate_model_config(TrainingConfig.model_validate(configuration(freeze=2)), architecture)
    weights = ModelOption("weights", "test", "YOLO11", "detect", "weights.pt", True, "local_weights")
    validate_model_config(TrainingConfig.model_validate(configuration(freeze=0)), weights)


def test_child_preserves_container_device_mapping_and_does_not_receive_database_passwords(monkeypatch, tmp_path):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-container-card")
    monkeypatch.setenv("WORKBENCH_DATABASE_URL", "private")
    monkeypatch.setenv("WORKBENCH_TEST_DATABASE_URL", "private-test")
    gpu = child_environment(tmp_path, "cuda:0")
    assert gpu["CUDA_VISIBLE_DEVICES"] == "GPU-container-card"
    assert "WORKBENCH_DATABASE_URL" not in gpu and "WORKBENCH_TEST_DATABASE_URL" not in gpu
    assert gpu["YOLO_OFFLINE"] == "true" and gpu["YOLO_AUTOINSTALL"] == "false"
    assert child_environment(tmp_path, "cpu")["CUDA_VISIBLE_DEVICES"] == "-1"


def test_api_only_accepts_fresh_worker_gpu_capabilities(monkeypatch, tmp_path):
    path = tmp_path / "capabilities.json"
    monkeypatch.setattr(devices, "_capability_path", lambda: path)
    gpu = {"id": "cuda:0", "name": "worker GPU", "kind": "cuda"}
    with pytest.raises(ValueError, match="不会自动切换"):
        devices.validate_device("cuda:0")
    path.write_text(json.dumps({"sampledAt": datetime.now(timezone.utc).isoformat(), "devices": [devices.CPU, gpu]}))
    assert devices.validate_device("cuda:0") == gpu
    path.write_text(json.dumps({"sampledAt": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
                                "devices": [devices.CPU, gpu]}))
    assert devices.capabilities()["workerStatus"]["state"] == "stale"
    assert devices.available_devices() == [devices.CPU]
    with pytest.raises(ValueError):
        devices.validate_device("cuda:0")


def test_gpu_samples_use_uuid_and_separate_whole_card_from_training_process(monkeypatch):
    calls = []

    def query(arguments):
        calls.append(arguments)
        return ([["GPU-one", "80", "500", "16000"]] if "--id=GPU-one" in arguments
                else [["123", "GPU-other", "999"], ["123", "GPU-one", "300"], ["456", "GPU-one", "200"]])

    monkeypatch.setattr("app.training.resources._nvidia_query", query)
    sample = gpu_sample({"id": "cuda:0", "name": "test", "kind": "cuda", "uuid": "GPU-one"}, 123)
    assert sample["utilizationPercent"] == 80
    assert sample["memoryUsedBytes"] == 500 * 1024**2
    assert sample["processMemoryBytes"] == 300 * 1024**2
    assert calls[0][0] == "--id=GPU-one"


@pytest.mark.parametrize("raw,expected", [
    ("40f318a7-e98d-8588-28ce-e3b3e32d655d", "GPU-40f318a7-e98d-8588-28ce-e3b3e32d655d"),
    ("GPU-40f318a7-e98d-8588-28ce-e3b3e32d655d", "GPU-40f318a7-e98d-8588-28ce-e3b3e32d655d"),
    ("MIG-40f318a7-e98d-8588-28ce-e3b3e32d655d", "MIG-40f318a7-e98d-8588-28ce-e3b3e32d655d"),
    (None, ""),
])
def test_worker_normalizes_pytorch_uuid_without_changing_prefixed_identifiers(raw, expected):
    assert devices.normalize_gpu_uuid(raw) == expected


def test_gpu_sampling_accepts_actual_pytorch28_uuid_format(monkeypatch):
    raw_uuid = "40f318a7-e98d-8588-28ce-e3b3e32d655d"
    nvidia_uuid = f"GPU-{raw_uuid}"

    def query(arguments):
        if arguments[0].startswith("--id="):
            assert arguments[0] == f"--id={nvidia_uuid}"
            return [[nvidia_uuid, "70", "800", "16384"]]
        return [["123", nvidia_uuid, "600"]]

    monkeypatch.setattr("app.training.resources._nvidia_query", query)
    sample = gpu_sample({"id": "cuda:0", "name": "RTX 5060 Ti", "kind": "cuda", "uuid": raw_uuid}, 123)
    assert sample["uuid"] == nvidia_uuid
    assert sample["utilizationPercent"] == 70
    assert sample["processMemoryBytes"] == 600 * 1024**2


@pytest.mark.parametrize("message,code", [
    ("RuntimeError: CUDA out of memory", "CUDA_OUT_OF_MEMORY"),
    ("RuntimeError: no kernel image is available for execution on the device", "CUDA_ARCH_UNSUPPORTED"),
    ("RuntimeError: CUDA driver error", "CUDA_UNAVAILABLE"),
    ("RuntimeError: can't allocate memory", "CPU_MEMORY_EXHAUSTED"),
])
def test_memory_and_cuda_failures_have_distinct_diagnostics(message, code):
    result = failure_for("training", 1, SimpleNamespace(failure=None, last_error=message))
    assert result["code"] == code


def test_runtime_exposes_actual_freeze_workers_and_parameter_counts():
    runtime = public_runtime({"arguments": {"task": "detect", "freeze": 4, "workers": 2},
                              "actualDevice": "cuda:0", "trainableParameters": 100, "frozenParameters": 50})
    assert runtime["arguments"] == {"freeze": 4, "workers": 2}
    assert runtime["actualDevice"] == "cuda:0"
    assert runtime["trainableParameters"] == 100 and runtime["frozenParameters"] == 50


def test_runner_reports_effective_amp_and_trainable_parameters():
    callbacks, events = {}, []
    model = SimpleNamespace(add_callback=lambda name, callback: callbacks.update({name: callback}))
    _callbacks(model, lambda kind, **payload: events.append((kind, payload)))
    parameters = [SimpleNamespace(requires_grad=True, numel=lambda: 100),
                  SimpleNamespace(requires_grad=False, numel=lambda: 50)]
    callbacks["on_train_start"](SimpleNamespace(
        model=SimpleNamespace(parameters=lambda: parameters), args=SimpleNamespace(amp=True, task="detect"),
        amp=False, device="cuda:0",
    ))
    kind, payload = events[0]
    assert kind == "environment"
    assert payload["arguments"]["amp"] is False
    assert payload["trainableParameters"] == 100 and payload["frozenParameters"] == 50


def test_parent_watch_uses_unbuffered_descriptor_to_allow_clean_interpreter_shutdown(monkeypatch):
    reads, killed = [], []
    monkeypatch.setattr("app.training.runner.sys.stdin", SimpleNamespace(fileno=lambda: 42))
    monkeypatch.setattr("app.training.runner.os.read", lambda fd, size: reads.append((fd, size)) or b"")
    monkeypatch.setattr("app.training.runner.os.getpgrp", lambda: 1234, raising=False)
    monkeypatch.setattr("app.training.runner.os.killpg", lambda group, signum: killed.append((group, signum)),
                        raising=False)
    monkeypatch.setattr("app.training.runner.signal.SIGKILL", 9, raising=False)
    _watch_parent()
    assert reads == [(42, 1)]
    assert killed == [(1234, 9)]


@pytest.mark.skipif(os.name == "nt", reason="Linux parent-pipe watcher is not used on Windows")
def test_live_parent_watch_does_not_crash_normal_runner_shutdown():
    script = ("from threading import Thread; import time; "
              "from app.training.runner import _watch_parent; "
              "Thread(target=_watch_parent, daemon=True).start(); time.sleep(0.1)")
    with subprocess.Popen([sys.executable, "-B", "-c", script], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as child:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            pytest.fail("runner did not exit with a live parent-pipe watcher")
        assert child.returncode == 0, child.stderr.read().decode("utf-8", errors="replace")
