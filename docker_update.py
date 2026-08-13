import http.client
import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from database import get_setting, set_setting
from version import CURRENT_VERSION


DOCKER_SOCKET = "/var/run/docker.sock"
WATCHTOWER_IMAGE = "containrrr/watchtower:latest"
EXPECTED_IMAGE = "ghcr.io/derrobin99/smart-drink-fridge"
HELPER_NAME = "smart-drink-fridge-updater"
DEFAULT_CONTAINER_NAME = "smart-drink-fridge-web"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost")

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(DOCKER_SOCKET)


def docker_request(method, path, body=None):
    connection = UnixHTTPConnection()
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()

    if response.status >= 400:
        message = data.decode(errors="replace")
        raise RuntimeError(f"Docker API {response.status}: {message}")

    if not data:
        return None

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        if "/logs?" in path:
            return decode_docker_logs(data)
        return data.decode(errors="replace")


def decode_docker_logs(data):
    """Decode Docker's multiplexed stdout/stderr stream."""
    output = []
    position = 0
    while position + 8 <= len(data):
        size = int.from_bytes(data[position + 4:position + 8], "big")
        start = position + 8
        end = start + size
        if end > len(data):
            break
        output.append(data[start:end])
        position = end
    if not output:
        output = [data]
    return b"".join(output).decode(errors="replace")


def managed_container():
    candidates = [
        os.getenv("DOCKER_CONTAINER_NAME", "").strip(),
        DEFAULT_CONTAINER_NAME,
        os.uname().nodename,
    ]
    for candidate in dict.fromkeys(filter(None, candidates)):
        try:
            return docker_request(
                "GET",
                f"/containers/{quote(candidate, safe='')}/json",
            )
        except (OSError, RuntimeError):
            continue
    raise RuntimeError("Smart Drink Fridge Docker container not found.")


def managed_container_names():
    """Find all Compose services that use the official application image."""
    web_container = managed_container()
    project = (
        web_container.get("Config", {}).get("Labels", {}) or {}
    ).get("com.docker.compose.project", "")
    containers = docker_request("GET", "/containers/json") or []
    names = []
    for container in containers:
        image = container.get("Image", "")
        container_names = container.get("Names", [])
        if not container_names:
            continue
        name = container_names[0].lstrip("/")
        if image.startswith(f"{EXPECTED_IMAGE}:"):
            names.append(name)
            continue
        labels = container.get("Labels", {}) or {}
        if not project or labels.get("com.docker.compose.project") != project:
            continue
        try:
            details = docker_request(
                "GET", f"/containers/{quote(name, safe='')}/json"
            )
        except (OSError, RuntimeError):
            continue
        configured_image = details.get("Config", {}).get("Image", "")
        if configured_image.startswith(f"{EXPECTED_IMAGE}:"):
            names.append(name)

    if not names:
        names.append(web_container["Name"].lstrip("/"))
    return sorted(set(names))


def companion_update_needed():
    """Return whether an official companion runs a different image ID."""
    web_container = managed_container()
    web_image_id = web_container.get("Image", "")
    if not web_image_id:
        return False

    for name in managed_container_names():
        try:
            container = docker_request(
                "GET",
                f"/containers/{quote(name, safe='')}/json",
            )
        except (OSError, RuntimeError):
            continue
        if container.get("Image", "") != web_image_id:
            return True
    return False


def docker_update_available():
    if os.getenv("DOCKER_UPDATE_ENABLED", "false").lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False

    if not os.path.exists(DOCKER_SOCKET):
        return False

    try:
        container = managed_container()
    except (OSError, RuntimeError):
        return False

    image = container.get("Config", {}).get("Image", "")
    return image.startswith(f"{EXPECTED_IMAGE}:")


def docker_update_in_progress():
    try:
        helper = docker_request("GET", f"/containers/{HELPER_NAME}/json")
    except (OSError, RuntimeError):
        return False

    return helper.get("State", {}).get("Status") in {
        "created",
        "running",
        "restarting",
    }


def _version_tuple(version):
    try:
        return tuple(int(part) for part in version.lstrip("v").split("."))
    except (AttributeError, ValueError):
        return (0,)


def _last_log_line(logs):
    lines = [line.strip() for line in str(logs or "").splitlines() if line.strip()]
    return lines[-1][-240:] if lines else ""


def docker_update_status():
    """Return a persistent, user-facing update state with coarse progress."""
    target = get_setting("update_install_target", "")
    stored_status = get_setting("update_install_status", "idle")
    started_at = get_setting("update_install_started_at", "")
    error = get_setting("update_install_error", "")

    if target and _version_tuple(CURRENT_VERSION) >= _version_tuple(target):
        if stored_status != "success":
            set_setting("update_install_status", "success")
            set_setting("update_install_error", "")
            try:
                from utils.apns import send_mobile_push

                send_mobile_push(
                    "updates",
                    "Update installed",
                    f"Smart Drink Fridge {CURRENT_VERSION} is now running.",
                )
            except Exception:
                # Update state must remain available even when APNs is offline.
                pass
        return {
            "status": "success", "phase": "complete", "progress": 100,
            "target": target, "started_at": started_at, "detail": "", "error": "",
        }

    try:
        helper = docker_request("GET", f"/containers/{HELPER_NAME}/json")
        state = helper.get("State", {})
        helper_status = state.get("Status", "unknown")
        logs = docker_request(
            "GET",
            f"/containers/{HELPER_NAME}/logs?stdout=1&stderr=1&tail=40",
        )
        detail = _last_log_line(logs)
    except (OSError, RuntimeError):
        helper = None
        helper_status = "missing"
        detail = ""

    if helper_status in {"created", "restarting"}:
        status, phase, progress = "running", "preparing", 15
    elif helper_status == "running":
        lower_logs = str(logs).lower()
        if "stopping" in lower_logs or "restarting" in lower_logs:
            phase, progress = "restarting", 80
        elif "found new" in lower_logs or "pulling" in lower_logs:
            phase, progress = "downloading", 55
        elif "checking" in lower_logs or "scanning" in lower_logs:
            phase, progress = "checking", 35
        else:
            phase, progress = "preparing", 20
        status = "running"
    elif helper_status in {"exited", "dead"}:
        exit_code = helper.get("State", {}).get("ExitCode", 1)
        if exit_code == 0:
            status, phase, progress = "running", "reconnecting", 90
        else:
            status, phase, progress = "failed", "failed", 100
            error = detail or f"Updater exited with code {exit_code}."
            set_setting("update_install_status", "failed")
            set_setting("update_install_error", error)
    elif stored_status in {"starting", "running"}:
        try:
            started = datetime.fromisoformat(started_at)
        except (TypeError, ValueError):
            started = datetime.now()
        if datetime.now() - started > timedelta(minutes=20):
            status, phase, progress = "failed", "failed", 100
            error = error or "Updater status could not be determined."
            set_setting("update_install_status", "failed")
            set_setting("update_install_error", error)
        else:
            status, phase, progress = "running", "preparing", 10
    else:
        status, phase, progress = stored_status, stored_status, 0

    return {
        "status": status,
        "phase": phase,
        "progress": progress,
        "target": target,
        "started_at": started_at,
        "detail": detail,
        "error": error,
    }


def start_docker_update(target_version=""):
    if not docker_update_available():
        raise RuntimeError("Docker update is not configured.")

    if docker_update_in_progress():
        return False

    set_setting("update_install_status", "starting")
    set_setting("update_install_target", target_version or "")
    set_setting(
        "update_install_started_at",
        datetime.now().isoformat(timespec="seconds"),
    )
    set_setting("update_install_error", "")

    try:
        container_names = managed_container_names()

        docker_request(
            "POST",
            "/images/create"
            f"?fromImage={quote('containrrr/watchtower', safe='')}"
            "&tag=latest",
        )

        try:
            docker_request("DELETE", f"/containers/{HELPER_NAME}?force=1")
        except RuntimeError:
            pass

        helper = docker_request(
            "POST",
            f"/containers/create?name={HELPER_NAME}",
            {
                "Image": WATCHTOWER_IMAGE,
                "Cmd": [
                    "--run-once",
                    "--cleanup",
                    "--rolling-restart",
                    *container_names,
                ],
                "HostConfig": {
                    "AutoRemove": False,
                    "Binds": [f"{DOCKER_SOCKET}:{DOCKER_SOCKET}"],
                },
            },
        )
        docker_request("POST", f"/containers/{helper['Id']}/start")
    except Exception as exc:
        set_setting("update_install_status", "failed")
        set_setting("update_install_error", str(exc)[:500])
        raise

    set_setting("update_install_status", "running")
    return True


def _reconcile_companions_loop():
    # A 1.3.x one-click update replaces only the web container. Wait for its
    # old Watchtower helper to finish, then update scanner/NFC/display too.
    time.sleep(15)
    for _ in range(12):
        try:
            if not docker_update_available() or not companion_update_needed():
                return
            if not docker_update_in_progress():
                start_docker_update()
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(10)


def start_companion_reconciliation():
    if not docker_update_available():
        return False
    threading.Thread(
        target=_reconcile_companions_loop,
        name="update-companion-reconciliation",
        daemon=True,
    ).start()
    return True
