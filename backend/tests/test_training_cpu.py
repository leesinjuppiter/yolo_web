from contextlib import nullcontext
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import sys

import pytest

from app.training import cpu, devices
from test_dataset_api import client


@pytest.mark.parametrize('name, vendor, expected', [
    ('AMD EPYC 7601 32-Core Processor', 'AuthenticAMD', 'amd'),
    ('Intel(R) Xeon(R) Gold 6338 CPU', 'GenuineIntel', 'intel'),
    ('AMD Ryzen 9 7950X', '', 'amd'),
    ('Intel Core i7', '', 'intel'),
    ('ARM Neoverse', '', 'unknown'),
    ('', '', 'unknown'),
])
def test_cpu_vendor_matches_detected_identity(monkeypatch, name, vendor, expected):
    monkeypatch.setattr(cpu, '_cpu_identity', lambda: (name, vendor))
    monkeypatch.setattr(cpu.platform, 'machine', lambda: 'x86_64')
    result = cpu.cpu_device()
    assert result == {**cpu.CPU, 'name': name or '本机 CPU', 'vendor': expected, 'architecture': 'x86_64'}


def test_linux_reads_model_name_after_vendor_instead_of_platform_architecture(monkeypatch):
    monkeypatch.setattr(cpu.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(cpu.platform, 'processor', lambda: 'x86_64')
    monkeypatch.setattr(cpu, 'Path', lambda _: SimpleNamespace(read_text=lambda:
        'processor : 0\nvendor_id : AuthenticAMD\ncpu family : 23\nmodel name : AMD EPYC 7601 32-Core Processor\n'))
    assert cpu._cpu_identity() == ('AMD EPYC 7601 32-Core Processor', 'AuthenticAMD')


def test_windows_reads_processor_model_and_vendor_from_registry(monkeypatch):
    monkeypatch.setattr(cpu.platform, 'system', lambda: 'Windows')
    values = {'ProcessorNameString': ' Intel(R) Core(TM) i7-13700 ', 'VendorIdentifier': 'GenuineIntel'}
    registry = SimpleNamespace(HKEY_LOCAL_MACHINE=object(), OpenKey=lambda *_: nullcontext(object()),
                               QueryValueEx=lambda _, name: (values[name], 1))
    monkeypatch.setitem(sys.modules, 'winreg', registry)
    assert cpu._cpu_identity() == ('Intel(R) Core(TM) i7-13700', 'GenuineIntel')


def test_unavailable_cpu_file_uses_platform_fallback(monkeypatch):
    monkeypatch.setattr(cpu.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(cpu.platform, 'processor', lambda: 'unknown processor')
    def missing(_):
        raise FileNotFoundError()
    monkeypatch.setattr(cpu, 'Path', missing)
    assert cpu._cpu_identity() == ('unknown processor', '')


def test_cpu_is_reported_when_worker_has_no_cuda(monkeypatch):
    monkeypatch.setattr(cpu, '_cpu_identity', lambda: ('Intel Xeon', 'GenuineIntel'))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(__version__='test', version=SimpleNamespace(cuda=None),
                                                           cuda=SimpleNamespace(is_available=lambda: False)))
    result = devices.probe_devices()
    assert len(result['devices']) == 1
    assert result['devices'][0]['name'] == 'Intel Xeon'
    assert result['devices'][0]['vendor'] == 'intel'


def test_overview_uses_worker_cpu_identity_and_environment_versions(client, monkeypatch):
    monkeypatch.setattr(cpu, '_cpu_identity', lambda: ('AMD EPYC test', 'AuthenticAMD'))
    device = cpu.cpu_device()
    path = devices._capability_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'sampledAt': datetime.now(timezone.utc).isoformat(), 'devices': [device],
                                'versions': {'torch': '2.8.0', 'cuda': '12.8'}}))
    response = client.get('/api/training')
    assert response.status_code == 200, response.text
    assert response.json()['devices'] == [device]
    assert response.json()['workerStatus']['state'] == 'live'
    assert response.json()['workerStatus']['versions'] == {'torch': '2.8.0', 'cuda': '12.8'}
