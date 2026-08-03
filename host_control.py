"""Explicit, opt-in Raspberry Pi host power controls for Docker installs."""

from urllib.parse import quote

from docker_update import docker_request, managed_container


ALLOWED_ACTIONS = {"reboot", "poweroff"}


def request_host_action(action):
    """Start a one-shot helper in the host PID/mount namespace."""
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported host action")

    container = managed_container()
    image = container.get("Config", {}).get("Image", "")
    if not image:
        raise RuntimeError("Application image could not be determined.")

    helper_name = f"smart-drink-fridge-host-{action}"
    try:
        docker_request(
            "DELETE",
            f"/containers/{quote(helper_name, safe='')}?force=1",
        )
    except RuntimeError:
        pass

    helper = docker_request(
        "POST",
        f"/containers/create?name={quote(helper_name, safe='')}",
        {
            "Image": image,
            "Cmd": [
                "/usr/bin/nsenter",
                "--target", "1",
                "--mount", "--uts", "--ipc", "--net", "--pid",
                "--",
                "/bin/systemctl",
                action,
            ],
            "HostConfig": {
                "AutoRemove": True,
                "Privileged": True,
                "PidMode": "host",
                "NetworkMode": "none",
            },
        },
    )
    docker_request("POST", f"/containers/{helper['Id']}/start")
    return True
