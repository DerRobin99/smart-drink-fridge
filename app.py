from pathlib import Path
import os
import requests
from flask import flash, send_from_directory, Flask, render_template_string, request, redirect, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
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


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


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


def render_page(template, **context):
    lang = get_language()

    context["lang"] = lang
    context["update_info"] = get_update_info()
    context["current_version"] = CURRENT_VERSION

    html = render_template_string(
        template,
        t=lambda key: TRANSLATIONS.get(lang, {}).get(key, key),
        **context
    )

    return html



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


HTML_START = """
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title></title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #111827;
            color: white;
            max-width: 1100px;
            margin: auto;
            padding: 20px;
        }

        h1 {
            color: #60a5fa;
        }

        a {
            color: #60a5fa;
            text-decoration: none;
        }

        a:hover {
            text-decoration: underline;
        }

        .card {
            background: #1f2937;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }

        .stat {
            background: #374151;
            padding: 15px;
            border-radius: 10px;
        }

        .stat-zahl {
            font-size: 28px;
            font-weight: bold;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #374151;
        }

        input {
            padding: 10px;
            margin: 5px;
            border-radius: 6px;
            border: none;
        }

        button, .button {
            padding: 8px 14px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            display: inline-block;
            text-decoration: none;
        }

        .plus {
            background: #22c55e;
            color: white;
        }

        .minus {
            background: #ef4444;
            color: white;
        }

        .filter {
            background: #374151;
            color: white;
            margin: 3px;
        }

        .filter-aktiv {
            background: #2563eb;
            color: white;
        }

        .bestand {
            font-size: 24px;
            font-weight: bold;
        }

        .aktionen {
            display: flex;
            gap: 8px;
        }

        .leer {
            color: #ef4444;
            font-weight: bold;
        }

        .zurueck {
            display: inline-block;
            margin-bottom: 20px;
        }
    
.success-message {
    background: #d1fae5;
    color: #065f46;
    border: 1px solid #10b981;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 15px;
}

</style>
</head>
<body>
"""


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

INDEX_HTML = HTML_START + """
<h1>🥤 {{ t("home") }}</h1>

<div style="margin-bottom: 20px;">
    <a
        class="button filter"
        href="/statistik"
    >
        📊 {{ t("statistics") }}
    </a>

    <a
        class="button filter"
        href="/barcode"
    >
        {{ t('barcode_add') }}
    </a>

    <a
        class="button filter"
        href="/einstellungen"
    >
        ⚙️ {{ t("settings") }}
    </a>
</div>

<div class="card">
    <h2>{{ t('current_stock') }}</h2>

    <table>
        <tr>
            <th>{{ t("manufacturer") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("packaging") }}</th>
            <th>{{ t("barcodes") }}</th>
            <th>{{ t("stock") }}</th>
            <th>{{ t("change") }}</th>
        </tr>

        {% for p in produkte %}
        <tr>
            <td>
                {% set logo = brand_logo(p.marke) %}
                <span style="display:inline-flex;width:70px;height:28px;align-items:center;justify-content:center;vertical-align:middle;margin-right:8px;">
                    {% if logo %}
                        <img src="{{ logo }}" alt="" style="max-height:28px;max-width:70px;object-fit:contain;" onerror="this.style.display='none'">
                    {% endif %}
                </span>
                {{ p.marke or "—" }}
            </td>

            <td>
                <a href="/produkt/{{ p.id }}">
                    {{ p.name }}
                </a>
            </td>

            <td>
                {{ p.verpackungsinfo or "—" }}
            </td>

            <td>{{ p.barcode_count }} Barcode{% if p.barcode_count != 1 %}s{% endif %}</td>

            <td class="bestand">
                {% if p.bestand == 0 %}
                    <span class="leer">{{ t("empty") }}</span>
                {% else %}
                    {{ p.bestand }}
                {% endif %}
            </td>

            <td>
                <div class="aktionen">
                    <form method="post" action="/bestand/{{ p.id }}/minus">
                        <button class="minus" type="submit">−1</button>
                    </form>

                    <form method="post" action="/bestand/{{ p.id }}/plus">
                        <button class="plus" type="submit">+1</button>
                    </form>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>

<div class="card">
    <h2>{{ t("last_bookings") }}</h2>

    <table>
        <tr>
            <th>{{ t("time") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("change") }}</th>
            <th>{{ t("stock") }}</th>
            <th>{{ t("source") }}</th>
        </tr>

        {% for b in buchungen %}
        <tr>
            <td>{{ b.zeitpunkt }}</td>

            <td>
                <a href="/produkt/{{ b.produkt_id }}">
                    {{ b.produkt }}
                </a>
            </td>

            <td>
                {% if b.menge is not none %}
                    {% if b.menge > 0 %}+{% endif %}{{ b.menge }}
                {% else %}
                    {{ b.aktion }}
                {% endif %}
            </td>

            <td>
                {% if b.bestand_nachher is not none %}
                    {{ b.bestand_nachher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>{{ b.quelle or "—" }}</td>
        </tr>
        {% endfor %}
    </table>
</div>

</body>
</html>
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


BARCODE_HTML = HTML_START + """
<a class="zurueck" href="/">{{ t('back_to_fridge') }}</a>

<h1>{{ t('barcode_add') }}</h1>

<div class="card">
    <h2>{{ t('product_lookup') }}</h2>

    <div>
        <input
            id="lookup-ean"
            placeholder="{{ t('ean_upc') }}"
            autocomplete="off"
        >

        <button
            type="button"
            onclick="lookupProduct()"
        >
            {{ t('product_lookup') }}
        </button>
    </div>

    <p id="lookup-status"></p>
</div>


<div class="card">

    <form method="post" action="/barcode/speichern">

        <input
            type="hidden"
            id="barcode-ean"
            name="ean"
            required
        >

        <h2>{{ t("product") }}</h2>

        <label>
            <input
                type="radio"
                name="modus"
                value="neu"
                checked
                onchange="updateMode()"
            >
            {{ t('new_product') }}
        </label>

        <label>
            <input
                type="radio"
                name="modus"
                value="bestehend"
                onchange="updateMode()"
            >
            {{ t('assign_existing') }}
        </label>

        <div id="new-product-fields" style="margin-top: 15px;">

            <input
                id="produkt-name"
                name="name"
                placeholder="{{ t('product_name') }}"
            >

            <input
                id="produkt-marke"
                name="marke"
                placeholder="{{ t('brand_manufacturer') }}"
            >

            <input
                id="api-menge"
                name="verpackungsinfo"
                placeholder="{{ t('packaging_info') }}"
            >

            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:14px; width:100%;">

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="bestand">
                        {{ t('current_stock') }}
                    </label>
                    <input
                        id="bestand"
                        name="bestand"
                        type="number"
                        min="0"
                        value="0"
                    >
                </div>

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="mindestbestand">
                        {{ t("minimum_stock") }}
                    </label>
                    <input
                        id="mindestbestand"
                        name="mindestbestand"
                        type="number"
                        min="0"
                        value="0"
                    >
                </div>

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="sollbestand">
                        {{ t("target_stock") }}
                    </label>
                    <input
                        id="sollbestand"
                        name="sollbestand"
                        type="number"
                        min="0"
                        value="0"
                    >
                </div>

            </div>

        </div>

        <div
            id="existing-product-fields"
            style="display: none; margin-top: 15px;"
        >

            <select
                name="produkt_id"
                style="
                    padding: 10px;
                    border-radius: 6px;
                    min-width: 280px;
                "
            >
                {% for p in produkte %}
                    <option value="{{ p.id }}">
                        {{ p.name }} ({{ p.bestand }})
                    </option>
                {% endfor %}
            </select>

        </div>

        <hr style="margin: 20px 0; border-color: #374151;">

        <h2>{{ t("barcode_action") }}</h2>

        <select
            name="aktion"
            style="
                padding: 10px;
                border-radius: 6px;
            "
        >
            <option value="entnehmen">
                {{ t("remove") }}
            </option>

            <option value="einlagern">
                {{ t("add_stock") }}
            </option>
        </select>

        <input
            name="menge"
            type="number"
            min="1"
            value="1"
            required
            placeholder="{{ t('quantity_per_scan') }}"
        >

        <button type="submit">
            {{ t("save_barcode") }}
        </button>

    </form>

</div>


<script>
function t(key) {
    const translations = {
        enter_ean: "Bitte eine EAN eingeben.",
        searching: "Produktdaten werden gesucht …",
        found: "Gefunden:",
        not_found_manual: "Produkt nicht gefunden. Bitte Daten manuell eingeben.",
        product_search_error: "Fehler bei der Produktsuche."
    };

    return translations[key] || key;
}

async function lookupProduct() {
    const eanInput = document.getElementById("lookup-ean");
    const ean = eanInput.value.trim();
    const status = document.getElementById("lookup-status");

    if (!ean) {
        status.textContent = t("enter_ean");
        return;
    }

    status.textContent = t("searching");

    try {
        const response = await fetch(
            "/api/produkt-suche/" + encodeURIComponent(ean)
        );

        const data = await response.json();

        document.getElementById("barcode-ean").value = ean;

        if (data.gefunden) {
            document.getElementById("produkt-name").value =
                data.name || "";

            document.getElementById("produkt-marke").value =
                data.marke || "";

            document.getElementById("api-menge").value =
                data.menge || "";

            status.textContent =
                t("found") + " " +
                [data.marke, data.name, data.menge]
                    .filter(Boolean)
                    .join(" – ");
        } else {
            status.textContent =
                t("not_found_manual");

            document.getElementById("produkt-name").value = "";
            document.getElementById("produkt-marke").value = "";
            document.getElementById("api-menge").value = "";
        }

    } catch (error) {
        status.textContent =
            t("product_search_error");
    }
}


function updateMode() {
    const mode = document.querySelector(
        'input[name="modus"]:checked'
    ).value;

    const newFields =
        document.getElementById("new-product-fields");

    const existingFields =
        document.getElementById("existing-product-fields");

    if (mode === "neu") {
        newFields.style.display = "block";
        existingFields.style.display = "none";
    } else {
        newFields.style.display = "none";
        existingFields.style.display = "block";
    }
}
</script>

</body>
</html>
"""


DETAIL_HTML = HTML_START + """
<a class="zurueck" href="/">{{ t('back_to_fridge') }}</a>

{% set logo = brand_logo(produkt.marke) %}
<h1>
    {% if logo %}
        <img src="{{ logo }}" alt="" style="height:48px;max-width:120px;object-fit:contain;vertical-align:middle;margin-right:10px;" onerror="this.style.display='none'">
    {% endif %}
    {% if produkt.marke %}{{ produkt.marke }} · {% endif %}{{ produkt.name }}{% if produkt.verpackungsinfo %} · {{ produkt.verpackungsinfo }}{% endif %}
</h1>

<div class="stats">

    <div class="stat">
        <div>{{ t('current_stock') }}</div>
        <div class="stat-zahl">{{ produkt.bestand }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_7_days") }}</div>
        <div class="stat-zahl">{{ stats.tage7 }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_30_days") }}</div>
        <div class="stat-zahl">{{ stats.tage30 }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_3_months") }}</div>
        <div class="stat-zahl">{{ stats.monate3 }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_total") }}</div>
        <div class="stat-zahl">{{ stats.gesamt }}</div>
    </div>

</div>

<div class="card">
    <h2>{{ t("edit_product") }}</h2>

    <form
        method="post"
        action="/produkt/{{ produkt.id }}/bearbeiten"
    >
        <div style="
            display:grid;
            grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
            gap:14px;
            width:100%;
            margin-bottom:14px;
        ">
            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('product_name') }}</span>
                <input
                    name="name"
                    value="{{ produkt.name }}"
                    required
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('brand_manufacturer') }}</span>
                <input
                    name="marke"
                    value="{{ produkt.marke }}"
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('packaging_info') }}</span>
                <input
                    name="verpackungsinfo"
                    value="{{ produkt.verpackungsinfo }}"
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('current_stock') }}</span>
                <input
                    name="bestand"
                    type="number"
                    min="0"
                    value="{{ produkt.bestand }}"
                    required
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t("minimum_stock") }}</span>
                <input
                    name="mindestbestand"
                    type="number"
                    min="0"
                    value="{{ produkt.mindestbestand or 0 }}"
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t("target_stock") }}</span>
                <input
                    name="sollbestand"
                    type="number"
                    min="0"
                    value="{{ produkt.sollbestand or 0 }}"
                >
            </label>
        </div>

        <button type="submit">
            Änderungen speichern
        </button>
    </form>
</div>


<div class="card">
    <h2>{{ t("change_stock") }}</h2>

    <div class="aktionen">

        <form
            method="post"
            action="/bestand/{{ produkt.id }}/minus"
        >
            <button class="minus" type="submit">
                −1 entnehmen
            </button>
        </form>

        <form
            method="post"
            action="/bestand/{{ produkt.id }}/plus"
        >
            <button class="plus" type="submit">
                +1 einlagern
            </button>
        </form>

    </div>

    <hr style="margin: 20px 0; border-color: #374151;">

    <h3>{{ t("store_multiple") }}</h3>

    <form
        method="post"
        action="/bestand/{{ produkt.id }}/einlagern"
    >
        <input
            type="number"
            name="menge"
            min="1"
            value="1"
            required
        >

        <button class="plus" type="submit">
            Menge einlagern
        </button>
    </form>
</div>


<div class="card">
    <h2>{{ t("merge_product") }}</h2>

    <p>
        Verschiebt alle Barcodes und den Bestand dieses Produkts
        zu einem anderen bestehenden Produkt.
    </p>

    <form
        method="post"
        action="/produkt/{{ produkt.id }}/zusammenfuehren"
    >
        <select
            name="ziel_id"
            required
        >
            {% for p in alle_produkte %}
                {% if p.id != produkt.id %}
                <option value="{{ p.id }}">
                    {% if p.marke %}
                        {{ p.marke }} –
                    {% endif %}
                    {{ p.name }}
                </option>
                {% endif %}
            {% endfor %}
        </select>

        <button
            class="minus"
            type="submit"
            onclick="return confirm('Produkte wirklich zusammenführen? Dieser Vorgang kann nicht automatisch rückgängig gemacht werden.')"
        >
            Mit ausgewähltem Produkt zusammenführen
        </button>
    </form>
</div>


<div class="card">
    <h2>{{ t("assigned_barcodes") }}</h2>

    <table>
        <tr>
            <th>{{ t("barcode") }}</th>
            <th>{{ t("assigned_product") }}</th>
            <th>{{ t("quantity") }}</th>
            <th>{{ t("action") }}</th>
            <th></th>
        </tr>

        {% for barcode in barcodes %}
        <tr>
            <td>{{ barcode.ean }}</td>

            <td>
                <select
                    form="barcode-{{ loop.index }}"
                    name="produkt_id"
                >
                    {% for p in alle_produkte %}
                    <option
                        value="{{ p.id }}"
                        {% if p.id == barcode.produkt_id %}selected{% endif %}
                    >
                        {% if p.marke %}
                            {{ p.marke }} –
                        {% endif %}
                        {{ p.name }}
                    </option>
                    {% endfor %}
                </select>
            </td>

            <td>
                <input
                    form="barcode-{{ loop.index }}"
                    name="menge"
                    type="number"
                    min="1"
                    value="{{ barcode.menge }}"
                    required
                    style="width: 80px;"
                >
            </td>

            <td>
                <select
                    form="barcode-{{ loop.index }}"
                    name="aktion"
                >
                    <option
                        value="entnehmen"
                        {% if barcode.aktion == "entnehmen" %}selected{% endif %}
                    >
                        {{ t("remove") }}
                    </option>

                    <option
                        value="einlagern"
                        {% if barcode.aktion == "einlagern" %}selected{% endif %}
                    >
                        {{ t("add_stock") }}
                    </option>
                </select>
            </td>

            <td>
                <form
                    id="barcode-{{ loop.index }}"
                    method="post"
                    action="/barcode/{{ barcode.ean }}/bearbeiten"
                >
                    <button type="submit">
                        Speichern
                    </button>
                </form>
            </td>
        </tr>
        {% else %}
        <tr>
            <td colspan="4">
                Keine Barcodes zugeordnet.
            </td>
        </tr>
        {% endfor %}

    </table>

    <div style="margin-top: 20px;">
        <a class="button filter" href="/barcode">
            + Weiteren Barcode hinzufügen
        </a>
    </div>
</div>


<div class="card">

    <h2>{{ t("booking_history") }}</h2>

    <div style="margin-bottom: 20px;">

        <a
            class="button filter {% if zeitraum == '7' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=7"
        >{{ t("last_7_days") }}</a>

        <a
            class="button filter {% if zeitraum == '30' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=30"
        >{{ t("last_30_days") }}</a>

        <a
            class="button filter {% if zeitraum == '3m' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=3m"
        >{{ t("last_3_months") }}</a>

        <a
            class="button filter {% if zeitraum == '6m' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=6m"
        >{{ t("last_6_months") }}</a>

        <a
            class="button filter {% if zeitraum == '1j' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=1j"
        >{{ t("last_year") }}</a>

        <a
            class="button filter {% if zeitraum == 'alle' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=alle"
        >
            Alles
        </a>

    </div>

    <table>
        <tr>
            <th>{{ t("time") }}</th>
            <th>{{ t("action") }}</th>
            <th>{{ t("change") }}</th>
            <th>{{ t("before") }}</th>
            <th>{{ t("after") }}</th>
            <th>{{ t("source") }}</th>
            <th>{{ t("undo") }}</th>
        </tr>

        {% for b in buchungen %}
        <tr>
            <td>{{ b.zeitpunkt }}</td>
            <td>{{ b.aktion }}</td>

            <td>
                {% if b.menge is not none %}
                    {% if b.menge > 0 %}+{% endif %}{{ b.menge }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>
                {% if b.bestand_vorher is not none %}
                    {{ b.bestand_vorher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>
                {% if b.bestand_nachher is not none %}
                    {{ b.bestand_nachher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>{{ b.quelle or "—" }}</td>

            <td>
                {% if b.quelle == "scanner" and b.storniert == 0 %}
                    <form method="post" action="/buchung/{{ b.id }}/stornieren">
                        <input
                            type="password"
                            name="passwort"
                            placeholder="Passwort"
                            required
                            style="width: 110px;"
                        >
                        <button class="minus" type="submit">
                            Stornieren
                        </button>
                    </form>

                {% elif b.storniert == 1 %}
                    STORNIERT

                {% else %}
                    —
                {% endif %}
            </td>

        </tr>

        {% else %}

        <tr>
            <td colspan="7">
                Keine Buchungen in diesem Zeitraum.
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


@app.route("/")
def index():
    conn = get_db()

    produkte = conn.execute(
        """
        SELECT
            p.*,
            COUNT(pb.ean) AS barcode_count
        FROM produkte p
        LEFT JOIN produkt_barcodes pb
            ON pb.produkt_id = p.id
        GROUP BY p.id
        ORDER BY p.name
        """
    ).fetchall()

    buchungen = conn.execute(
        """
        SELECT
            b.*,
            pb.produkt_id
        FROM buchungen b
        LEFT JOIN produkt_barcodes pb
            ON pb.ean = b.ean
        ORDER BY b.id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    backup_path = get_setting("backup_path", "/data/backups")
    backups = list_backups(backup_path)

    return render_page(

        INDEX_HTML,
        produkte=produkte,
        buchungen=buchungen
    )


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


@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    conn = get_db()

    if request.method == "POST":
        enabled = (
            "1"
            if request.form.get("ha_einkaufsliste_aktiv") == "on"
            else "0"
        )
        ha_url = request.form.get("ha_url", "").strip()
        ha_token = request.form.get("ha_token", "").strip()

        conn.execute(
            """
            INSERT INTO einstellungen (schluessel, wert)
            VALUES ('ha_einkaufsliste_aktiv', ?)
            ON CONFLICT(schluessel)
            DO UPDATE SET wert = excluded.wert
            """,
            (enabled,),
        )
        conn.execute(
            "INSERT INTO einstellungen (schluessel, wert) VALUES (\"ha_url\", ?) ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            (ha_url,),
        )

        conn.execute(
            "INSERT INTO einstellungen (schluessel, wert) VALUES (\"ha_token\", ?) ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            (ha_token,),
        )


        conn.commit()
        conn.close()

        flash("Einstellungen erfolgreich gespeichert.", "success"); return redirect("/einstellungen")

    setting = conn.execute(
        """
        SELECT wert
        FROM einstellungen
        WHERE schluessel = 'ha_einkaufsliste_aktiv'
        """
    ).fetchone()

    enabled = bool(
        setting
        and str(setting["wert"]).lower()
        in ("1", "true", "yes", "on")
    )

    ha_url_row = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel = 'ha_url'"
    ).fetchone()
    ha_url = ha_url_row["wert"] if ha_url_row else ""

    ha_token_row = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel = 'ha_token'"
    ).fetchone()
    ha_token = ha_token_row["wert"] if ha_token_row else ""

    conn.close()

    backup_path = get_setting("backup_path", "/data/backups")
    backups = list_backups(backup_path)

    return render_page(
        HTML_START + """
        <a href="/" style="display:inline-block;margin-bottom:20px;">
            {{ t('back_to_fridge') }}
        </a>

        <h1>⚙️ {{ t("settings") }}</h1>

        <div class="card">
            <h2>{{ t("home_assistant") }}</h2>

            <form method="post">
            <div style="
                margin-bottom:24px;
                padding:20px;
                border-radius:14px;
                background:rgba(255,255,255,0.035);
                border:1px solid rgba(255,255,255,0.08);
            ">
                <label for="language" style="
                    display:block;
                    margin-bottom:10px;
                    font-weight:700;
                ">
                    🌐 {{ t("language") }}
                </label>

                <select
                    id="language"
                    name="language"
                    onchange="window.location.href='/sprache/' + this.value"
                    style="
                        width:100%;
                        max-width:420px;
                        padding:12px 14px;
                        border-radius:10px;
                        font-size:16px;
                        cursor:pointer;
                    "
                >
                    
                    {% for code, display_name in available_languages %}
                    <option value="{{ code }}" {% if lang == code %}selected{% endif %}>
                        {{ display_name }}
                    </option>
                    {% endfor %}

                </select>
            </div>

                <div style="
                    display:flex;
                    justify-content:space-between;
                    align-items:center;
                    gap:20px;
                    flex-wrap:wrap;
                ">
                    <div style="flex:1;min-width:240px;">
                        <strong>
                            {{ t("shopping_sync") }}
                        </strong>

                        <div style="
                            margin-top:8px;
                            opacity:0.75;
                            line-height:1.5;
                        ">
                            {{ t("shopping_sync_desc") }}
                        </div>
                    </div>

                    <label style="
                        display:flex;
                        align-items:center;
                        gap:10px;
                        cursor:pointer;
                    ">
                        <input
                            type="checkbox"
                            name="ha_einkaufsliste_aktiv"
                            {% if enabled %}checked{% endif %}
                            style="
                                width:22px;
                                height:22px;
                                accent-color:#4caf50;
                            "
                        >
                        <span>
                            {% if enabled %}
                                {{ t("active") }}
                            {% else %}
                                {{ t("disabled") }}
                            {% endif %}
                        </span>
                    </label>
                </div>
                <div style="margin-top:24px; display:grid; gap:16px;">
                    <div>
                        <label for="ha_url"><strong>{{ t("home_assistant_url") }}</strong></label>
                        <input
                            type="text"
                            id="ha_url"
                            name="ha_url"
                            value="{{ ha_url }}"
                            placeholder="http://homeassistant.local:8123"
                            style="width:100%; margin-top:8px;"
                        >
                    </div>

                    <div>
                        <label for="ha_token"><strong>{{ t("home_assistant_token") }}</strong></label>
                        <input
                            type="password"
                            id="ha_token"
                            name="ha_token"
                            value="{{ ha_token }}"
                            placeholder="Home-Assistant-Token"
                            style="width:100%; margin-top:8px;"
                        >
                    </div>
                </div>


                <hr style="margin:32px 0;">

                <h3>💾 {{ t("backup") }}</h3>

                <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:16px;">
                    <button
                        type="submit"
                        class="button filter"
                        formaction="/settings/backup/create"
                        formmethod="post"
                    >
                        📦 {{ t("create_backup_now") }}
                    </button>
                </div>


                {% if backups %}
                <div id="backup" style="margin-top:24px;">
                    {% with messages = get_flashed_messages(with_categories=true) %}
  {% for category, message in messages %}
    <div class="success-message">{{ message }}</div>
  {% endfor %}
{% endwith %}

<h4>{{ t("available_backups") }}</h4>

                    <table style="width:100%;margin-top:10px;">
                        <tr>
                            <th>{{ t("filename") }}</th>
                            <th>{{ t("size") }}</th>
                            <th>{{ t("created") }}</th>
                            <th>Download</th>
                        </tr>

                        {% for backup in backups %}
                        <tr>
                            <td>{{ backup.filename }}</td>
                            <td>{{ "%.1f"|format(backup.size_bytes/1024/1024) }} MB</td>
                            <td>{{ backup.created_at }}</td>
                            <td>
                                <a class="button filter" href="/settings/backup/download/{{ backup.filename }}">
                                    ⬇️ {{ t("download") }}
                                </a>
                            </td>
                            <td>
                                <button
                                    type="submit"
                                    class="button warning"
                                    formaction="/settings/backup/restore/{{ backup.filename }}"
                                    formmethod="post"
                                    onclick="return confirm('Backup wirklich wiederherstellen? Die aktuelle Datenbank wird vorher automatisch gesichert.');">
                                    ♻️ {{ t("restore") }}
                                </button>
                            </td>
                            <td>
                                <button
                                    type="submit"
                                    class="button danger"
                                    formaction="/settings/backup/delete/{{ backup.filename }}"
                                    formmethod="post"
                                    onclick="return confirm('Backup wirklich löschen?');">
                                    🗑️ {{ t("delete") }}
                                </button>
                            </td>
                        </tr>
                        {% endfor %}
                    </table>
                </div>
                {% endif %}

                {% if backups %}
                <div style="margin-top:24px;">
                    
                </div>
                {% endif %}

                <div style="
                    margin-top:24px;
                    display:flex;
                    gap:10px;
                    flex-wrap:wrap;
                ">
                    <button type="submit" class="button filter">
                        💾 {{ t("save") }}
                    </button>

                    <a class="button filter" href="/">
                        ← {{ t("back") }}
                    </a>
                </div>
            </form>
        </div>
        """,
        enabled=enabled,
        ha_url=ha_url,
        ha_token=ha_token,
        backups=backups,
        available_languages=available_languages(),
    )


def sync_home_assistant_shopping_list_data():
    """Add missing products to the Home Assistant shopping list."""
    conn = get_db()

    settings = dict(
        conn.execute(
            """
            SELECT schluessel, wert
            FROM einstellungen
            WHERE schluessel IN (
                'ha_einkaufsliste_aktiv',
                'ha_url',
                'ha_token'
            )
            """
        ).fetchall()
    )

    enabled = str(settings.get("ha_einkaufsliste_aktiv", "")).lower() \
        in ("1", "true", "yes", "on")
    ha_url = settings.get("ha_url", "").rstrip("/")
    ha_token = settings.get("ha_token", "")

    if not enabled:
        conn.close()
        return jsonify({"success": False, "error": "Integration deaktiviert"}), 400

    if not ha_url or not ha_token:
        conn.close()
        return jsonify({"success": False, "error": "Home Assistant nicht konfiguriert"}), 400

    products = conn.execute(
        """
        SELECT id, name, bestand, mindestbestand, sollbestand
        FROM produkte
        WHERE bestand <= mindestbestand
          AND sollbestand > bestand
        ORDER BY name COLLATE NOCASE
        """
    ).fetchall()

    tracked = {
        row["produkt_id"]: row["item_name"]
        for row in conn.execute(
            "SELECT produkt_id, item_name FROM ha_shopping_sync"
        ).fetchall()
    }

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    added = []
    removed = []
    unchanged = []

    try:
        needed_product_ids = {product["id"] for product in products}

        for produkt_id, old_item in list(tracked.items()):
            if produkt_id not in needed_product_ids:
                response = requests.post(
                    f"{ha_url}/api/services/shopping_list/remove_item",
                    headers=headers,
                    json={"name": old_item},
                    timeout=10,
                )
                response.raise_for_status()

                conn.execute(
                    "DELETE FROM ha_shopping_sync WHERE produkt_id = ?",
                    (produkt_id,),
                )
                removed.append(old_item)

        for product in products:
            quantity = product["sollbestand"] - product["bestand"]
            item_name = f"{quantity}x {product['name']}"
            old_item = tracked.get(product["id"])

            if old_item == item_name:
                unchanged.append(item_name)
                continue

            if old_item:
                response = requests.post(
                    f"{ha_url}/api/services/shopping_list/remove_item",
                    headers=headers,
                    json={"name": old_item},
                    timeout=10,
                )
                response.raise_for_status()
                removed.append(old_item)

            response = requests.post(
                f"{ha_url}/api/services/shopping_list/add_item",
                headers=headers,
                json={"name": item_name},
                timeout=10,
            )
            response.raise_for_status()

            conn.execute(
                """
                INSERT INTO ha_shopping_sync (produkt_id, item_name)
                VALUES (?, ?)
                ON CONFLICT(produkt_id)
                DO UPDATE SET item_name = excluded.item_name
                """,
                (product["id"], item_name),
            )
            added.append(item_name)

        conn.commit()

    except requests.RequestException as exc:
        conn.rollback()
        conn.close()
        return jsonify({
            "success": False,
            "error": str(exc),
            "added": added,
            "removed": removed,
            "unchanged": unchanged,
        }), 502

    conn.close()

    return jsonify({
        "success": True,
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
    })



@app.post("/api/home-assistant/shopping-list/sync")
def sync_home_assistant_shopping_list():
    return sync_home_assistant_shopping_list_data()


@app.get("/api/home-assistant/shopping-list")
def api_home_assistant_shopping_list():
    """Return products that should be added to the Home Assistant shopping list."""
    conn = get_db()

    setting = conn.execute(
        """
        SELECT wert
        FROM einstellungen
        WHERE schluessel = 'ha_einkaufsliste_aktiv'
        """
    ).fetchone()

    enabled = bool(
        setting
        and str(setting["wert"]).lower()
        in ("1", "true", "yes", "on")
    )

    items = []

    if enabled:
        products = conn.execute(
            """
            SELECT
                id,
                name,
                marke,
                bestand,
                mindestbestand,
                sollbestand
            FROM produkte
            WHERE bestand <= mindestbestand
              AND sollbestand > bestand
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()

        for product in products:
            items.append(
                {
                    "product_id": product["id"],
                    "name": product["name"],
                    "brand": product["marke"],
                    "stock": product["bestand"],
                    "minimum_stock": product["mindestbestand"],
                    "target_stock": product["sollbestand"],
                    "quantity_needed": (
                        product["sollbestand"]
                        - product["bestand"]
                    ),
                }
            )

    conn.close()

    return jsonify(
        {
            "enabled": enabled,
            "items": items,
        }
    )




@app.post("/settings/backup/create")
def backup_create():
    backup_path = get_setting("backup_path", "/data/backups")
    create_backup(
        "/data/getraenke.db",
        backup_path,
        None
    )
    flash("Backup erfolgreich erstellt.", "success"); return redirect("/einstellungen#backup")


@app.get("/settings/backup/download/<filename>")
def backup_download(filename):
    import os
    from flask import send_from_directory

    backup_path = get_setting("backup_path", "/data/backups")
    filename = os.path.basename(filename)
    file_path = os.path.join(backup_path, filename)

    if not os.path.isfile(file_path):
        flash("Backup nicht gefunden.", "error")
        return redirect("/einstellungen#backup")

    return send_from_directory(
        backup_path,
        filename,
        as_attachment=True
    )


@app.post("/settings/backup/delete/<filename>")
def backup_delete(filename):
    import os

    backup_path = get_setting("backup_path", "/data/backups")
    file = os.path.join(backup_path, filename)

    if os.path.isfile(file):
        os.remove(file)
        flash("Backup gelöscht.", "success")
    else:
        flash("Backup nicht gefunden.", "error")

    return redirect("/einstellungen#backup")


@app.post("/settings/backup/restore/<filename>")
def backup_restore(filename):
    import os
    import shutil

    backup_path = get_setting("backup_path", "/data/backups")
    backup = os.path.join(backup_path, filename)
    database = "/data/getraenke.db"

    if not os.path.isfile(backup):
        flash("Backup nicht gefunden.", "error")
        return redirect("/einstellungen#backup")

    create_backup(database, backup_path, "pre_restore")

    import sqlite3

    source = sqlite3.connect(backup)
    destination = sqlite3.connect(database)

    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()

    for suffix in ("-wal", "-shm"):
        temporary_file = database + suffix
        if os.path.exists(temporary_file):
            os.remove(temporary_file)

    flash("Backup erfolgreich wiederhergestellt.", "success")
    return redirect("/einstellungen#backup")

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
