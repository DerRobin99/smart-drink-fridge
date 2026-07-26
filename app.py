from pathlib import Path
import os
import requests
from flask import flash, send_from_directory, Flask, render_template_string, request, redirect, jsonify
import sqlite3
from datetime import datetime

from routes.backups import backup_bp
from routes.dashboard import dashboard_bp
from utils.db import get_db
from utils.render import (
    DETAIL_HTML,
    BARCODE_HTML,
    HTML_START,
    INDEX_HTML,
    configure_rendering,
    render_page,
)
from routes.settings import create_settings_blueprint
from routes.home_assistant import (
    home_assistant_bp,
    sync_home_assistant_shopping_list_data,
)

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.register_blueprint(backup_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(home_assistant_bp)
from database import DB, init_db, get_setting, set_setting
from backup import create_backup, list_backups
from translation import load_translations, normalize_language, available_languages

init_db()


CURRENT_VERSION = "v1.2.5"

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





def available_languages():
    translations_dir = Path(__file__).resolve().parent / "translations"
    languages = []

    flags = {
        "de": "🇩🇪",
        "en": "🇬🇧",
        "fr": "🇫🇷",
        "es": "🇪🇸",
        "it": "🇮🇹",
        "nl": "🇳🇱",
        "pt": "🇵🇹",
        "pl": "🇵🇱",
        "cs": "🇨🇿",
        "sk": "🇸🇰",
        "hu": "🇭🇺",
        "ro": "🇷🇴",
        "tr": "🇹🇷",
        "ru": "🇷🇺",
        "uk": "🇺🇦",
        "ja": "🇯🇵",
        "ko": "🇰🇷",
        "zh": "🇨🇳",
    }

    if not translations_dir.exists():
        return [("en", "🇬🇧 English")]

    for language_file in sorted(translations_dir.glob("*.lang")):
        code = language_file.stem.strip().lower()

        if not code:
            continue

        display_name = code.upper()

        try:
            for line in language_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)

                if key.strip() == "language_name" and value.strip():
                    display_name = value.strip()
                    break
        except OSError:
            continue

        display_name = f"{flags.get(code, '🌐')} {display_name}"
        languages.append((code, display_name))

    languages.sort(key=lambda item: item[1].casefold())

    return languages or [("en", "🇬🇧 English")]


def get_default_language():
    languages = available_languages()
    codes = [code for code, _ in languages]

    if "en" in codes:
        return "en"

    return codes[0]


@app.route("/sprache/<lang>")
def sprache(lang):
    lang = str(lang).strip().lower()
    available_codes = {
        code for code, _ in available_languages()
    }

    if lang not in available_codes:
        lang = get_default_language()

    response = redirect(
        request.referrer or "/"
    )

    response.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        samesite="Lax"
    )

    return response




HTML_START += """
{% if update_info %}
<div style="margin:8px 0 16px 0;font-size:13px;text-align:right;">
{% if update_info.update_available %}
    <span style="display:inline-block;padding:5px 9px;border-radius:12px;background:#fff3cd;color:#856404;">
        ↑ {% if lang == "de" %}Update verfügbar{% else %}Update available{% endif %}: {{ update_info.latest_version }}
        · <a href="{{ update_info.release_url }}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:underline;">{% if lang == "de" %}Release ansehen{% else %}View release{% endif %}</a>
    </span>
{% else %}
    <span style="display:inline-block;padding:5px 9px;border-radius:12px;background:#d1e7dd;color:#0f5132;">
        ✓ {% if lang == "de" %}Aktuell{% else %}Up to date!{% endif %} · {{ current_version }}
    </span>
{% endif %}
</div>
{% endif %}
"""



STATISTIK_HTML = HTML_START + """
<a class="zurueck" href="/">{{ t('back_to_fridge') }}</a>

<h1>📊 {{ t("statistics") }}</h1>

<div class="stats">

    <div class="stat">
        <div>{{ t("today") }}</div>
        <div class="stat-zahl">{{ stats.heute }}</div>
        <div>{{ t("drinks") }}</div>
    </div>

    <div class="stat">
        <div>{{ t("last_7_days") }}</div>
        <div class="stat-zahl">{{ stats.tage7 }}</div>
        <div>{{ t("drinks") }}</div>
    </div>

    <div class="stat">
        <div>{{ t("last_30_days") }}</div>
        <div class="stat-zahl">{{ stats.tage30 }}</div>
        <div>{{ t("drinks") }}</div>
    </div>

    <div class="stat">
        <div>{{ t("last_3_months") }}</div>
        <div class="stat-zahl">{{ stats.monate3 }}</div>
        <div>{{ t("drinks") }}</div>
    </div>

    <div class="stat">
        <div>{{ t("last_year") }}</div>
        <div class="stat-zahl">{{ stats.jahr }}</div>
        <div>{{ t("drinks") }}</div>
    </div>

    <div class="stat">
        <div>{{ t("total") }}</div>
        <div class="stat-zahl">{{ stats.gesamt }}</div>
        <div>{{ t("drinks") }}</div>
    </div>

</div>


<div class="card">

    <h2>{{ t("consumption_by_period") }}</h2>

    <div style="margin-bottom: 20px;">

        <a
            class="button filter {% if zeitraum == '7' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=7"
        >{{ t("last_7_days") }}</a>

        <a
            class="button filter {% if zeitraum == '30' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=30"
        >{{ t("last_30_days") }}</a>

        <a
            class="button filter {% if zeitraum == '3m' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=3m"
        >{{ t("last_3_months") }}</a>

        <a
            class="button filter {% if zeitraum == '6m' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=6m"
        >{{ t("last_6_months") }}</a>

        <a
            class="button filter {% if zeitraum == '1j' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=1j"
        >{{ t("last_year") }}</a>

        <a
            class="button filter {% if zeitraum == 'alle' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=alle"
        >{{ t("total") }}</a>

    </div>

    <table>

        <tr>
            <th>{{ t("rank") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("consumption") }}</th>
        </tr>

        {% for p in ranking %}

        <tr>

            <td>
                {{ loop.index }}
            </td>

            <td>
                {% set logo = brand_logo(p.marke) %}
                <span style="display:inline-flex;width:70px;height:28px;align-items:center;justify-content:center;vertical-align:middle;margin-right:8px;">
                    {% if logo %}
                        <img src="{{ logo }}" alt="" style="max-height:28px;max-width:70px;object-fit:contain;" onerror="this.style.display='none'">
                    {% endif %}
                </span>
                <a href="/produkt/{{ p.produkt_id }}">
                    {% if p.marke %}{{ p.marke }} · {% endif %}{{ p.name }}{% if p.verpackungsinfo %} · {{ p.verpackungsinfo }}{% endif %}
                </a>
            </td>

            <td class="bestand">
                {{ p.verbrauch }}
            </td>

        </tr>

        {% else %}

        <tr>
            <td colspan="4">
                {{ t("no_consumption_period") }}
            </td>
        </tr>

        {% endfor %}

    </table>

</div>


<div class="card">

    <h2>{{ t("consumption_by_day") }}</h2>

    <table>

        <tr>
            <th>{{ t("date") }}</th>
            <th>{{ t("removed_drinks") }}</th>
        </tr>

        {% for t in tage %}

        <tr>
            <td>{{ t.datum }}</td>
            <td class="bestand">{{ t.verbrauch }}</td>
        </tr>

        {% else %}

        <tr>
            <td colspan="2">
                {{ t("no_consumption") }}
            </td>
        </tr>

        {% endfor %}

    </table>

</div>

</body>
</html>
"""







@app.route("/api/status")
def api_status():
    return {
        "name": "Smart Drink Fridge",
        "version": CURRENT_VERSION,
        "status": "ok",
    }


@app.route("/api/products")
def api_products():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            id,
            name,
            marke,
            verpackungsinfo
        FROM produkte
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    return {
        "products": [
            {
                "id": row["id"],
                "name": row["name"],
                "brand": row["marke"],
                "packaging": row["verpackungsinfo"],
            }
            for row in rows
        ]
    }


@app.route("/api/stock")
def api_stock():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            id,
            bestand
        FROM produkte
        ORDER BY id
        """
    ).fetchall()

    conn.close()

    return {
        "stock": [
            {
                "product_id": row["id"],
                "stock": row["bestand"],
            }
            for row in rows
        ]
    }




@app.route("/statistik")
def statistik():

    zeitraum = request.args.get(
        "zeitraum",
        "30"
    )

    conn = get_db()

    def gesamt_verbrauch(modifier=None, heute=False):

        if heute:

            row = conn.execute(
                """
                SELECT COALESCE(
                    -SUM(menge),
                    0
                ) AS anzahl
                FROM buchungen
                WHERE menge < 0
                  AND storniert = 0
                  AND quelle != 'storno'
                  AND date(zeitpunkt) = date(
                      'now',
                      'localtime'
                  )
                """
            ).fetchone()

        elif modifier:

            row = conn.execute(
                """
                SELECT COALESCE(
                    -SUM(menge),
                    0
                ) AS anzahl
                FROM buchungen
                WHERE menge < 0
                  AND storniert = 0
                  AND quelle != 'storno'
                  AND zeitpunkt >= datetime(
                      'now',
                      'localtime',
                      ?
                  )
                """,
                (modifier,)
            ).fetchone()

        else:

            row = conn.execute(
                """
                SELECT COALESCE(
                    -SUM(menge),
                    0
                ) AS anzahl
                FROM buchungen
                WHERE menge < 0
                  AND storniert = 0
                  AND quelle != 'storno'
                """
            ).fetchone()

        return row["anzahl"]


    stats = {
        "heute": gesamt_verbrauch(
            heute=True
        ),
        "tage7": gesamt_verbrauch(
            "-7 days"
        ),
        "tage30": gesamt_verbrauch(
            "-30 days"
        ),
        "monate3": gesamt_verbrauch(
            "-3 months"
        ),
        "jahr": gesamt_verbrauch(
            "-1 year"
        ),
        "gesamt": gesamt_verbrauch()
    }


    modifier = {
        "7": "-7 days",
        "30": "-30 days",
        "3m": "-3 months",
        "6m": "-6 months",
        "1j": "-1 year"
    }.get(zeitraum)


    if zeitraum == "alle":

        ranking = conn.execute(
            """
            SELECT
                p.id AS produkt_id,
                p.name AS name,
                p.marke AS marke,
                p.verpackungsinfo AS verpackungsinfo,
                -SUM(b.menge) AS verbrauch
            FROM buchungen b
            JOIN produkt_barcodes pb
              ON pb.ean = b.ean
            JOIN produkte p
              ON p.id = pb.produkt_id
            WHERE b.menge < 0
              AND b.storniert = 0
              AND b.quelle != 'storno'
            GROUP BY
                p.id,
                p.name,
                p.marke,
                p.verpackungsinfo
            ORDER BY
                verbrauch DESC,
                p.name
            """
        ).fetchall()


        tage = conn.execute(
            """
            SELECT
                date(zeitpunkt) AS datum,
                -SUM(menge) AS verbrauch
            FROM buchungen
            WHERE menge < 0
              AND storniert = 0
              AND quelle != 'storno'
            GROUP BY date(zeitpunkt)
            ORDER BY datum DESC
            LIMIT 365
            """
        ).fetchall()


    else:

        if modifier is None:
            zeitraum = "30"
            modifier = "-30 days"


        ranking = conn.execute(
            """
            SELECT
                p.id AS produkt_id,
                p.name AS name,
                p.marke AS marke,
                p.verpackungsinfo AS verpackungsinfo,
                -SUM(b.menge) AS verbrauch
            FROM buchungen b
            JOIN produkt_barcodes pb
              ON pb.ean = b.ean
            JOIN produkte p
              ON p.id = pb.produkt_id
            WHERE b.menge < 0
              AND b.storniert = 0
              AND b.quelle != 'storno'
              AND b.zeitpunkt >= datetime(
                  'now',
                  'localtime',
                  ?
              )
            GROUP BY
                p.id,
                p.name,
                p.marke,
                p.verpackungsinfo
            ORDER BY
                verbrauch DESC,
                p.name
            """,
            (modifier,)
        ).fetchall()


        tage = conn.execute(
            """
            SELECT
                date(zeitpunkt) AS datum,
                -SUM(menge) AS verbrauch
            FROM buchungen
            WHERE menge < 0
              AND storniert = 0
              AND quelle != 'storno'
              AND zeitpunkt >= datetime(
                  'now',
                  'localtime',
                  ?
              )
            GROUP BY date(zeitpunkt)
            ORDER BY datum DESC
            """,
            (modifier,)
        ).fetchall()


    conn.close()


    return render_page(
        STATISTIK_HTML,
        stats=stats,
        ranking=ranking,
        tage=tage,
        zeitraum=zeitraum
    )


@app.route("/produkt/<int:produkt_id>")
def produkt_detail(produkt_id):
    zeitraum = request.args.get("zeitraum", "30")

    conn = get_db()

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE id = ?
        """,
        (produkt_id,)
    ).fetchone()

    if produkt is None:
        conn.close()
        return "Produkt nicht gefunden", 404

    barcodes = conn.execute(
        """
        SELECT
            ean,
            produkt_id,
            menge,
            aktion
        FROM produkt_barcodes
        WHERE produkt_id = ?
        ORDER BY ean
        """,
        (produkt_id,)
    ).fetchall()

    alle_produkte = conn.execute(
        """
        SELECT
            id,
            name,
            marke
        FROM produkte
        ORDER BY
            marke,
            name
        """
    ).fetchall()

    # Alle Buchungen dieses Produkts werden über die
    # zugeordneten Barcodes zusammengeführt.
    #
    # Zusätzlich wird über den {{ t('product_name') }}n gesucht,
    # damit ältere Buchungen aus der Zeit vor der
    # produkt_id-Migration weiterhin sichtbar bleiben.
    basis_where = """
        (
            ean IN (
                SELECT ean
                FROM produkt_barcodes
                WHERE produkt_id = ?
            )
            OR produkt = ?
        )
    """

    def verbrauch_produkt(modifier=None):
        params = [
            produkt_id,
            produkt["name"]
        ]

        zeit_filter = ""

        if modifier:
            zeit_filter = """
                AND zeitpunkt >= datetime(
                    'now',
                    'localtime',
                    ?
                )
            """
            params.append(modifier)

        row = conn.execute(
            f"""
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN menge < 0
                        THEN ABS(menge)
                        ELSE 0
                    END
                ),
                0
            ) AS verbrauch
            FROM buchungen
            WHERE {basis_where}
              AND storniert = 0
              {zeit_filter}
            """,
            params
        ).fetchone()

        return row["verbrauch"]

    stats = {
        "tage7": verbrauch_produkt("-7 days"),
        "tage30": verbrauch_produkt("-30 days"),
        "monate3": verbrauch_produkt("-3 months"),
        "gesamt": verbrauch_produkt()
    }

    modifier = {
        "7": "-7 days",
        "30": "-30 days",
        "3m": "-3 months",
        "6m": "-6 months",
        "1j": "-1 year"
    }.get(zeitraum)

    params = [
        produkt_id,
        produkt["name"]
    ]

    zeit_filter = ""

    if zeitraum == "alle":
        pass

    elif modifier:
        zeit_filter = """
            AND zeitpunkt >= datetime(
                'now',
                'localtime',
                ?
            )
        """
        params.append(modifier)

    else:
        zeitraum = "30"
        zeit_filter = """
            AND zeitpunkt >= datetime(
                'now',
                'localtime',
                '-30 days'
            )
        """

    buchungen = conn.execute(
        f"""
        SELECT *
        FROM buchungen
        WHERE {basis_where}
          {zeit_filter}
        ORDER BY id DESC
        """,
        params
    ).fetchall()

    conn.close()

    return render_page(
        DETAIL_HTML,
        produkt=produkt,
        barcodes=barcodes,
        alle_produkte=alle_produkte,
        buchungen=buchungen,
        stats=stats,
        zeitraum=zeitraum
    )


@app.route("/barcode")
def barcode_seite():
    conn = get_db()

    produkte = conn.execute(
        """
        SELECT *
        FROM produkte
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    return render_page(
        BARCODE_HTML,
        produkte=produkte
    )


@app.route("/barcode/speichern", methods=["POST"])
def barcode_speichern():

    ean = request.form.get("ean", "").strip()
    modus = request.form.get("modus", "neu")
    aktion = request.form.get("aktion", "entnehmen")

    try:
        menge = int(
            request.form.get("menge", "1")
        )
    except ValueError:
        menge = 1

    if not ean or menge < 1:
        return "Ungültiger Barcode oder Menge.", 400

    if aktion not in (
        "entnehmen",
        "einlagern"
    ):
        return "Ungültige Barcode-Aktion.", 400

    conn = get_db()

    vorhanden = conn.execute(
        """
        SELECT ean
        FROM produkt_barcodes
        WHERE ean = ?
        """,
        (ean,)
    ).fetchone()

    if vorhanden:
        conn.close()
        return (
            "Dieser Barcode ist bereits einem Produkt zugeordnet.",
            400
        )

    if modus == "neu":

        name = request.form.get(
            "name",
            ""
        ).strip()

        marke = request.form.get(
            "marke",
            ""
        ).strip()

        verpackungsinfo = request.form.get(
            "verpackungsinfo",
            ""
        ).strip()

        try:
            bestand = int(
                request.form.get(
                    "bestand",
                    "0"
                )
            )
        except ValueError:
            bestand = 0

        try:
            mindestbestand = int(
                request.form.get(
                    "mindestbestand",
                    "0"
                )
            )
        except ValueError:
            mindestbestand = 0

        try:
            sollbestand = int(
                request.form.get(
                    "sollbestand",
                    "0"
                )
            )
        except ValueError:
            sollbestand = 0

        if not name:
            conn.close()
            return "{{ t('product_name') }} fehlt.", 400

        bestand = max(0, bestand)
        mindestbestand = max(0, mindestbestand)
        sollbestand = max(0, sollbestand)

        if sollbestand < mindestbestand:
            sollbestand = mindestbestand

        cursor = conn.execute(
            """
            INSERT INTO produkte (
                name,
                marke,
                verpackungsinfo,
                bestand,
                mindestbestand,
                sollbestand
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                marke,
                verpackungsinfo,
                bestand,
                mindestbestand,
                sollbestand
            )
        )

        produkt_id = cursor.lastrowid

        if bestand > 0:
            zeitpunkt = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            conn.execute(
                """
                INSERT INTO buchungen (
                    ean,
                    produkt,
                    aktion,
                    zeitpunkt,
                    menge,
                    bestand_vorher,
                    bestand_nachher,
                    quelle
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ean,
                    name,
                    "Anfangsbestand",
                    zeitpunkt,
                    bestand,
                    0,
                    bestand,
                    "web"
                )
            )

    elif modus == "bestehend":

        try:
            produkt_id = int(
                request.form.get(
                    "produkt_id",
                    "0"
                )
            )
        except ValueError:
            conn.close()
            return "Ungültige Produkt-ID.", 400

        produkt = conn.execute(
            """
            SELECT *
            FROM produkte
            WHERE id = ?
            """,
            (produkt_id,)
        ).fetchone()

        if produkt is None:
            conn.close()
            return "Produkt nicht gefunden.", 404

    else:
        conn.close()
        return "Ungültiger Modus.", 400

    conn.execute(
        """
        INSERT INTO produkt_barcodes (
            ean,
            produkt_id,
            menge,
            aktion
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            ean,
            produkt_id,
            menge,
            aktion
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        f"/produkt/{produkt_id}"
    )




@app.route(
    "/produkt/<int:quell_id>/zusammenfuehren",
    methods=["POST"]
)
def produkt_zusammenfuehren(quell_id):

    try:
        ziel_id = int(
            request.form.get("ziel_id", "0")
        )
    except ValueError:
        return "Ungültige Ziel-ID.", 400

    if quell_id == ziel_id:
        return "Produkt kann nicht mit sich selbst zusammengeführt werden.", 400

    conn = get_db()

    quelle = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE id = ?
        """,
        (quell_id,)
    ).fetchone()

    ziel = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE id = ?
        """,
        (ziel_id,)
    ).fetchone()

    if quelle is None or ziel is None:
        conn.close()
        return "Produkt nicht gefunden.", 404

    # Barcodes des Quellprodukts ermitteln
    quell_barcodes = conn.execute(
        """
        SELECT ean
        FROM produkt_barcodes
        WHERE produkt_id = ?
        """,
        (quell_id,)
    ).fetchall()

    # Bestände addieren
    neuer_bestand = (
        ziel["bestand"]
        + quelle["bestand"]
    )

    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE id = ?
        """,
        (
            neuer_bestand,
            ziel_id
        )
    )

    # Alle Barcodes zum Zielprodukt verschieben
    conn.execute(
        """
        UPDATE produkt_barcodes
        SET produkt_id = ?
        WHERE produkt_id = ?
        """,
        (
            ziel_id,
            quell_id
        )
    )

    # Historische Buchungen der verschobenen Barcodes
    # auf den Namen des Zielprodukts vereinheitlichen
    for barcode in quell_barcodes:
        conn.execute(
            """
            UPDATE buchungen
            SET produkt = ?
            WHERE ean = ?
            """,
            (
                ziel["name"],
                barcode["ean"]
            )
        )

    # Quellprodukt löschen
    conn.execute(
        """
        DELETE FROM produkte
        WHERE id = ?
        """,
        (quell_id,)
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        f"/produkt/{ziel_id}"
    )


@app.route("/barcode/<ean>/bearbeiten", methods=["POST"])
def barcode_bearbeiten(ean):

    try:
        menge = int(
            request.form.get("menge", "1")
        )
    except ValueError:
        menge = 1

    aktion = request.form.get(
        "aktion",
        "entnehmen"
    )

    try:
        neue_produkt_id = int(
            request.form.get(
                "produkt_id",
                "0"
            )
        )
    except ValueError:
        return "Ungültige Produkt-ID.", 400

    if menge < 1:
        return "Ungültige Menge.", 400

    if aktion not in (
        "entnehmen",
        "einlagern"
    ):
        return "Ungültige Aktion.", 400

    conn = get_db()

    barcode = conn.execute(
        """
        SELECT produkt_id
        FROM produkt_barcodes
        WHERE ean = ?
        """,
        (ean,)
    ).fetchone()

    if barcode is None:
        conn.close()
        return "Barcode nicht gefunden.", 404

    produkt_id = barcode["produkt_id"]

    zielprodukt = conn.execute(
        """
        SELECT id
        FROM produkte
        WHERE id = ?
        """,
        (neue_produkt_id,)
    ).fetchone()

    if zielprodukt is None:
        conn.close()
        return "Zielprodukt nicht gefunden.", 404

    conn.execute(
        """
        UPDATE produkt_barcodes
        SET
            produkt_id = ?,
            menge = ?,
            aktion = ?
        WHERE ean = ?
        """,
        (
            neue_produkt_id,
            menge,
            aktion,
            ean
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        f"/produkt/{neue_produkt_id}"
    )


@app.route("/api/produkt-suche/<ean>")
def produkt_suche(ean):
    ean = ean.strip()

    if not ean.isdigit():
        return {
            "gefunden": False,
            "fehler": "Ungültige EAN"
        }, 400

    url = (
        "https://world.openfoodfacts.org"
        f"/api/v2/product/{ean}.json"
    )

    headers = {
        "User-Agent":
            "SmartDrinkFridge/1.1 "
            "(https://github.com/DerRobin99/smart-drink-fridge)"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=8
        )
        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError):
        return {
            "gefunden": False,
            "fehler": "Produktdatenbank nicht erreichbar"
        }, 502

    if data.get("status") != 1:
        return {
            "gefunden": False
        }

    product = data.get("product", {})

    name = (
        product.get("product_name_de")
        or product.get("product_name")
        or ""
    )

    marke = product.get("brands", "")
    menge = product.get("quantity", "")

    return {
        "gefunden": True,
        "ean": ean,
        "name": name,
        "marke": marke,
        "menge": menge
    }


@app.route("/produkt", methods=["POST"])
def produkt():
    ean = request.form["ean"].strip()
    name = request.form["name"].strip()
    bestand = int(request.form["bestand"])

    conn = get_db()

    vorhanden = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE ean = ?
        """,
        (ean,)
    ).fetchone()

    if vorhanden is None:
        conn.execute(
            """
            INSERT INTO produkte
            (ean, name, bestand)
            VALUES (?, ?, ?)
            """,
            (ean, name, bestand)
        )

        if bestand != 0:
            zeitpunkt = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            conn.execute(
                """
                INSERT INTO buchungen (
                    ean,
                    produkt,
                    aktion,
                    zeitpunkt,
                    menge,
                    bestand_vorher,
                    bestand_nachher,
                    quelle
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ean,
                    name,
                    "Anfangsbestand",
                    zeitpunkt,
                    bestand,
                    0,
                    bestand,
                    "web"
                )
            )

    conn.commit()
    conn.close()

    return redirect("/")


@app.route("/produkt/<int:produkt_id>/bearbeiten", methods=["POST"])
def produkt_bearbeiten(produkt_id):

    name = request.form.get("name", "").strip()
    marke = request.form.get("marke", "").strip()
    verpackungsinfo = request.form.get(
        "verpackungsinfo",
        ""
    ).strip()

    try:
        bestand = int(
            request.form.get("bestand", "0")
        )
    except ValueError:
        bestand = 0

    try:
        mindestbestand = int(
            request.form.get("mindestbestand", "0")
        )
    except ValueError:
        mindestbestand = 0

    try:
        sollbestand = int(
            request.form.get("sollbestand", "0")
        )
    except ValueError:
        sollbestand = 0

    if not name:
        return redirect(
            f"/produkt/{produkt_id}"
        )

    bestand = max(0, bestand)
    mindestbestand = max(0, mindestbestand)
    sollbestand = max(0, sollbestand)

    if sollbestand < mindestbestand:
        sollbestand = mindestbestand

    conn = get_db()

    conn.execute(
        """
        UPDATE produkte
        SET
            name = ?,
            marke = ?,
            verpackungsinfo = ?,
            bestand = ?,
            mindestbestand = ?,
            sollbestand = ?
        WHERE id = ?
        """,
        (
            name,
            marke,
            verpackungsinfo,
            bestand,
            mindestbestand,
            sollbestand,
            produkt_id
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        f"/produkt/{produkt_id}"
    )


@app.route("/buchung/<int:buchung_id>/stornieren", methods=["POST"])
def buchung_stornieren(buchung_id):

    eingegeben = request.form.get("passwort", "")
    richtig = os.environ.get("STORNO_PASSWORT", "")

    if not richtig or eingegeben != richtig:
        return "Falsches Passwort", 403

    conn = get_db()

    buchung = conn.execute(
        """
        SELECT *
        FROM buchungen
        WHERE id = ?
        """,
        (buchung_id,)
    ).fetchone()

    if buchung is None:
        conn.close()
        return "Buchung nicht gefunden", 404

    if buchung["quelle"] != "scanner":
        conn.close()
        return (
            "Nur Scanner-Buchungen können storniert werden.",
            400
        )

    barcode = conn.execute(
        """
        SELECT
            pb.produkt_id,
            p.name,
            p.bestand
        FROM produkt_barcodes pb
        JOIN produkte p
            ON p.id = pb.produkt_id
        WHERE pb.ean = ?
        """,
        (buchung["ean"],)
    ).fetchone()

    if barcode is None:
        conn.close()
        return "Produkt zum Barcode nicht gefunden", 404

    produkt_id = barcode["produkt_id"]

    if buchung["storniert"] == 1:
        conn.close()
        return redirect(
            f"/produkt/{produkt_id}"
        )

    # Die ursprüngliche Mengenänderung exakt umkehren.
    # Beispiel:
    # -1 Entnahme  -> +1 Storno
    # +6 Einlagern -> -6 Storno
    urspruengliche_menge = (
        buchung["menge"]
        if buchung["menge"] is not None
        else -1
    )

    storno_menge = -urspruengliche_menge

    vorher = barcode["bestand"]
    nachher = vorher + storno_menge

    # Bestand darf nicht negativ werden.
    if nachher < 0:
        conn.close()
        return (
            "Storno nicht möglich: "
            "Der Bestand würde negativ werden.",
            400
        )

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Ursprüngliche Scanner-Buchung als storniert markieren
    conn.execute(
        """
        UPDATE buchungen
        SET storniert = 1
        WHERE id = ?
        """,
        (buchung_id,)
    )

    # Bestand um die Gegenbuchung korrigieren
    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE id = ?
        """,
        (
            nachher,
            produkt_id
        )
    )

    # Storno als eigene Buchung protokollieren
    conn.execute(
        """
        INSERT INTO buchungen (
            ean,
            produkt,
            aktion,
            zeitpunkt,
            menge,
            bestand_vorher,
            bestand_nachher,
            quelle,
            storniert
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            buchung["ean"],
            barcode["name"],
            "Scanner-Buchung storniert",
            zeitpunkt,
            storno_menge,
            vorher,
            nachher,
            "storno",
            0
        )
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        f"/produkt/{produkt_id}"
    )


@app.route("/bestand/<int:produkt_id>/einlagern", methods=["POST"])
def menge_einlagern(produkt_id):

    try:
        menge = int(request.form["menge"])
    except (ValueError, KeyError):
        return redirect(f"/produkt/{produkt_id}")

    if menge <= 0:
        return redirect(f"/produkt/{produkt_id}")

    conn = get_db()

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE id = ?
        """,
        (produkt_id,)
    ).fetchone()

    if produkt is None:
        conn.close()
        return redirect("/")

    barcode = conn.execute(
        """
        SELECT ean
        FROM produkt_barcodes
        WHERE produkt_id = ?
        ORDER BY ean
        LIMIT 1
        """,
        (produkt_id,)
    ).fetchone()

    buchungs_ean = (
        barcode["ean"]
        if barcode
        else f"produkt:{produkt_id}"
    )

    vorher = produkt["bestand"]
    nachher = vorher + menge

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE id = ?
        """,
        (nachher, produkt_id)
    )

    conn.execute(
        """
        INSERT INTO buchungen (
            ean,
            produkt,
            aktion,
            zeitpunkt,
            menge,
            bestand_vorher,
            bestand_nachher,
            quelle
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            buchungs_ean,
            produkt["name"],
            "Eingelagert",
            zeitpunkt,
            menge,
            vorher,
            nachher,
            "web"
        )
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        f"/produkt/{produkt_id}"
    )


@app.route("/bestand/<int:produkt_id>/<aktion>", methods=["POST"])
def bestand_aendern(produkt_id, aktion):

    conn = get_db()

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE id = ?
        """,
        (produkt_id,)
    ).fetchone()

    if produkt is None:
        conn.close()
        return redirect("/")

    barcode = conn.execute(
        """
        SELECT ean
        FROM produkt_barcodes
        WHERE produkt_id = ?
        ORDER BY ean
        LIMIT 1
        """,
        (produkt_id,)
    ).fetchone()

    buchungs_ean = (
        barcode["ean"]
        if barcode
        else f"produkt:{produkt_id}"
    )

    vorher = produkt["bestand"]

    if aktion == "plus":
        menge = 1
        nachher = vorher + 1
        beschreibung = "Eingelagert"

    elif aktion == "minus":

        if vorher <= 0:
            conn.close()
            return redirect(
                f"/produkt/{produkt_id}"
            )

        menge = -1
        nachher = vorher - 1
        beschreibung = "Manuell entnommen"

    else:
        conn.close()
        return redirect(
            f"/produkt/{produkt_id}"
        )

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE id = ?
        """,
        (nachher, produkt_id)
    )

    conn.execute(
        """
        INSERT INTO buchungen (
            ean,
            produkt,
            aktion,
            zeitpunkt,
            menge,
            bestand_vorher,
            bestand_nachher,
            quelle
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            buchungs_ean,
            produkt["name"],
            beschreibung,
            zeitpunkt,
            menge,
            vorher,
            nachher,
            "web"
        )
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        request.referrer
        or f"/produkt/{produkt_id}"
    )











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
