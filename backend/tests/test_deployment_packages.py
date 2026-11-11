import json
from hashlib import sha256
from zipfile import ZipFile

import pytest

from app.deployment.builder import build, requirement_versions
from app.deployment.verify_template import verify
from app.model_exports.schemas import ExportRequest, PackageRequest


def _export(tmp_path):
    root = tmp_path/"export"
    root.mkdir()
    data = b"unit-fixture-not-an-onnx-model"
    (root/"model.onnx").write_bytes(data)
    report = {"taskType": "obb", "classNames": ["coal", "bottle"],
              "artifact": {"sha256": sha256(data).hexdigest()},
              "input": {"shape": [1, 3, 320, 320]}, "pipeline": {"conf": 0.25, "iou": 0.7, "maxDet": 300},
              "environment": {"python": "3.12.16", "versions": {"ultralytics": "8.4.115", "torch": "2.8.0+cu128", "torchvision": "0.23.0+cu128", "numpy": "2.5.4", "onnxruntime": "1.31.1"}},
              "validation": {"status": "completed"}}
    (root/"report.json").write_text(json.dumps(report), encoding="utf-8")
    return root, report


def test_package_has_runtime_verified_members_and_environment(tmp_path):
    root, report = _export(tmp_path)
    destination = tmp_path/"built"
    result = build(root, destination, package_id="package", export_id="export", version_id="version", expected_report=report)
    assert result["productionReady"] is False
    assert result["taskType"] == "obb"
    assert "runtime/infer.py" in result["files"]
    assert verify(destination/"package") >= 7
    requirements = (destination/"package"/"requirements.txt").read_text()
    assert "https://download.pytorch.org/whl/cu128" in requirements
    assert "torch==2.8.0+cu128" in requirements
    with ZipFile(destination/"deployment-package.zip") as archive:
        assert "manifest.json" in archive.namelist()
        assert not any(name.startswith("/") or ".." in name.split("/") for name in archive.namelist())


def test_package_verification_rejects_changed_and_extra_files(tmp_path):
    root, _ = _export(tmp_path)
    build(root, tmp_path/"built", package_id="package", export_id="export", version_id="version")
    folder = tmp_path/"built"/"package"
    (folder/"unexpected.py").write_text("untrusted")
    with pytest.raises(ValueError, match="member list"):
        verify(folder)
    (folder/"unexpected.py").unlink()
    (folder/"model"/"model.onnx").write_bytes(b"modified")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify(folder)


def test_builder_rejects_modified_export_or_report(tmp_path):
    root, report = _export(tmp_path)
    changed = {**report, "classNames": ["tampered"]}
    with pytest.raises(ValueError, match="报告"):
        build(root, tmp_path/"bad1", package_id="p", export_id="e", version_id="v", expected_report=changed)
    (root/"model.onnx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="产物"):
        build(root, tmp_path/"bad2", package_id="p", export_id="e", version_id="v")


@pytest.mark.parametrize("missing", ["torchvision", "numpy"])
def test_legacy_export_report_requires_regeneration_before_creating_package(tmp_path, missing):
    root, report = _export(tmp_path)
    del report["environment"]["versions"][missing]
    (root/"report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="重新创建导出任务"):
        build(root, tmp_path/"legacy-package", package_id="p", export_id="e", version_id="v")
    assert not (tmp_path/"legacy-package").exists()


def test_package_dependency_lock_rejects_invalid_version_text(tmp_path):
    _, report = _export(tmp_path)
    report["environment"]["versions"]["torchvision"] = "0.23.0\n--index-url https://untrusted.invalid"
    with pytest.raises(ValueError, match="无效依赖版本"):
        requirement_versions(report)


def test_verify_rejects_escaping_manifest_path(tmp_path):
    (tmp_path/"package").mkdir()
    (tmp_path/"outside").write_bytes(b"outside")
    value = sha256(b"outside").hexdigest()
    (tmp_path/"package"/"checksum.sha256").write_text(f"{value}  ../outside\n")
    with pytest.raises(ValueError, match="Unsafe"):
        verify(tmp_path/"package")


def test_export_schema_rejects_unsupported_device_and_dimensions():
    version_id = "00000000-0000-0000-0000-000000000001"
    assert ExportRequest(versionId=version_id).deviceId == "cpu"
    for config in ({"deviceId": "cuda:0"}, {"imgsz": 321}, {"imgsz": 0}, {"format": "engine"}):
        with pytest.raises(ValueError):
            ExportRequest(versionId=version_id, **config)
    with pytest.raises(ValueError):
        PackageRequest(exportId="not-a-uuid")
