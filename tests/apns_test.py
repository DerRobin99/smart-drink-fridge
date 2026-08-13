import os
import tempfile
from unittest.mock import patch

from utils import apns


class FakeConnection:
    def __init__(self, devices):
        self.devices = devices
        self.updated = []
        self.closed = False

    def execute(self, query, params=()):
        if query.lstrip().startswith("SELECT"):
            return self
        self.updated.append((query, tuple(params)))
        return self

    def fetchall(self):
        return self.devices

    def commit(self):
        pass

    def close(self):
        self.closed = True


class FakeResponse:
    def __init__(self, status_code, reason=""):
        self.status_code = status_code
        self.content = b"x" if reason else b""
        self._reason = reason

    def json(self):
        return {"reason": self._reason}


class FakeClient:
    responses = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_mobile_push_delivery_and_invalid_token():
    key = tempfile.NamedTemporaryFile(delete=False)
    key.close()
    connection = FakeConnection([
        {"id": 1, "device_token": "one", "environment": "production"},
        {"id": 2, "device_token": "two", "environment": "development"},
    ])
    FakeClient.responses = [FakeResponse(200), FakeResponse(410, "Unregistered")]
    with patch.dict(os.environ, {
        "APNS_PRIVATE_KEY_PATH": key.name,
        "APNS_KEY_ID": "KEY",
        "APNS_TEAM_ID": "TEAM",
    }, clear=False), patch.object(apns, "_provider_token", return_value="jwt"), \
            patch.object(apns, "get_db", return_value=connection), \
            patch.object(apns.httpx, "Client", FakeClient):
        result = apns.send_mobile_push("low_stock", "title", "message")

    assert result == {"sent": 1, "failed": 1, "reason": "sent"}
    assert connection.updated
    assert connection.closed
    os.unlink(key.name)


def test_mobile_push_skips_unknown_or_unconfigured():
    with patch.dict(os.environ, {"APNS_PRIVATE_KEY_PATH": ""}, clear=False):
        assert apns.send_mobile_push("unknown", "title", "message")["reason"] == "unknown_event"
        assert apns.send_mobile_push("updates", "title", "message")["reason"] == "not_configured"


test_mobile_push_delivery_and_invalid_token()
test_mobile_push_skips_unknown_or_unconfigured()
