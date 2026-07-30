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
    <h2>{{ t("financial_statistics") }}</h2>
    <p>{{ t("currencies_not_converted") }}</p>

    <table class="responsive-table">
        <tr class="table-head">
            <th>{{ t("currency") }}</th>
            <th>{{ t("inventory_value") }}</th>
            <th>{{ t("purchase_value_period") }}</th>
            <th>{{ t("consumption_value_period") }}</th>
        </tr>
        {% for money in money_totals %}
        <tr>
            <td class="mobile-primary" data-label="{{ t('currency') }}">{{ money.waehrung }}</td>
            <td data-label="{{ t('inventory_value') }}">{{ format_money(money.lagerwert_cent, money.waehrung) }}</td>
            <td data-label="{{ t('purchase_value_period') }}">{{ format_money(money.einkauf_cent, money.waehrung) }}</td>
            <td data-label="{{ t('consumption_value_period') }}">{{ format_money(money.verbrauch_cent, money.waehrung) }}</td>
        </tr>
        {% else %}
        <tr>
            <td class="mobile-primary" colspan="4">{{ t("no_price_data") }}</td>
        </tr>
        {% endfor %}
    </table>
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

    <table class="responsive-table">

        <tr class="table-head">
            <th>{{ t("rank") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("consumption") }}</th>
            <th>{{ t("consumption_value") }}</th>
        </tr>

        {% for p in ranking %}

        <tr>

            <td data-label="{{ t('rank') }}">
                {{ loop.index }}
            </td>

            <td class="mobile-primary" data-label="{{ t('product') }}">
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

            <td class="bestand" data-label="{{ t('consumption') }}">
                {{ p.verbrauch }}
            </td>
            <td data-label="{{ t('consumption_value') }}">
                {{ format_money(p.kosten_cent, p.waehrung) }}
            </td>

        </tr>

        {% else %}

        <tr>
            <td class="mobile-primary" colspan="4">
                {{ t("no_consumption_period") }}
            </td>
        </tr>

        {% endfor %}

    </table>

</div>


<div class="card">

    <h2>{{ t("consumption_by_day") }}</h2>

    <table class="responsive-table">

        <tr class="table-head">
            <th>{{ t("date") }}</th>
            <th>{{ t("removed_drinks") }}</th>
            <th>{{ t("consumption_value") }}</th>
        </tr>

        {% for day in tage %}

        <tr>
            <td class="mobile-primary" data-label="{{ t('date') }}">{{ day.datum }}</td>
            <td class="bestand" data-label="{{ t('removed_drinks') }}">{{ day.verbrauch }}</td>
            <td data-label="{{ t('consumption_value') }}">{{ format_money(day.kosten_cent, day.waehrung) }}</td>
        </tr>

        {% else %}

        <tr>
            <td class="mobile-primary" colspan="3">
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

    if zeitraum != "alle" and modifier is None:
        zeitraum = "30"
        modifier = "-30 days"

    period_clause = ""
    period_params = ()

    if zeitraum != "alle":
        period_clause = """
          AND zeitpunkt >= datetime(
              'now',
              'localtime',
              ?
          )
        """
        period_params = (modifier,)

    money_rows = {}

    def add_money_rows(rows, field):
        for row in rows:
            currency = row["waehrung"] or "EUR"
            money_rows.setdefault(
                currency,
                {
                    "waehrung": currency,
                    "lagerwert_cent": 0,
                    "einkauf_cent": 0,
                    "verbrauch_cent": 0,
                },
            )[field] = row["betrag_cent"] or 0

    add_money_rows(
        conn.execute(
            """
            SELECT
                waehrung,
                SUM(bestand * preis_cent) AS betrag_cent
            FROM produkte
            WHERE bestand > 0
              AND preis_cent > 0
            GROUP BY waehrung
            """
        ).fetchall(),
        "lagerwert_cent",
    )

    add_money_rows(
        conn.execute(
            f"""
            SELECT
                COALESCE(waehrung, 'EUR') AS waehrung,
                SUM(menge * COALESCE(einzelpreis_cent, 0)) AS betrag_cent
            FROM buchungen
            WHERE menge > 0
              AND storniert = 0
              AND quelle != 'storno'
              {period_clause}
            GROUP BY COALESCE(waehrung, 'EUR')
            """,
            period_params,
        ).fetchall(),
        "einkauf_cent",
    )

    add_money_rows(
        conn.execute(
            f"""
            SELECT
                COALESCE(waehrung, 'EUR') AS waehrung,
                SUM(-menge * COALESCE(einzelpreis_cent, 0)) AS betrag_cent
            FROM buchungen
            WHERE menge < 0
              AND storniert = 0
              AND quelle != 'storno'
              {period_clause}
            GROUP BY COALESCE(waehrung, 'EUR')
            """,
            period_params,
        ).fetchall(),
        "verbrauch_cent",
    )

    money_totals = [
        money_rows[currency]
        for currency in sorted(money_rows)
        if any(
            money_rows[currency][field]
            for field in (
                "lagerwert_cent",
                "einkauf_cent",
                "verbrauch_cent",
            )
        )
    ]

    if zeitraum == "alle":

        ranking = conn.execute(
            """
            SELECT
                p.id AS produkt_id,
                p.name AS name,
                p.marke AS marke,
                p.verpackungsinfo AS verpackungsinfo,
                -SUM(b.menge) AS verbrauch,
                SUM(
                    -b.menge * COALESCE(b.einzelpreis_cent, 0)
                ) AS kosten_cent,
                COALESCE(b.waehrung, 'EUR') AS waehrung
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
                p.verpackungsinfo,
                COALESCE(b.waehrung, 'EUR')
            ORDER BY
                verbrauch DESC,
                p.name
            """
        ).fetchall()


        tage = conn.execute(
            """
            SELECT
                date(zeitpunkt) AS datum,
                -SUM(menge) AS verbrauch,
                SUM(
                    -menge * COALESCE(einzelpreis_cent, 0)
                ) AS kosten_cent,
                COALESCE(waehrung, 'EUR') AS waehrung
            FROM buchungen
            WHERE menge < 0
              AND storniert = 0
              AND quelle != 'storno'
            GROUP BY
                date(zeitpunkt),
                COALESCE(waehrung, 'EUR')
            ORDER BY datum DESC
            LIMIT 365
            """
        ).fetchall()


    else:

        ranking = conn.execute(
            """
            SELECT
                p.id AS produkt_id,
                p.name AS name,
                p.marke AS marke,
                p.verpackungsinfo AS verpackungsinfo,
                -SUM(b.menge) AS verbrauch,
                SUM(
                    -b.menge * COALESCE(b.einzelpreis_cent, 0)
                ) AS kosten_cent,
                COALESCE(b.waehrung, 'EUR') AS waehrung
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
                p.verpackungsinfo,
                COALESCE(b.waehrung, 'EUR')
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
                -SUM(menge) AS verbrauch,
                SUM(
                    -menge * COALESCE(einzelpreis_cent, 0)
                ) AS kosten_cent,
                COALESCE(waehrung, 'EUR') AS waehrung
            FROM buchungen
            WHERE menge < 0
              AND storniert = 0
              AND quelle != 'storno'
              AND zeitpunkt >= datetime(
                  'now',
                  'localtime',
                  ?
              )
            GROUP BY
                date(zeitpunkt),
                COALESCE(waehrung, 'EUR')
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
        money_totals=money_totals,
        zeitraum=zeitraum
    )
