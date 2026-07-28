from flask import Blueprint, request, redirect, jsonify
from datetime import datetime

from utils.db import get_db
from utils.render import BARCODE_HTML, render_page

barcodes_bp = Blueprint("barcodes", __name__)

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
