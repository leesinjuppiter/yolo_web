"""Create an immutable package with executable CPU inference and checksums."""

import json
import re
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.model_exports.storage import digest, write_json


def requirement_versions(report: dict) -> dict[str, str]:
    versions = (report.get("environment") or {}).get("versions") or {}
    required = ("ultralytics", "torch", "torchvision", "numpy", "onnxruntime")
    missing = [name for name in required if not isinstance(versions.get(name), str) or not versions[name].strip()]
    if missing:
        raise ValueError("导出报告缺少锁定依赖版本（"+", ".join(missing)+"），请重新创建导出任务后再生成部署包")
    if any(not re.fullmatch(r"[0-9][A-Za-z0-9.+!_-]*", versions[name]) for name in required):
        raise ValueError("导出报告包含无效依赖版本，请重新创建导出任务")
    return {name: versions[name] for name in required}


def build(export_root: Path, destination: Path, *, package_id: str, export_id: str, version_id: str,
          expected_report: dict | None = None) -> dict:
    report = json.loads((export_root/"report.json").read_text(encoding="utf-8"))
    if expected_report is not None and report != expected_report:
        raise ValueError("导出报告在打包前发生变化")
    versions = requirement_versions(report)
    if digest(export_root/"model.onnx") != report["artifact"]["sha256"]:
        raise ValueError("导出产物在打包前发生变化")
    folder = destination/"package"
    folder.mkdir(parents=True, exist_ok=False)
    (folder/"model").mkdir()
    shutil.copyfile(export_root/"model.onnx", folder/"model"/"model.onnx")
    if digest(folder/"model"/"model.onnx") != report["artifact"]["sha256"]:
        raise ValueError("模型复制后校验失败")
    manifest = {"schemaVersion": 1, "packageId": package_id, "exportId": export_id,
                "modelVersionId": version_id, "taskType": report["taskType"], "format": "onnx",
                "precision": "fp32", "artifactSha256": report["artifact"]["sha256"],
                "input": report["input"], "pipeline": report["pipeline"], "classNames": report["classNames"],
                "runtime": "Ultralytics ONNX / ONNX Runtime CPUExecutionProvider",
                "validatedEnvironment": report["environment"], "productionReady": False,
                "validationStatus": report["validation"]["status"],
                "installation": "Requires Python 3.11+ and network access for locked dependencies; no offline wheels included"}
    write_json(folder/"manifest.json", manifest)
    write_json(folder/"model"/"classes.json", {"names": report["classNames"]})
    write_json(folder/"config"/"preprocess.json", {"input": report["input"], "pipeline": report["pipeline"]})
    write_json(folder/"reports"/"validation.json", report)
    runtime = folder/"runtime"
    runtime.mkdir()
    here = Path(__file__).parent
    shutil.copyfile(here/"verify_template.py", runtime/"verify.py")
    shutil.copyfile(here/"infer_template.py", runtime/"infer.py")
    torch_suffix = versions["torch"].split("+", 1)[-1]
    index = f"--extra-index-url https://download.pytorch.org/whl/{torch_suffix}\n" if torch_suffix in ("cu124", "cu126", "cu128", "cu130", "cpu") else ""
    requirements = index+"\n".join(f"{name}=={versions[name]}" for name in ("ultralytics", "torch", "torchvision", "numpy", "onnxruntime"))+"\n"
    (folder/"requirements.txt").write_text(requirements, encoding="utf-8")
    readme = ("# ONNX FP32 deployment package\n\n"
              "This is a downloadable, CPU-tested package. It does not install a service or deploy remotely.\n"
              "Only the environment in manifest.json was tested. No production accuracy threshold was configured.\n\n"
              "Create a separate Conda Python environment matching validatedEnvironment.python. Then run:\n\n"
              "    python -B runtime/verify.py\n"
              "    python -m pip install -r requirements.txt\n"
              "    python -B runtime/infer.py /absolute/path/to/image.jpg\n\n"
              "Keep the extracted directory unchanged. Run verification before installing dependencies.\n"
              "Network access is required for dependency installation; offline wheels are not bundled.\n"
              "Output coordinates refer to the original image, OBB uses rotated corners; output comes from the locked Ultralytics runtime.\n"
              "Dependencies below are pinned at direct-package level; the build environment's complete pip freeze is included for reproduction.\n")
    (folder/"README.md").write_text(readme, encoding="utf-8")
    freeze = export_root/"environment-lock.txt"
    if freeze.is_file():
        shutil.copyfile(freeze, folder/"environment-lock.txt")
    checks = "\n".join(f"{digest(path)}  {path.relative_to(folder).as_posix()}"
                       for path in sorted(folder.rglob("*")) if path.is_file())+"\n"
    (folder/"checksum.sha256").write_text(checks, encoding="utf-8")
    from app.deployment.verify_template import verify
    verify(folder)
    archive = destination/"deployment-package.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(folder).as_posix())
    return {**manifest, "packageSha256": digest(archive), "sizeBytes": archive.stat().st_size,
            "files": sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())}
