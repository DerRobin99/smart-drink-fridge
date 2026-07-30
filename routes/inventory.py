import os
from datetime import datetime

from flask import Blueprint, current_app, redirect, request

from utils.db import get_db
from utils.money import (
    normalize_currency,
    parse_optional_price_cents,
    weighted_average_cents,
)
from routes.home_assistant import sync_home_assistant_shopping_list_data
from translation import translate

inventory_bp = Blueprint("inventory", __name__)


def _message(key):
    return translate(key, request.cookies.get("lang", ""))


@inventory_bp.route("/bestand/<int:produkt_id>/<aktion>", methods=["POST"])
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
            quelle,
            einzelpreis_cent,
            waehrung
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            buchungs_ean,
            produkt["name"],
            beschreibung,
            zeitpunkt,
            menge,
            vorher,
            nachher,
            "web",
            produkt["preis_cent"],
            produkt["waehrung"]
        )
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        current_app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        request.referrer
        or f"/produkt/{produkt_id}"
    )


@inventory_bp.route("/bestand/<int:produkt_id>/einlagern", methods=["POST"])
def menge_einlagern(produkt_id):

    try:
        menge = int(request.form["menge"])
    except (ValueError, KeyError):
        return redirect(f"/produkt/{produkt_id}")

    if menge <= 0:
        return redirect(f"/produkt/{produkt_id}")

    try:
        eingegebener_preis = parse_optional_price_cents(
            request.form.get("preis")
        )
        eingegebene_waehrung = normalize_currency(
            request.form.get("waehrung")
        )
    except ValueError:
        return _message("error_invalid_price_or_currency"), 400

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
    preis_cent = produkt["preis_cent"]
    waehrung = produkt["waehrung"]

    if eingegebener_preis is not None:
        if vorher > 0 and eingegebene_waehrung != waehrung:
            conn.close()
            return _message("error_currency_change_with_stock"), 400

        if vorher == 0:
            waehrung = eingegebene_waehrung

        preis_cent = weighted_average_cents(
            vorher,
            produkt["preis_cent"],
            menge,
            eingegebener_preis,
        )

    zeitpunkt = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute(
        """
        UPDATE produkte
        SET
            bestand = ?,
            preis_cent = ?,
            waehrung = ?
        WHERE id = ?
        """,
        (
            nachher,
            preis_cent,
            waehrung,
            produkt_id,
        )
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
            buchungs_ean,
            produkt["name"],
            "Eingelagert",
            zeitpunkt,
            menge,
            vorher,
            nachher,
            "web",
            (
                eingegebener_preis
                if eingegebener_preis is not None
                else preis_cent
            ),
            waehrung
        )
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        current_app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        f"/produkt/{produkt_id}"
    )


@inventory_bp.route("/buchung/<int:buchung_id>/stornieren", methods=["POST"])
def buchung_stornieren(buchung_id):

    eingegeben = request.form.get("passwort", "")
    richtig = os.environ.get("STORNO_PASSWORT", "")

    if not richtig or eingegeben != richtig:
        return _message("error_wrong_password"), 403

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
        return _message("error_booking_not_found"), 404

    if buchung["quelle"] != "scanner":
        conn.close()
        return (
            _message("error_only_scanner_bookings_undo"),
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
        return _message("error_barcode_product_not_found"), 404

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
            _message("error_undo_negative_stock"),
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
            storniert,
            einzelpreis_cent,
            waehrung
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            0,
            buchung["einzelpreis_cent"],
            buchung["waehrung"]
        )
    )

    conn.commit()
    conn.close()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        current_app.logger.warning("Home-Assistant-Sync fehlgeschlagen: %s", exc)


    return redirect(
        f"/produkt/{produkt_id}"
    )
