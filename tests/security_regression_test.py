"""Regression tests for redirect, path, and response hardening."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/app")

database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_PATH"] = database_file.name
os.environ["SECRET_KEY"] = "ci-security-secret"
os.environ["UPDATE_CHECKER_ENABLED"] = "false"

try:
    from app import app
    from utils.redirects import is_safe_local_url
    from werkzeug.security import generate_password_hash

    assert is_safe_local_url("/produkt/1?tab=details")
    for unsafe in (
        "https://attacker.invalid/path",
        "//attacker.invalid/path",
        "/%2Fattacker.invalid/path",
        "/%252Fattacker.invalid/path",
        "/\\attacker.invalid/path",
        "javascript:alert(1)",
        "/path\r\nX-Test: injected",
    ):
        assert not is_safe_local_url(unsafe), unsafe

    app.config.update(TESTING=True)
    client = app.test_client()

    # Language changes must never redirect to a Referer-controlled host.
    response = client.get(
        "/sprache/en",
        headers={"Referer": "https://attacker.invalid/collect"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    conn = sqlite3.connect(database_file.name)
    conn.execute(
        "INSERT INTO benutzer "
        "(name, login_name, password_hash, rolle, aktiv) "
        "VALUES (?, ?, ?, ?, 1)",
        ("Security Test", "security", generate_password_hash("correct"), "user"),
    )
    conn.execute(
        "UPDATE einstellungen SET wert='1' "
        "WHERE schluessel='benutzerkonten_aktiv'"
    )
    conn.commit()
    conn.close()

    # A successful login may only return to a local application path.
    response = client.post(
        "/anmelden?next=//attacker.invalid/collect",
        data={"login_name": "security", "password": "correct"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    print("All security regression tests passed.")
finally:
    os.unlink(database_file.name)
