import http.client
import json
import os
import socket
from urllib.parse import quote


DOCKER_SOCKET = "/var/run/docker.sock"
WATCHTOWER_IMAGE = "containrrr/watchtower:latest"
EXPECTED_IMAGE = "ghcr.io/derrobin99/smart-drink-fridge"
HELPER_NAME = "smart-drink-fridge-updater"


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
        return data.decode(errors="replace")


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
        container = docker_request("GET", f"/containers/{os.uname().nodename}/json")
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


def start_docker_update():
    if not docker_update_available():
        raise RuntimeError("Docker update is not configured.")

    if docker_update_in_progress():
        return False

    container_id = os.uname().nodename
    container = docker_request("GET", f"/containers/{container_id}/json")
    container_name = container["Name"].lstrip("/")

    docker_request(
        "POST",
        "/images/create"
        f"?fromImage={quote('containrrr/watchtower', safe='')}"
        "&tag=latest",
    )

    try:
        docker_request("DELETE", f"/containers/{HELPER_NAME}")
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
                container_name,
            ],
            "HostConfig": {
                "AutoRemove": True,
                "Binds": [f"{DOCKER_SOCKET}:{DOCKER_SOCKET}"],
            },
        },
    )
    docker_request("POST", f"/containers/{helper['Id']}/start")
    return True
