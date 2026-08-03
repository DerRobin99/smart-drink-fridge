from flask import Blueprint, request, redirect, jsonify
from datetime import datetime

from utils.db import get_db
from utils.money import normalize_currency, parse_optional_price_cents
from utils.render import BARCODE_HTML, render_page
from translation import translate
from database import get_setting
from location_inventory import initialize_product_location

barcodes_bp = Blueprint("barcodes", __name__)


def _message(key):
    return translate(key, request.cookies.get("lang", ""))


@barcodes_bp.route("/barcode")
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

@barcodes_bp.route("/barcode/speichern", methods=["POST"])
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
        return _message("error_invalid_barcode_or_quantity"), 400

    if aktion not in (
        "entnehmen",
        "einlagern"
    ):
        return _message("error_invalid_barcode_action"), 400

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
            _message("error_barcode_already_assigned"),
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

        try:
            preis_cent = parse_optional_price_cents(
                request.form.get("preis")
            )
            waehrung = normalize_currency(
                get_setting("default_currency", "EUR"),
                "EUR",
            )
        except ValueError:
            conn.close()
            return _message("error_invalid_price_or_currency"), 400

        if not name:
            conn.close()
            return _message("error_product_name_required"), 400

        bestand = max(0, bestand)
        mindestbestand = max(0, mindestbestand)
        sollbestand = max(0, sollbestand)
        preis_cent = preis_cent or 0

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
                sollbestand,
                preis_cent,
                waehrung
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                marke,
                verpackungsinfo,
                bestand,
                mindestbestand,
                sollbestand,
                preis_cent,
                waehrung
            )
        )

        produkt_id = cursor.lastrowid
        initialize_product_location(
            conn, produkt_id, bestand, mindestbestand, sollbestand
        )

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
                    quelle,
                    einzelpreis_cent,
                    waehrung
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ean,
                    name,
                    "Anfangsbestand",
                    zeitpunkt,
                    bestand,
                    0,
                    bestand,
                    "web",
                    preis_cent,
                    waehrung
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
            return _message("error_invalid_product_id"), 400

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
            return _message("error_product_not_found"), 404

    else:
        conn.close()
        return _message("error_invalid_mode"), 400

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

@barcodes_bp.route("/barcode/<ean>/bearbeiten", methods=["POST"])
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
        return _message("error_invalid_product_id"), 400

    if menge < 1:
        return _message("error_invalid_quantity"), 400

    if aktion not in (
        "entnehmen",
        "einlagern"
    ):
        return _message("error_invalid_action"), 400

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
        return _message("error_barcode_not_found"), 404

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
        return _message("error_target_product_not_found"), 404

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
