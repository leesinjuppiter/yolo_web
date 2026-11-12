"""Single-image validation previews from the frozen inputs and best checkpoint."""

import json
from math import cos, radians, sin
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def read_previews(directory: Path) -> list[dict]:
    path = directory / "output/previews/manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _ground_truth(source: Path, sample: dict, classes: list[dict], destination: Path) -> None:
    from matplotlib.font_manager import findfont
    from ultralytics.utils.plotting import colors

    with Image.open(source) as original:
        image = original.convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    width = max(2, round(min(image.size) / 250))
    font = ImageFont.truetype(findfont("DejaVu Sans"), max(14, round(min(image.size) / 40)))
    categories = {item["id"]: item for item in classes}
    for annotation in sample["annotations"]:
        category = categories[annotation["class_id"]]
        color = colors(category["index"], bgr=False)
        kind = annotation["type"]
        if kind == "bbox":
            box = annotation["bbox"]
            x, y = box["x"], box["y"]
            draw.rectangle((x, y, x + box["width"], y + box["height"]), outline=color, width=width)
        elif kind in ("polygon", "obb"):
            if kind == "polygon":
                points = [tuple(point) for point in annotation["polygon"]]
            else:
                box = annotation["obb"]
                angle = radians(box["angle"])
                points = [(box["cx"] + dx * cos(angle) - dy * sin(angle),
                           box["cy"] + dx * sin(angle) + dy * cos(angle))
                          for dx, dy in [(-box["width"]/2, -box["height"]/2),
                                         (box["width"]/2, -box["height"]/2),
                                         (box["width"]/2, box["height"]/2),
                                         (-box["width"]/2, box["height"]/2)]]
            draw.polygon(points, fill=(*color, 45))
            draw.line(points + [points[0]], fill=color, width=width)
            x, y = points[0]
        else:
            x, y = 8, 8
        x = min(max(0, x), max(0, image.width - draw.textlength(category["name"], font=font) - 2))
        draw.text((x, max(0, y - font.size)), category["name"], font=font,
                  fill=color, stroke_width=1, stroke_fill=(0, 0, 0))
    image.save(destination, quality=92)


def generate_previews(directory: Path, *, device: str = "cpu") -> list[dict]:
    from ultralytics import YOLO

    config = json.loads((directory / "invocation.json").read_text(encoding="utf-8"))
    frozen = directory / "input"
    manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    samples = []
    with (frozen / "samples.jsonl").open(encoding="utf-8") as source:
        for line in source:
            sample = json.loads(line)
            if sample["split"] == "val":
                samples.append(sample)
                if len(samples) == 16:
                    break
    if not samples:
        return []
    destination = directory / "output/previews"
    destination.mkdir(parents=True, exist_ok=True)
    model = YOLO(directory / "output/weights/best.pt")
    predictions = model.predict(source=[str(frozen / sample["image_path"]) for sample in samples],
                                imgsz=config["arguments"]["imgsz"], device=device, batch=1,
                                stream=True, verbose=False, save=False)
    records = []
    for index, (sample, prediction) in enumerate(zip(samples, predictions, strict=True)):
        stem = f"{index:03d}"
        prediction.save(filename=str(destination / f"{stem}_pred.jpg"))
        _ground_truth(frozen / sample["image_path"], sample, manifest["classes"], destination / f"{stem}_labels.jpg")
        records.append({"id": f"validation-{stem}", "name": sample["name"],
                        "width": sample["width"], "height": sample["height"],
                        "artifactId": f"preview-{stem}-prediction", "groundTruthArtifactId": f"preview-{stem}-labels"})
    temporary = destination / "manifest.tmp"
    temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination / "manifest.json")
    return records
