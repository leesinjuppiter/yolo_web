"""Isolated prediction runner; no database access."""
import json
from pathlib import Path
import sys
from uuid import uuid4


def annotations(result, task_type, classes):
    values = []
    unsupported = False
    objects = result.obb if task_type == "obb" else result.boxes
    if objects is None:
        return values, unsupported
    for index, obj in enumerate(objects):
        class_index = int(obj.cls.item())
        value = {"id": str(uuid4()), "class_id": classes[class_index]["id"], "source": "manual"}
        if task_type == "detect":
            x1, y1, x2, y2 = obj.xyxy[0].tolist()
            value.update(type="bbox", bbox={"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1})
        elif task_type == "obb":
            from math import degrees
            cx, cy, width, height, angle = obj.xywhr[0].tolist()
            value.update(type="obb", obb={"cx": cx, "cy": cy, "width": width, "height": height,
                                          "angle": degrees(angle)})
        else:
            import cv2
            mask = result.masks.data[index].cpu().numpy().astype("uint8")
            contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            if len(contours) != 1 or hierarchy is None:
                unsupported = True
                continue
            points = result.masks.xy[index].tolist()
            if not 3 <= len(points) <= 4000:
                unsupported = True
                continue
            value.update(type="polygon", polygon=points)
        values.append(value)
    return values, unsupported


def run(job):
    from ultralytics import YOLO
    from app.core.storage import resolve_image
    from hashlib import sha256
    config = job["config"]
    model = YOLO(job["modelPath"])
    rows = []
    for index, image in enumerate(job["inputs"]):
        path = resolve_image(image["storagePath"])
        if sha256(path.read_bytes()).hexdigest() != image["imageSha256"]:
            raise ValueError("推荐输入原图已发生变化")
        result = model.predict(str(path), device=config["deviceId"], imgsz=config["imageSize"],
            conf=config["retainConfidence"], iou=config["nmsIou"], retina_masks=True, verbose=False)[0]
        objects = result.obb if job["taskType"] == "obb" else result.boxes
        confidences = [] if objects is None else objects.conf.cpu().tolist()
        matched = [score for score in confidences if config["minConfidence"] <= score < config["maxConfidence"]]
        if matched or (not confidences and config["includeNoPredictions"]):
            converted, unsupported = annotations(result, job["taskType"], job["classes"])
            rows.append({**image, "confidence": min(matched) if matched else None,
                         "lowConfidenceCount": len(matched), "predictions": converted,
                         "unsupportedPrediction": unsupported,
                         "reasons": ["low_confidence" if matched else "no_predictions"]})
        print(json.dumps({"processed": index + 1}), flush=True)
    rows.sort(key=lambda row: (row["confidence"] is None, row["confidence"] or 0,
                               -row["lowConfidenceCount"], row["imageId"]))
    return rows[:config["candidateLimit"]]


if __name__ == "__main__":
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = run(job)
    Path(job["output"]).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
