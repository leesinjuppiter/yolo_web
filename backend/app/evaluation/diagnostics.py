"""Object evidence and class-aware matching at the displayed diagnostic threshold."""
from math import radians

import cv2
import numpy as np
import torch


def match_objects(overlap: np.ndarray, target_classes: list[int], prediction_classes: list[int],
                  threshold: float) -> dict:
    # Match the installed Ultralytics validator's descending-overlap, unique prediction/GT policy.
    correct_class = np.asarray(target_classes)[:, None] == np.asarray(prediction_classes)[None, :]
    values = overlap * correct_class
    pairs = np.array(np.nonzero(values >= threshold)).T
    if len(pairs) > 1:
        pairs = pairs[values[pairs[:, 0], pairs[:, 1]].argsort()[::-1]]
        pairs = pairs[np.unique(pairs[:, 1], return_index=True)[1]]
        pairs = pairs[np.unique(pairs[:, 0], return_index=True)[1]]
    matches = [{"groundTruthIndex": int(g), "predictionIndex": int(p), "overlap": float(values[g, p])}
               for g, p in pairs]
    return {"matches": matches,
            "unmatchedPredictions": sorted(set(range(len(prediction_classes))) - {int(p) for _, p in pairs}),
            "unmatchedGroundTruth": sorted(set(range(len(target_classes))) - {int(g) for g, _ in pairs}),
            "summary": {"tp": len(pairs), "fp": len(prediction_classes) - len(pairs),
                        "fn": len(target_classes) - len(pairs)}}


def _boxes(annotations: list[dict]) -> torch.Tensor:
    boxes = []
    for item in annotations:
        if item["type"] == "polygon":
            points = np.asarray(item["polygon"])
            boxes.append([*points.min(axis=0), *points.max(axis=0)])
        else:
            b = item["bbox"]
            boxes.append([b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]])
    return torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4)


def _rotated(annotations: list[dict]) -> torch.Tensor:
    return torch.tensor([[b["cx"], b["cy"], b["width"], b["height"], radians(b["angle"])]
                         for item in annotations for b in [item["obb"]]], dtype=torch.float32).reshape(-1, 5)


def ground_truth_masks(annotations: list[dict], width: int, height: int) -> np.ndarray:
    masks = np.zeros((len(annotations), height, width), dtype=np.uint8)
    for mask, item in zip(masks, annotations):
        cv2.fillPoly(mask, [np.asarray(item["polygon"], dtype=np.int32)], 1)
    return masks


def diagnose(ground_truth: list[dict], predictions: list[dict], task: str, indices: dict[str, int],
             threshold: float, width: int, height: int, prediction_masks=None) -> dict:
    from ultralytics.utils.metrics import batch_probiou, box_iou, mask_iou
    target = [indices[item["class_id"]] for item in ground_truth]
    predicted = [item["classIndex"] for item in predictions]
    if task == "obb":
        overlap = batch_probiou(_rotated(ground_truth), _rotated(predictions)).numpy()
    elif task == "segment":
        gt_masks = ground_truth_masks(ground_truth, width, height)
        gt = torch.from_numpy(gt_masks).reshape(len(target), width * height).float()
        pred = torch.from_numpy(prediction_masks).reshape(len(predicted), width * height).float()
        overlap = mask_iou(gt, pred).numpy()
    else:
        overlap = box_iou(_boxes(ground_truth), _boxes(predictions)).numpy()
    result = match_objects(overlap, target, predicted, threshold)
    if task == "segment":
        box_overlap = box_iou(_boxes(ground_truth), _boxes(predictions)).numpy()
        result["box"] = match_objects(box_overlap, target, predicted, threshold)
    return result
