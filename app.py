from pathlib import Path
import os
import requests
from flask import Flask, request
from datetime import datetime

from routes.backups import backup_bp
from routes.dashboard import dashboard_bp
from routes.api import api_bp
from routes.statistics import statistics_bp
from routes.products import products_bp
from routes.language import language_bp
from routes.inventory import inventory_bp
from routes.barcodes import barcodes_bp
from utils.render import HTML_START, configure_rendering, render_page
from routes.settings import create_settings_blueprint
from routes.home_assistant import home_assistant_bp

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.register_blueprint(backup_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(home_assistant_bp)
from database import init_db
from translation import load_translations, normalize_language, available_languages, get_default_language

init_db()


from version import CURRENT_VERSION

UPDATE_CHECKER_ENABLED = os.getenv(
    "UPDATE_CHECKER_ENABLED",
    "true"
).lower() in ("1", "true", "yes", "on")

UPDATE_CHECK_URL = (
    "https://api.github.com/repos/"
    "DerRobin99/smart-drink-fridge/releases/latest"
)

UPDATE_CACHE_SECONDS = 6 * 60 * 60

_update_cache = {
    "checked_at": None,
    "latest_version": None,
    "release_url": None,
}


def version_tuple(version):
    try:
        return tuple(
            int(part)
            for part in version.lstrip("v").split(".")
        )
    except (ValueError, AttributeError):
        return (0,)


def get_update_info():
    if not UPDATE_CHECKER_ENABLED:
        return None

    now = datetime.now()

    if _update_cache["checked_at"] is not None:
        age = (
            now - _update_cache["checked_at"]
        ).total_seconds()

        if age < UPDATE_CACHE_SECONDS:
            return _update_cache

    try:
        response = requests.get(
            UPDATE_CHECK_URL,
            timeout=5
        )
        response.raise_for_status()

        data = response.json()

        _update_cache["latest_version"] = data.get(
            "tag_name"
        )
        _update_cache["release_url"] = data.get(
            "html_url"
        )
        _update_cache["checked_at"] = now

    except requests.RequestException:
        # Fehler beim Update-Check sollen die Weboberfläche
        # niemals beeinträchtigen.
        _update_cache["checked_at"] = now

    latest = _update_cache["latest_version"]

    if not latest:
        return None

    _update_cache["update_available"] = (
        version_tuple(latest)
        > version_tuple(CURRENT_VERSION)
    )

    return _update_cache



# Herstellerlogos über Wikidata / Wikimedia Commons.
# Wenn kein Internet verfügbar ist oder kein Logo gefunden wird,
# wird None zurückgegeben und die Oberfläche funktioniert ohne Logo weiter.
_brand_logo_cache = {}


def get_brand_logo(marke):
    if not marke:
        return None

    cache_key = marke.strip().lower()

    if not cache_key:
        return None

    if cache_key in _brand_logo_cache:
        return _brand_logo_cache[cache_key]

    try:
        search_response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": marke,
                "language": "en",
                "format": "json",
                "limit": 10,
            },
            headers={
                "User-Agent": "SmartDrinkFridge/1.0"
            },
            timeout=3,
        )
        search_response.raise_for_status()

        results = search_response.json().get("search", [])
        normalized_brand = marke.strip().casefold()

        for result in results:
            label = (result.get("label") or "").strip()
            description = (result.get("description") or "").strip().casefold()
            entity_id = result.get("id")

            if not entity_id or not label:
                continue

            normalized_label = label.casefold()

            # Exakte oder erweiterte Markennamen akzeptieren,
            # z. B. "Bitburger Braugruppe" für "Bitburger".
            if (
                normalized_label != normalized_brand
                and normalized_brand not in normalized_label
            ):
                continue

            # Offensichtlich unpassende Treffer ausschließen.
            blocked_terms = (
                "football",
                "soccer",
                "cup",
                "tournament",
                "competition",
                "sports",
                "award",
                "film",
                "song",
                "album",
                "person",
            )

            if any(term in description for term in blocked_terms):
                continue

            entity_response = requests.get(
                f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json",
                headers={
                    "User-Agent": "SmartDrinkFridge/1.0"
                },
                timeout=3,
            )
            entity_response.raise_for_status()

            entity = (
                entity_response.json()
                .get("entities", {})
                .get(entity_id, {})
            )

            claims = entity.get("claims", {})
            logo_claims = claims.get("P154", [])

            if not logo_claims:
                continue

            try:
                filename = (
                    logo_claims[0]["mainsnak"]["datavalue"]["value"]
                )
            except (KeyError, IndexError, TypeError):
                continue

            commons_response = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "iiurlwidth": 160,
                    "titles": f"File:{filename}",
                },
                headers={
                    "User-Agent": "SmartDrinkFridge/1.0"
                },
                timeout=3,
            )
            commons_response.raise_for_status()

            pages = (
                commons_response.json()
                .get("query", {})
                .get("pages", {})
            )

            for page in pages.values():
                imageinfo = page.get("imageinfo", [])

                if imageinfo:
                    logo_url = (
                        imageinfo[0].get("thumburl")
                        or imageinfo[0].get("url")
                    )

                    if logo_url:
                        _brand_logo_cache[cache_key] = logo_url
                        return logo_url

    except (requests.RequestException, ValueError):
        pass

    _brand_logo_cache[cache_key] = None
    return None


@app.context_processor
def inject_brand_logo_helper():
    return {
        "brand_logo": get_brand_logo
    }




def verbrauch(conn, ean, modifier=None):
    if modifier:
        row = conn.execute(
            """
            SELECT COALESCE(
                -SUM(CASE WHEN menge < 0 THEN menge ELSE 0 END),
                0
            ) AS anzahl
            FROM buchungen
            WHERE ean = ?
              AND zeitpunkt >= datetime('now', 'localtime', ?)
            """,
            (ean, modifier)
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(
                -SUM(CASE WHEN menge < 0 THEN menge ELSE 0 END),
                0
            ) AS anzahl
            FROM buchungen
            WHERE ean = ?
            """,
            (ean,)
        ).fetchone()

    return row["anzahl"]



TRANSLATIONS = {
    code: load_translations(code)
    for code in available_languages()
}


def get_language():
    return normalize_language(request.cookies.get("lang"))













HTML_START += """
{% if update_info %}
<div style="margin:8px 0 16px 0;font-size:13px;text-align:right;">
{% if update_info.update_available %}
    <span style="display:inline-block;padding:5px 9px;border-radius:12px;background:#fff3cd;color:#856404;">
        ↑ {{ t("update_available") }}: {{ update_info.latest_version }}
        · <a href="{{ update_info.release_url }}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:underline;">{{ t("view_release") }}</a>
    </span>
{% else %}
    <span style="display:inline-block;padding:5px 9px;border-radius:12px;background:#d1e7dd;color:#0f5132;">
        ✓ {{ t("up_to_date") }} · {{ current_version }}
    </span>
{% endif %}
</div>
{% endif %}
"""



































configure_rendering(
    get_language_callback=get_language,
    get_update_info_callback=get_update_info,
    translations=TRANSLATIONS,
    current_version=CURRENT_VERSION,
)


settings_bp = create_settings_blueprint(
    render_page=render_page,
    html_start=HTML_START,
    available_languages=available_languages,
)
app.register_blueprint(settings_bp)
app.register_blueprint(statistics_bp)
app.register_blueprint(products_bp)
app.register_blueprint(language_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(barcodes_bp)
app.register_blueprint(api_bp)


if __name__ == "__main__":
    import socket
    from zeroconf import ServiceInfo, Zeroconf

    hostname = socket.gethostname()

    # Determine the real LAN IP instead of relying on hostname resolution,
    # which may return a loopback address such as 127.0.1.1.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip_address = sock.getsockname()[0]
    finally:
        sock.close()

    zeroconf = Zeroconf()

    service_info = ServiceInfo(
        "_smartfridge._tcp.local.",
        f"{hostname}._smartfridge._tcp.local.",
        addresses=[socket.inet_aton(ip_address)],
        port=5000,
        properties={
            "name": "Smart Drink Fridge",
            "version": CURRENT_VERSION,
        },
        server=f"{hostname}.local.",
    )

    zeroconf.register_service(service_info)

    try:
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False
        )
    finally:
        zeroconf.unregister_service(service_info)
        zeroconf.close()
