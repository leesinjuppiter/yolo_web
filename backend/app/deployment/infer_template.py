"""Run package verification before loading the packaged ONNX model."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from verify import verify


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    verify(root)
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    from ultralytics import YOLO
    import torch
    torch.set_num_threads(2)
    meta = json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    model = YOLO(str(root/"model"/"model.onnx"), task=meta["taskType"])
    results = model.predict(str(args.image), imgsz=meta["input"]["shape"][-1], device="cpu",
                            conf=meta["pipeline"]["conf"], iou=meta["pipeline"]["iou"],
                            max_det=meta["pipeline"]["maxDet"], rect=False, verbose=False)
    print(json.dumps([json.loads(result.to_json()) for result in results], ensure_ascii=False))


if __name__ == "__main__":
    main()
