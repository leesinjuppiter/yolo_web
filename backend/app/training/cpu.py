"""CPU identity published by the training worker alongside its GPU devices."""

import platform
import re
from pathlib import Path

CPU = {"id": "cpu", "name": "本机 CPU", "kind": "cpu"}


def _cpu_identity() -> tuple[str, str]:
    name, vendor = "", ""
    try:
        if platform.system() == "Windows":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
                vendor = winreg.QueryValueEx(key, "VendorIdentifier")[0].strip()
        else:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() == "model name":
                    name = value.strip()
                elif separator and key.strip() == "vendor_id":
                    vendor = value.strip()
                if name and vendor:
                    break
    except (OSError, ValueError):
        pass
    return name or platform.processor().strip(), vendor


def cpu_device() -> dict:
    name, vendor = _cpu_identity()
    if vendor == "AuthenticAMD":
        brand = "amd"
    elif vendor == "GenuineIntel":
        brand = "intel"
    elif re.search(r"\bAMD\b", name, re.IGNORECASE):
        brand = "amd"
    elif re.search(r"\bIntel\b", name, re.IGNORECASE):
        brand = "intel"
    else:
        brand = "unknown"
    return {**CPU, "name": name or CPU["name"], "vendor": brand, "architecture": platform.machine()}
