from pathlib import Path
from types import SimpleNamespace

import pytest

from app.training import memory
from app.training.resources import ResourceSampler, resource_status

GiB = 1024**3


@pytest.fixture
def cgroup(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    monkeypatch.setattr(memory.psutil, 'virtual_memory', lambda: SimpleNamespace(total=503 * GiB, available=400 * GiB))
    monkeypatch.setattr(memory, 'Path', lambda name: proc / Path(name).name
                        if str(name).startswith('/proc/self/') else Path(name))

    def setup(version, *, root='/docker/instance', member='/docker/instance', limit='67075309568', usage=str(12 * GiB)):
        mount = tmp_path / 'memory'
        mount.mkdir(exist_ok=True)
        controller = '0::' if version == 2 else '11:memory:'
        (proc / 'cgroup').write_text(controller + member + '\n')
        filesystem = 'cgroup2 cgroup rw' if version == 2 else 'cgroup cgroup rw,memory'
        (proc / 'mountinfo').write_text(f'1 0 0:1 {root} {mount.as_posix()} ro - {filesystem}\n')
        relative = member.removeprefix(root).lstrip('/') if member != '/' else ''
        directory = mount / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ('memory.max' if version == 2 else 'memory.limit_in_bytes')).write_text(limit)
        if usage is not None:
            (directory / ('memory.current' if version == 2 else 'memory.usage_in_bytes')).write_text(usage)
        return mount, directory

    return setup


def test_sampler_uses_instance_capacity_instead_of_503_gib_host(cgroup, monkeypatch):
    import os
    cgroup(1)
    monkeypatch.setattr('app.training.resources._SAMPLE_INTERVAL', 0)
    sample = ResourceSampler(os.getpid()).sample()
    assert sample['memoryScope'] == 'container'
    assert sample['hostMemoryTotalBytes'] == 67075309568
    assert sample['hostMemoryUsedBytes'] == 12 * GiB


@pytest.mark.parametrize('version, root, member', [(1, '/docker/instance', '/'),
                                                  (2, '/', '/batch/training'),
                                                  (2, '/docker/instance', '/')])
def test_cgroup_mount_and_namespace_paths(cgroup, version, root, member):
    cgroup(version, root=root, member=member)
    assert memory.memory_sample() == {'memoryScope': 'container', 'hostMemoryTotalBytes': 67075309568,
                                      'hostMemoryUsedBytes': 12 * GiB}


def test_smaller_visible_parent_limit_uses_parent_usage(cgroup):
    mount, _ = cgroup(2, root='/', member='/training', limit=str(100 * GiB), usage=str(3 * GiB))
    (mount / 'memory.max').write_text(str(64 * GiB))
    (mount / 'memory.current').write_text(str(20 * GiB))
    assert memory.memory_sample() == {'memoryScope': 'container', 'hostMemoryTotalBytes': 64 * GiB,
                                      'hostMemoryUsedBytes': 20 * GiB}


@pytest.mark.parametrize('version, limit', [(1, '9223372036854771712'), (2, 'max'), (2, 'invalid'), (1, '-1')])
def test_unlimited_or_invalid_limit_keeps_explicit_host_scope(cgroup, version, limit):
    cgroup(version, limit=limit)
    assert memory.memory_sample() == {'memoryScope': 'host', 'hostMemoryTotalBytes': 503 * GiB,
                                      'hostMemoryUsedBytes': 103 * GiB}


def test_unavailable_container_usage_never_uses_host_numerator(cgroup):
    cgroup(2, usage=None)
    assert memory.memory_sample() == {'memoryScope': 'container', 'hostMemoryTotalBytes': 67075309568}


def test_host_without_cgroup_files(cgroup):
    assert memory.memory_sample() == {'memoryScope': 'host', 'hostMemoryTotalBytes': 503 * GiB,
                                      'hostMemoryUsedBytes': 103 * GiB}


def test_historical_sample_is_not_rewritten_with_current_capacity():
    sample = {'sampledAt': '2026-11-11T12:00:00+00:00', 'hostMemoryTotalBytes': 503 * GiB,
              'hostMemoryUsedBytes': 103 * GiB}
    task = SimpleNamespace(status='succeeded', environment={'resourceSample': sample})
    assert resource_status(task) == {'state': 'finished', 'sample': sample}
    assert 'memoryScope' not in sample
