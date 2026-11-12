"""Task-local diagnostic evidence IO. API consumers never receive internal paths."""
from __future__ import annotations

import json
from pathlib import Path


def read_samples(directory: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((directory / "input" / "manifest.json").read_text(encoding="utf-8"))
    return manifest, manifest["samples"]


def write_evidence(directory: Path, ordinal: int, evidence: dict, masks=None) -> None:
    folder = directory / "evidence"
    folder.mkdir(exist_ok=True)
    if masks is not None:
        import numpy as np
        np.savez_compressed(folder / f"{ordinal}.npz", masks=masks)
    (folder / f"{ordinal}.json").write_text(json.dumps(evidence, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def read_evidence(directory: Path, image_id: str, per_image: list[dict]) -> dict:
    index = next((i for i, item in enumerate(per_image) if item["imageId"] == image_id), None)
    if index is None:
        from app.dataset.repository import NotFound
        raise NotFound("评估图片不存在")
    return json.loads((directory / "evidence" / f"{index}.json").read_text(encoding="utf-8"))


def prediction_objects(result, task: str) -> tuple[list[dict], np.ndarray | None]:
    from math import degrees
    import cv2
    import numpy as np
    objects = []
    source = result.obb if task == "obb" else result.boxes
    if source is None:
        return objects, np.zeros((0, *result.orig_shape), dtype=np.uint8) if task == "segment" else None
    for i in range(len(source)):
        item = {"id": f"prediction:{i}", "classIndex": int(source.cls[i]), "confidence": float(source.conf[i])}
        if task == "obb":
            cx, cy, width, height, angle = source.xywhr[i].cpu().tolist()
            item.update(type="obb", obb={"cx": cx, "cy": cy, "width": width, "height": height,
                                         "angle": degrees(angle)})
        else:
            x1, y1, x2, y2 = source.xyxy[i].cpu().tolist()
            item.update(type="bbox", bbox={"x": x1, "y": y1, "width": x2-x1, "height": y2-y1})
        objects.append(item)
    masks = None
    if task == "segment":
        height, width = result.orig_shape
        masks = np.zeros((len(objects), height, width), dtype=np.uint8)
        for index, item in enumerate(objects):
            mask = result.masks.data[index].cpu().numpy().astype(np.uint8)
            masks[index] = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
            contours, hierarchy = cv2.findContours(masks[index], cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            outlines = [contour[:, 0].tolist() for contour in contours]
            item["contours"] = outlines
            item["editable"] = len(outlines) == 1 and 3 <= len(outlines[0]) <= 4000
            # Preserve all contours; do not concatenate disconnected components or holes.
            if item["editable"]:
                item["polygon"] = outlines[0]
    return objects, masks
