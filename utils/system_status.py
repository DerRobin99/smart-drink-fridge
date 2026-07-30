import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path

from docker_update import docker_request


def _format_bytes(value):
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024


def _format_duration(seconds):
    total_minutes = max(0, int(seconds)) // 60
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _memory_status():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return None

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)
    percent = round((used / total) * 100) if total else 0
    return {
        "used": _format_bytes(used),
        "total": _format_bytes(total),
        "percent": percent,
    }


def _cpu_temperature():
    thermal_root = Path("/sys/class/thermal")
    candidates = list(thermal_root.glob("thermal_zone*/temp"))
    for path in candidates:
        try:
            value = float(path.read_text().strip())
        except (OSError, ValueError):
            continue
        if value > 1000:
            value /= 1000
        if -20 <= value <= 150:
            return round(value, 1)
    return None


def _uptime():
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return _format_duration(seconds)


def _disk_status():
    try:
        total, used, free = shutil.disk_usage("/data")
    except OSError:
        return None
    percent = round((used / total) * 100) if total else 0
    return {
        "used": _format_bytes(used),
        "free": _format_bytes(free),
        "total": _format_bytes(total),
        "percent": percent,
    }


def _database_status():
    path = os.getenv("DATABASE_PATH", "/data/getraenke.db")
    try:
        size = Path(path).stat().st_size
    except OSError:
        return {"path": path, "size": None}
    return {"path": path, "size": _format_bytes(size)}


def _container_status():
    try:
        containers = docker_request("GET", "/containers/json?all=true")
    except (OSError, RuntimeError):
        return {"available": False, "containers": [], "camera": None}

    app_containers = []
    camera = None
    for container in containers or []:
        names = [name.lstrip("/") for name in container.get("Names", [])]
        name = names[0] if names else container.get("Id", "")[:12]
        if not name.startswith("smart-drink-fridge"):
            continue

        app_containers.append(
            {
                "name": name,
                "image": container.get("Image", ""),
                "state": container.get("State", "unknown"),
                "status": container.get("Status", ""),
            }
        )

        if name == "smart-drink-fridge-scanner":
            try:
                details = docker_request(
                    "GET",
                    f"/containers/{container['Id']}/json",
                )
                devices = (
                    details.get("HostConfig", {}).get("Devices") or []
                )
                camera = {
                    "configured": any(
                        device.get("PathOnHost") == "/dev/video0"
                        for device in devices
                    ),
                    "running": container.get("State") == "running",
                }
            except (KeyError, OSError, RuntimeError):
                camera = {"configured": False, "running": False}

    app_containers.sort(key=lambda item: item["name"])
    return {
        "available": True,
        "containers": app_containers,
        "camera": camera,
    }


def get_system_status():
    disk = _disk_status()
    try:
        load = os.getloadavg()
        load_average = " / ".join(f"{value:.2f}" for value in load)
    except (AttributeError, OSError):
        load_average = None

    return {
        "temperature": _cpu_temperature(),
        "memory": _memory_status(),
        "disk": disk,
        "database": _database_status(),
        "uptime": _uptime(),
        "load_average": load_average,
        "architecture": platform.machine(),
        "kernel": platform.release(),
        "hostname": platform.node(),
        "containers": _container_status(),
        "checked_at": datetime.now(timezone.utc),
    }
