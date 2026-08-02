from urllib.parse import unquote, urlsplit

from flask import redirect


def is_safe_local_url(target: str) -> bool:
    """Return whether target is an absolute path on this application."""
    if not isinstance(target, str):
        return False

    target = target.strip()
    if not target or any(ord(character) < 32 for character in target):
        return False

    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return False

    # Reject network-path references and encoded variants before a browser can
    # interpret them as a different host. Backslashes are treated as slashes by
    # some clients and therefore cannot appear in redirect targets either.
    decoded_path = unquote(unquote(parsed.path))
    return not decoded_path.startswith("//") and "\\" not in decoded_path


def safe_redirect(target: str, fallback: str = "/"):
    """Redirect only to a local application path."""
    destination = target if is_safe_local_url(target) else fallback
    if not is_safe_local_url(destination):
        destination = "/"
    return redirect(destination)
