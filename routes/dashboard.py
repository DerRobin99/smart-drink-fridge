from flask import Blueprint

from backup import list_backups
from database import get_setting
from utils.db import get_db
from utils.render import INDEX_HTML, render_page


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
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

    buchungen = conn.execute(
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
