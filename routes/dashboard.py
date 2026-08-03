from flask import Blueprint, redirect, request

from backup import list_backups
from database import get_setting
from utils.auth import accounts_enabled
from utils.db import get_db
from utils.render import INDEX_HTML, render_page


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
def index():
    if (
        accounts_enabled()
        and get_setting("checkout_mode_enabled", "0").lower()
        in {"1", "true", "yes", "on"}
        and request.path == "/"
    ):
        return redirect("/checkout")
    conn = get_db()

    show_empty = get_setting(
        "show_empty_products",
        "1",
    ).lower() in ("1", "true", "yes", "on")

    sql = """
        SELECT
            p.*,
            COUNT(pb.ean) AS barcode_count
        FROM produkte p
        LEFT JOIN produkt_barcodes pb
            ON pb.produkt_id = p.id
    """

    if not show_empty:
        sql += "\nWHERE p.bestand > 0"

    sql += """
        GROUP BY p.id
        ORDER BY p.name
    """

    produkte = conn.execute(sql).fetchall()

    summary_row = conn.execute(
        """
        SELECT
            COUNT(*) AS products,
            COALESCE(SUM(bestand), 0) AS units,
            COALESCE(SUM(
                CASE
                    WHEN bestand <= mindestbestand THEN 1
                    ELSE 0
                END
            ), 0) AS low_stock
        FROM produkte p
        """
    ).fetchone()

    consumed_7 = conn.execute(
        """
        SELECT COALESCE(-SUM(menge), 0) AS consumed
        FROM buchungen
        WHERE menge < 0
          AND storniert = 0
          AND quelle != 'storno'
          AND zeitpunkt >= datetime('now', 'localtime', '-7 days')
        """
    ).fetchone()["consumed"]

    summary = {
        "products": summary_row["products"],
        "units": summary_row["units"],
        "low_stock": summary_row["low_stock"],
        "consumed_7": consumed_7,
    }

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
        buchungen=buchungen,
        summary=summary,
    )
