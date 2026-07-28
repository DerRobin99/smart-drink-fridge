import requests
from flask import Blueprint, request, redirect
from datetime import datetime

from utils.db import get_db
from utils.render import DETAIL_HTML, render_page

products_bp = Blueprint("products", __name__)


@products_bp.route("/produkt", methods=["POST"])
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


@products_bp.route("/produkt/<int:produkt_id>/bearbeiten", methods=["POST"])
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


@products_bp.route("/produkt/<int:produkt_id>")
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


@products_bp.route(
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


@products_bp.route("/api/produkt-suche/<ean>")
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
