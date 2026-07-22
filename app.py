import os
from flask import Flask, render_template_string, request, redirect
import sqlite3
from datetime import datetime

app = Flask(__name__)
from database import DB, init_db

init_db()


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



TRANSLATIONS_EN = {
    "Getränkekühlschrank": "Smart Drink Fridge",
    "Statistiken anzeigen": "View statistics",
    "Produkt hinzufügen": "Add product",
    "Produktname": "Product name",
    "Bestand": "Stock",
    "Speichern": "Save",
    "Aktueller Bestand": "Current stock",
    "Produkt": "Product",
    "Ändern": "Change",
    "LEER": "EMPTY",
    "Letzte Buchungen": "Latest transactions",
    "Zeit": "Time",
    "Änderung": "Change",
    "Quelle": "Source",
    "Zurück zum Kühlschrank": "Back to fridge",
    "Statistiken": "Statistics",
    "Heute": "Today",
    "Letzte 7 Tage": "Last 7 days",
    "Letzte 30 Tage": "Last 30 days",
    "Letzte 3 Monate": "Last 3 months",
    "Letztes Jahr": "Last year",
    "Gesamt": "Total",
    "Getränke": "Drinks",
    "Verbrauch nach Zeitraum": "Consumption by period",
    "7 Tage": "7 days",
    "30 Tage": "30 days",
    "3 Monate": "3 months",
    "6 Monate": "6 months",
    "1 Jahr": "1 year",
    "Platz": "Rank",
    "Getränk": "Drink",
    "Verbrauch": "Consumption",
    "Noch keine Verbrauchsdaten in diesem Zeitraum.": "No consumption data for this period yet.",
    "Verbrauch nach Tagen": "Consumption by day",
    "Datum": "Date",
    "Entnommene Getränke": "Drinks taken",
    "Noch keine Verbrauchsdaten vorhanden.": "No consumption data available yet.",
    "Verbrauch 7 Tage": "Consumption 7 days",
    "Verbrauch 30 Tage": "Consumption 30 days",
    "Verbrauch 3 Monate": "Consumption 3 months",
    "Verbrauch gesamt": "Total consumption",
    "Produkt bearbeiten": "Edit product",
    "Name speichern": "Save name",
    "Produktdaten": "Product details",
    "−1 entnehmen": "−1 remove",
    "+1 einlagern": "+1 add",
    "Mehrere Flaschen einlagern": "Add multiple bottles",
    "Menge einlagern": "Add quantity",
    "Buchungshistorie": "Transaction history",
    "Alles": "All",
    "Aktion": "Action",
    "Vorher": "Before",
    "Nachher": "After",
    "Storno": "Cancel",
    "Passwort": "Password",
    "Stornieren": "Cancel transaction",
    "STORNIERT": "CANCELLED",
    "Keine Buchungen in diesem Zeitraum.": "No transactions in this period.",
    "Ausgebucht": "Removed",
    "Eingelagert": "Added",
    "Manuell entnommen": "Manually removed",
    "Anfangsbestand": "Initial stock",
    "Scanner-Buchung storniert": "Scanner transaction cancelled",
}


def get_language():
    cookie_lang = request.cookies.get("lang")

    if cookie_lang in ("de", "en"):
        return cookie_lang

    return (
        request.accept_languages.best_match(
            ["en", "de"]
        )
        or "en"
    )


def render_page(template, **context):
    lang = get_language()

    context["lang"] = lang

    html = render_template_string(
        template,
        **context
    )

    if lang == "en":
        # Längere Texte zuerst ersetzen, damit Teilstrings
        # keine späteren Übersetzungen beschädigen.
        for german, english in sorted(
            TRANSLATIONS_EN.items(),
            key=lambda item: len(item[0]),
            reverse=True
        ):
            html = html.replace(german, english)

    return html


@app.route("/sprache/<lang>")
def sprache(lang):
    if lang not in ("de", "en"):
        lang = "en"

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
    <title>Getränkekühlschrank</title>

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
    </style>
</head>
<body>

<div style="text-align: right; margin-bottom: 10px;">
    <a href="/sprache/de">DE</a>
    <span style="color: #6b7280;"> | </span>
    <a href="/sprache/en">EN</a>
</div>
"""


INDEX_HTML = HTML_START + """
<h1>🥤 Getränkekühlschrank</h1>

<div style="margin-bottom: 20px;">
    <a
        class="button filter"
        href="/statistik"
    >
        📊 Statistiken anzeigen
    </a>
</div>

<div class="card">
    <h2>Produkt hinzufügen</h2>

    <form method="post" action="/produkt">
        <input name="ean" placeholder="EAN" required>
        <input name="name" placeholder="Produktname" required>
        <input name="bestand" type="number" min="0" placeholder="Bestand" required>
        <button type="submit">Speichern</button>
    </form>
</div>

<div class="card">
    <h2>Aktueller Bestand</h2>

    <table>
        <tr>
            <th>Produkt</th>
            <th>EAN</th>
            <th>Bestand</th>
            <th>Ändern</th>
        </tr>

        {% for p in produkte %}
        <tr>
            <td>
                <a href="/produkt/{{ p.ean }}">
                    {{ p.name }}
                </a>
            </td>

            <td>{{ p.ean }}</td>

            <td class="bestand">
                {% if p.bestand == 0 %}
                    <span class="leer">LEER</span>
                {% else %}
                    {{ p.bestand }}
                {% endif %}
            </td>

            <td>
                <div class="aktionen">
                    <form method="post" action="/bestand/{{ p.ean }}/minus">
                        <button class="minus" type="submit">−1</button>
                    </form>

                    <form method="post" action="/bestand/{{ p.ean }}/plus">
                        <button class="plus" type="submit">+1</button>
                    </form>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>

<div class="card">
    <h2>Letzte Buchungen</h2>

    <table>
        <tr>
            <th>Zeit</th>
            <th>Produkt</th>
            <th>Änderung</th>
            <th>Bestand</th>
            <th>Quelle</th>
        </tr>

        {% for b in buchungen %}
        <tr>
            <td>{{ b.zeitpunkt }}</td>

            <td>
                <a href="/produkt/{{ b.ean }}">
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
<a class="zurueck" href="/">← Zurück zum Kühlschrank</a>

<h1>📊 Statistiken</h1>

<div class="stats">

    <div class="stat">
        <div>Heute</div>
        <div class="stat-zahl">{{ stats.heute }}</div>
        <div>Getränke</div>
    </div>

    <div class="stat">
        <div>Letzte 7 Tage</div>
        <div class="stat-zahl">{{ stats.tage7 }}</div>
        <div>Getränke</div>
    </div>

    <div class="stat">
        <div>Letzte 30 Tage</div>
        <div class="stat-zahl">{{ stats.tage30 }}</div>
        <div>Getränke</div>
    </div>

    <div class="stat">
        <div>Letzte 3 Monate</div>
        <div class="stat-zahl">{{ stats.monate3 }}</div>
        <div>Getränke</div>
    </div>

    <div class="stat">
        <div>Letztes Jahr</div>
        <div class="stat-zahl">{{ stats.jahr }}</div>
        <div>Getränke</div>
    </div>

    <div class="stat">
        <div>Gesamt</div>
        <div class="stat-zahl">{{ stats.gesamt }}</div>
        <div>Getränke</div>
    </div>

</div>


<div class="card">

    <h2>Verbrauch nach Zeitraum</h2>

    <div style="margin-bottom: 20px;">

        <a
            class="button filter {% if zeitraum == '7' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=7"
        >
            7 Tage
        </a>

        <a
            class="button filter {% if zeitraum == '30' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=30"
        >
            30 Tage
        </a>

        <a
            class="button filter {% if zeitraum == '3m' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=3m"
        >
            3 Monate
        </a>

        <a
            class="button filter {% if zeitraum == '6m' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=6m"
        >
            6 Monate
        </a>

        <a
            class="button filter {% if zeitraum == '1j' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=1j"
        >
            1 Jahr
        </a>

        <a
            class="button filter {% if zeitraum == 'alle' %}filter-aktiv{% endif %}"
            href="/statistik?zeitraum=alle"
        >
            Gesamt
        </a>

    </div>

    <table>

        <tr>
            <th>Platz</th>
            <th>Getränk</th>
            <th>EAN</th>
            <th>Verbrauch</th>
        </tr>

        {% for p in ranking %}

        <tr>

            <td>
                {{ loop.index }}
            </td>

            <td>
                <a href="/produkt/{{ p.ean }}">
                    {{ p.name }}
                </a>
            </td>

            <td>
                {{ p.ean }}
            </td>

            <td class="bestand">
                {{ p.verbrauch }}
            </td>

        </tr>

        {% else %}

        <tr>
            <td colspan="4">
                Noch keine Verbrauchsdaten in diesem Zeitraum.
            </td>
        </tr>

        {% endfor %}

    </table>

</div>


<div class="card">

    <h2>Verbrauch nach Tagen</h2>

    <table>

        <tr>
            <th>Datum</th>
            <th>Entnommene Getränke</th>
        </tr>

        {% for t in tage %}

        <tr>
            <td>{{ t.datum }}</td>
            <td class="bestand">{{ t.verbrauch }}</td>
        </tr>

        {% else %}

        <tr>
            <td colspan="2">
                Noch keine Verbrauchsdaten vorhanden.
            </td>
        </tr>

        {% endfor %}

    </table>

</div>

</body>
</html>
"""


DETAIL_HTML = HTML_START + """
<a class="zurueck" href="/">← Zurück zum Kühlschrank</a>

<h1>🥤 {{ produkt.name }}</h1>

<div class="stats">

    <div class="stat">
        <div>Aktueller Bestand</div>
        <div class="stat-zahl">{{ produkt.bestand }}</div>
    </div>

    <div class="stat">
        <div>Verbrauch 7 Tage</div>
        <div class="stat-zahl">{{ stats.tage7 }}</div>
    </div>

    <div class="stat">
        <div>Verbrauch 30 Tage</div>
        <div class="stat-zahl">{{ stats.tage30 }}</div>
    </div>

    <div class="stat">
        <div>Verbrauch 3 Monate</div>
        <div class="stat-zahl">{{ stats.monate3 }}</div>
    </div>

    <div class="stat">
        <div>Verbrauch gesamt</div>
        <div class="stat-zahl">{{ stats.gesamt }}</div>
    </div>

</div>

<div class="card">
    <h2>Produkt bearbeiten</h2>

    <form method="post" action="/produkt/{{ produkt.ean }}/bearbeiten">
        <input
            name="name"
            value="{{ produkt.name }}"
            placeholder="Produktname"
            required
        >
        <button type="submit">Name speichern</button>
    </form>
</div>

<div class="card">
    <h2>Produktdaten</h2>

    <p>
        <strong>EAN:</strong> {{ produkt.ean }}
    </p>

    <div class="aktionen">
        <form method="post" action="/bestand/{{ produkt.ean }}/minus">
            <button class="minus" type="submit">−1 entnehmen</button>
        </form>

        <form method="post" action="/bestand/{{ produkt.ean }}/plus">
            <button class="plus" type="submit">+1 einlagern</button>
        </form>
    </div>

    <hr style="margin: 20px 0; border-color: #374151;">

    <h3>Mehrere Flaschen einlagern</h3>

    <form method="post" action="/bestand/{{ produkt.ean }}/einlagern">
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

    <h2>Buchungshistorie</h2>

    <div style="margin-bottom: 20px;">

        <a
            class="button filter {% if zeitraum == '7' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.ean }}?zeitraum=7"
        >
            7 Tage
        </a>

        <a
            class="button filter {% if zeitraum == '30' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.ean }}?zeitraum=30"
        >
            30 Tage
        </a>

        <a
            class="button filter {% if zeitraum == '3m' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.ean }}?zeitraum=3m"
        >
            3 Monate
        </a>

        <a
            class="button filter {% if zeitraum == '6m' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.ean }}?zeitraum=6m"
        >
            6 Monate
        </a>

        <a
            class="button filter {% if zeitraum == '1j' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.ean }}?zeitraum=1j"
        >
            1 Jahr
        </a>

        <a
            class="button filter {% if zeitraum == 'alle' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.ean }}?zeitraum=alle"
        >
            Alles
        </a>

    </div>

    <table>
        <tr>
            <th>Zeit</th>
            <th>Aktion</th>
            <th>Änderung</th>
            <th>Vorher</th>
            <th>Nachher</th>
            <th>Quelle</th>
            <th>Storno</th>
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


@app.route("/")
def index():
    conn = get_db()

    produkte = conn.execute(
        """
        SELECT *
        FROM produkte
        ORDER BY name
        """
    ).fetchall()

    buchungen = conn.execute(
        """
        SELECT *
        FROM buchungen
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

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
                p.ean AS ean,
                p.name AS name,
                -SUM(b.menge) AS verbrauch
            FROM buchungen b
            JOIN produkte p
              ON p.ean = b.ean
            WHERE b.menge < 0
              AND b.storniert = 0
              AND b.quelle != 'storno'
            GROUP BY
                p.ean,
                p.name
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
                p.ean AS ean,
                p.name AS name,
                -SUM(b.menge) AS verbrauch
            FROM buchungen b
            JOIN produkte p
              ON p.ean = b.ean
            WHERE b.menge < 0
              AND b.storniert = 0
              AND b.quelle != 'storno'
              AND b.zeitpunkt >= datetime(
                  'now',
                  'localtime',
                  ?
              )
            GROUP BY
                p.ean,
                p.name
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


@app.route("/produkt/<ean>")
def produkt_detail(ean):
    zeitraum = request.args.get("zeitraum", "30")

    conn = get_db()

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE ean = ?
        """,
        (ean,)
    ).fetchone()

    if produkt is None:
        conn.close()
        return "Produkt nicht gefunden", 404

    stats = {
        "tage7": verbrauch(conn, ean, "-7 days"),
        "tage30": verbrauch(conn, ean, "-30 days"),
        "monate3": verbrauch(conn, ean, "-3 months"),
        "gesamt": verbrauch(conn, ean)
    }

    modifier = {
        "7": "-7 days",
        "30": "-30 days",
        "3m": "-3 months",
        "6m": "-6 months",
        "1j": "-1 year"
    }.get(zeitraum)

    if zeitraum == "alle":
        buchungen = conn.execute(
            """
            SELECT *
            FROM buchungen
            WHERE ean = ?
            ORDER BY id DESC
            """,
            (ean,)
        ).fetchall()

    elif modifier:
        buchungen = conn.execute(
            """
            SELECT *
            FROM buchungen
            WHERE ean = ?
              AND zeitpunkt >= datetime('now', 'localtime', ?)
            ORDER BY id DESC
            """,
            (ean, modifier)
        ).fetchall()

    else:
        zeitraum = "30"

        buchungen = conn.execute(
            """
            SELECT *
            FROM buchungen
            WHERE ean = ?
              AND zeitpunkt >= datetime(
                    'now',
                    'localtime',
                    '-30 days'
              )
            ORDER BY id DESC
            """,
            (ean,)
        ).fetchall()

    conn.close()

    return render_page(
        DETAIL_HTML,
        produkt=produkt,
        buchungen=buchungen,
        stats=stats,
        zeitraum=zeitraum
    )


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


@app.route("/produkt/<ean>/bearbeiten", methods=["POST"])
def produkt_bearbeiten(ean):
    neuer_name = request.form["name"].strip()

    if not neuer_name:
        return redirect(f"/produkt/{ean}")

    conn = get_db()

    conn.execute(
        """
        UPDATE produkte
        SET name = ?
        WHERE ean = ?
        """,
        (neuer_name, ean)
    )

    conn.commit()
    conn.close()

    return redirect(f"/produkt/{ean}")


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
        return "Nur Scanner-Buchungen können storniert werden.", 400

    if buchung["storniert"] == 1:
        conn.close()
        return redirect(f"/produkt/{buchung['ean']}")

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE ean = ?
        """,
        (buchung["ean"],)
    ).fetchone()

    if produkt is None:
        conn.close()
        return "Produkt nicht gefunden", 404

    vorher = produkt["bestand"]
    nachher = vorher + 1
    zeitpunkt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Ursprüngliche Scanner-Buchung als storniert markieren
    conn.execute(
        """
        UPDATE buchungen
        SET storniert = 1
        WHERE id = ?
        """,
        (buchung_id,)
    )

    # Bestand wieder um 1 erhöhen
    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE ean = ?
        """,
        (nachher, buchung["ean"])
    )

    # Stornierung als eigene nachvollziehbare Buchung speichern
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
            produkt["name"],
            "Scanner-Buchung storniert",
            zeitpunkt,
            1,
            vorher,
            nachher,
            "storno",
            0
        )
    )

    conn.commit()
    conn.close()

    return redirect(f"/produkt/{buchung['ean']}")


@app.route("/bestand/<ean>/einlagern", methods=["POST"])
def menge_einlagern(ean):
    try:
        menge = int(request.form["menge"])
    except (ValueError, KeyError):
        return redirect(f"/produkt/{ean}")

    if menge <= 0:
        return redirect(f"/produkt/{ean}")

    conn = get_db()

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE ean = ?
        """,
        (ean,)
    ).fetchone()

    if produkt is None:
        conn.close()
        return redirect("/")

    vorher = produkt["bestand"]
    nachher = vorher + menge

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE ean = ?
        """,
        (nachher, ean)
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

    return redirect(f"/produkt/{ean}")


@app.route("/bestand/<ean>/<aktion>", methods=["POST"])
def bestand_aendern(ean, aktion):
    conn = get_db()

    produkt = conn.execute(
        """
        SELECT *
        FROM produkte
        WHERE ean = ?
        """,
        (ean,)
    ).fetchone()

    if produkt is None:
        conn.close()
        return redirect("/")

    vorher = produkt["bestand"]

    if aktion == "plus":
        menge = 1
        nachher = vorher + 1
        beschreibung = "Eingelagert"

    elif aktion == "minus":
        if vorher <= 0:
            conn.close()
            return redirect("/")

        menge = -1
        nachher = vorher - 1
        beschreibung = "Manuell entnommen"

    else:
        conn.close()
        return redirect("/")

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute(
        """
        UPDATE produkte
        SET bestand = ?
        WHERE ean = ?
        """,
        (nachher, ean)
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

    return redirect(request.referrer or "/")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
