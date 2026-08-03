"""Remote scanner discovery and secure pairing client tests."""

import json
import os
import sys
import tempfile

sys.path.insert(0, "/app")

with tempfile.TemporaryDirectory() as directory:
    os.environ.update({
        "SCANNER_DATA_DIR": directory,
        "SCANNER_ID": "network-1",
        "SCANNER_NAME": "Network scanner",
        "SCANNER_AUTO_DISCOVERY": "true",
        "SCANNER_SERVER_URL": "",
        "SCANNER_TOKEN": "",
    })
    import scanner_client

    scanner_client._discovered_url = None
    scanner_client.discover_server = lambda timeout=3: "http://192.0.2.10:5000"

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    calls = []

    def paired_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/pair/status"):
            return Response({"ok": True, "status": "approved", "token": "claimed-token"})
        return Response({"ok": True, "status": "pending"})

    scanner_client.requests.post = paired_post
    assert scanner_client.server_url() == "http://192.0.2.10:5000"
    assert scanner_client.ensure_pairing()
    assert scanner_client.scanner_token() == "claimed-token"
    saved = json.loads(scanner_client.credentials_path().read_text())
    assert saved == {"server_url": "http://192.0.2.10:5000", "token": "claimed-token"}
    assert scanner_client.ensure_pairing()

    # The saved URL and token survive a fresh process/cache state.
    scanner_client._discovered_url = None
    assert scanner_client.server_url() == "http://192.0.2.10:5000"
    event = scanner_client._event("12345678")
    assert event["scanner_id"] == "network-1"
    assert scanner_client._send(event)["status"] == "pending"

    # Invalid persisted state is ignored safely.
    scanner_client.credentials_path().write_text("not-json")
    assert scanner_client._credentials() == {}

print("All scanner network pairing tests passed.")
