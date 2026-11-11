"""Memory usage and capacity must come from the same resource boundary."""

from pathlib import Path, PurePosixPath

import psutil


def _cgroup_directories() -> list[tuple[Path, int]]:
    try:
        memberships = {}
        for line in Path('/proc/self/cgroup').read_text().splitlines():
            hierarchy, controllers, member = line.split(':', 2)
            if 'memory' in controllers.split(','):
                memberships[1] = PurePosixPath(member)
            elif hierarchy == '0' and not controllers:
                memberships[2] = PurePosixPath(member)
        directories = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            location, filesystem = line.split(' - ', 1)
            fields, options = location.split(), filesystem.split()
            version = 2 if options[0] == 'cgroup2' else 1
            if options[0] not in ('cgroup', 'cgroup2') or version not in memberships:
                continue
            if version == 1 and 'memory' not in options[2].split(','):
                continue
            root, member = PurePosixPath(fields[3]), memberships[version]
            if member.is_relative_to(root):
                relative = member.relative_to(root)
            elif member == PurePosixPath('/'):
                relative = PurePosixPath('.')
            else:
                continue
            mount = Path(fields[4].replace('\\040', ' ').replace('\\134', '\\'))
            current = mount / str(relative)
            while current.is_relative_to(mount):
                directories.append((current, version))
                if current == mount:
                    break
                current = current.parent
        return directories
    except (OSError, ValueError, IndexError):
        return []


def _read_bytes(path: Path) -> int | None:
    try:
        value = int(path.read_text().strip())
        return value if value >= 0 else None
    except (OSError, ValueError):
        return None


def memory_sample() -> dict:
    try:
        host = psutil.virtual_memory()
    except (OSError, psutil.Error):
        return {}
    values = {'memoryScope': 'host', 'hostMemoryUsedBytes': host.total - host.available,
              'hostMemoryTotalBytes': host.total}
    for directory, version in _cgroup_directories():
        limit = _read_bytes(directory / ('memory.max' if version == 2 else 'memory.limit_in_bytes'))
        if limit is None or limit <= 0 or limit >= values['hostMemoryTotalBytes']:
            continue
        usage = _read_bytes(directory / ('memory.current' if version == 2 else 'memory.usage_in_bytes'))
        values = {'memoryScope': 'container', 'hostMemoryTotalBytes': limit}
        if usage is not None:
            values['hostMemoryUsedBytes'] = usage
    return values
