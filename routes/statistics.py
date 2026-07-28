from flask import Blueprint, request

from utils.db import get_db
from utils.render import HTML_START, render_page

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

statistics_bp = Blueprint("statistics", __name__)


@statistics_bp.route("/statistik")
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

