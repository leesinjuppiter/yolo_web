from hashlib import sha256

import pytest
import torch

from app.dataset.repository import Conflict
from app.training.resume import load_checkpoint


def _save(tmp_path, **overrides):
    path = tmp_path / "last.pt"
    torch.save({"epoch": 0, "optimizer": {"state": {}, "param_groups": []},
                "train_args": {"epochs": 3}, "model": torch.nn.Linear(2, 1), **overrides}, path)
    return path, sha256(path.read_bytes()).hexdigest()


def test_complete_checkpoint_keeps_training_state(tmp_path):
    path, digest = _save(tmp_path)
    checkpoint, epoch = load_checkpoint(path, digest, 3)
    assert epoch == 0
    assert checkpoint["optimizer"] == {"state": {}, "param_groups": []}


@pytest.mark.parametrize("overrides", [{"epoch": -1}, {"epoch": 2}, {"optimizer": None},
                                      {"train_args": None}, {"model": None, "ema": None}])
def test_weights_only_finished_or_incomplete_checkpoint_is_rejected(tmp_path, overrides):
    path, digest = _save(tmp_path, **overrides)
    with pytest.raises(Conflict):
        load_checkpoint(path, digest, 3)


def test_checkpoint_hash_change_is_rejected_before_loading(tmp_path):
    path, digest = _save(tmp_path)
    path.write_bytes(b"changed")
    with pytest.raises(Conflict, match="校验失败"):
        load_checkpoint(path, digest, 3)


def test_hash_matching_but_corrupt_checkpoint_is_rejected(tmp_path):
    path = tmp_path / "last.pt"
    path.write_bytes(b"not-a-torch-checkpoint")
    with pytest.raises(Conflict, match="无法读取"):
        load_checkpoint(path, sha256(path.read_bytes()).hexdigest(), 3)
