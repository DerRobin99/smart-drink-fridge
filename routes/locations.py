import hashlib
import re
import secrets
import sqlite3

from flask import Blueprint, abort, redirect, request

from database import get_setting, set_setting
from location_inventory import recalculate_product_stock
from translation import translate
from utils.auth import admin_required, current_user
from utils.db import get_db
from utils.render import HTML_START, get_language, render_page


locations_bp = Blueprint("locations", __name__)


def _t(key):
    return translate(key, get_language())


def _data():
    conn = get_db()
    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO standort_bestaende
                (produkt_id, standort_id, bestand, mindestbestand, sollbestand)
            SELECT p.id, s.id, 0, p.mindestbestand, p.sollbestand
            FROM produkte p CROSS JOIN standorte s WHERE s.aktiv=1
        """)
    locations = conn.execute("SELECT * FROM standorte WHERE aktiv=1 ORDER BY name COLLATE NOCASE").fetchall()
    scanners = conn.execute(
        "SELECT sg.*, s.name AS location_name FROM scanner_geraete sg JOIN standorte s ON s.id=sg.standort_id ORDER BY sg.name COLLATE NOCASE"
    ).fetchall()
    products = conn.execute("SELECT id, name FROM produkte ORDER BY name COLLATE NOCASE").fetchall()
    stocks = conn.execute(
        """
        SELECT sb.*, p.name AS product_name, s.name AS location_name
        FROM standort_bestaende sb
        JOIN produkte p ON p.id=sb.produkt_id
        JOIN standorte s ON s.id=sb.standort_id
        ORDER BY p.name COLLATE NOCASE, s.name COLLATE NOCASE
        """
    ).fetchall()
    conn.close()
    return locations, scanners, products, stocks


def _render(token=None):
    locations, scanners, products, stocks = _data()
    return render_page(
        HTML_START + """
        <div class="page-hero"><div><div class="eyebrow">{{ t("locations_and_scanners") }}</div>
        <h1>{{ t("multi_fridge_management") }}</h1><p>{{ t("multi_fridge_desc") }}</p></div>
        <a class="button filter" href="/einstellungen">{{ t("back_to_settings") }}</a></div>
        {% with messages = get_flashed_messages(with_categories=true) %}{% for category,message in messages %}<div class="success-message">{{ message }}</div>{% endfor %}{% endwith %}
        {% if token %}<div class="card" style="border:2px solid #fbbf24"><h2>{{ t("scanner_token_once") }}</h2><code style="word-break:break-all;user-select:all">{{ token }}</code><p>{{ t("scanner_token_warning") }}</p></div>{% endif %}
        <div class="card"><h2>{{ t("locations") }}</h2><form method="post" action="/einstellungen/standorte/anlegen" style="display:flex;gap:10px;flex-wrap:wrap"><input name="name" required placeholder="{{ t('location_name') }}"><button class="plus">{{ t("create") }}</button></form>
        <form method="post" action="/einstellungen/standorte/config" style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px"><label>{{ t("default_location") }}<select name="default_location_id">{% for location in locations %}<option value="{{ location.id }}" {% if location.id|string == default_location %}selected{% endif %}>{{ location.name }}</option>{% endfor %}</select></label><label>{{ t("shopping_lists") }}<select name="shopping_list_scope"><option value="shared" {% if shopping_scope=='shared' %}selected{% endif %}>{{ t("shopping_list_shared") }}</option><option value="separate" {% if shopping_scope=='separate' %}selected{% endif %}>{{ t("shopping_list_separate") }}</option></select></label><button class="filter">{{ t("save") }}</button></form></div>
        <div class="card"><h2>{{ t("scanner_devices") }}</h2><form method="post" action="/einstellungen/scanner/anlegen" class="form-grid"><input name="name" required placeholder="{{ t('scanner_name') }}"><input name="scanner_id" required pattern="[A-Za-z0-9._-]+" placeholder="kitchen-1"><select name="location_id">{% for location in locations %}<option value="{{ location.id }}">{{ location.name }}</option>{% endfor %}</select><button class="plus">{{ t("create_scanner") }}</button></form>
        <table><thead><tr><th>{{ t("scanner_name") }}</th><th>ID</th><th>{{ t("location") }}</th><th>{{ t("last_contact") }}</th></tr></thead><tbody>{% for scanner in scanners %}<tr><td>{{ scanner.name }}</td><td><code>{{ scanner.scanner_id }}</code></td><td>{{ scanner.location_name }}</td><td>{{ scanner.letzter_kontakt or '—' }}</td></tr>{% endfor %}</tbody></table></div>
        <div class="card"><h2>{{ t("transfer_stock") }}</h2><form method="post" action="/einstellungen/standorte/umlagern" class="form-grid"><select name="product_id">{% for product in products %}<option value="{{ product.id }}">{{ product.name }}</option>{% endfor %}</select><select name="from_location_id">{% for location in locations %}<option value="{{ location.id }}">{{ location.name }}</option>{% endfor %}</select><select name="to_location_id">{% for location in locations %}<option value="{{ location.id }}">{{ location.name }}</option>{% endfor %}</select><input name="quantity" type="number" min="1" value="1"><button class="filter">{{ t("transfer") }}</button></form></div>
        <div class="card"><h2>{{ t("stock_by_location") }}</h2><table><thead><tr><th>{{ t("product") }}</th><th>{{ t("location") }}</th><th>{{ t("stock") }}</th><th>{{ t("minimum_stock") }}</th><th>{{ t("target_stock") }}</th><th></th></tr></thead><tbody>{% for stock in stocks %}<tr><td>{{ stock.product_name }}</td><td>{{ stock.location_name }}</td><td><input form="stock-{{ stock.produkt_id }}-{{ stock.standort_id }}" name="stock" type="number" min="0" value="{{ stock.bestand }}" style="width:90px"></td><td><input form="stock-{{ stock.produkt_id }}-{{ stock.standort_id }}" name="minimum" type="number" min="0" value="{{ stock.mindestbestand }}" style="width:90px"></td><td><input form="stock-{{ stock.produkt_id }}-{{ stock.standort_id }}" name="target" type="number" min="0" value="{{ stock.sollbestand }}" style="width:90px"></td><td><form id="stock-{{ stock.produkt_id }}-{{ stock.standort_id }}" method="post" action="/einstellungen/standorte/bestand"><input type="hidden" name="product_id" value="{{ stock.produkt_id }}"><input type="hidden" name="location_id" value="{{ stock.standort_id }}"><button class="filter">{{ t("save") }}</button></form></td></tr>{% endfor %}</tbody></table></div></body></html>
        """,
        locations=locations,
        scanners=scanners,
        products=products,
        stocks=stocks,
        token=token,
        default_location=get_setting("default_location_id", "1"),
        shopping_scope=get_setting("shopping_list_scope", "shared"),
    )


@locations_bp.get("/einstellungen/standorte")
@admin_required
def locations_page():
    return _render()


@locations_bp.post("/einstellungen/standorte/anlegen")
@admin_required
def create_location():
    name = request.form.get("name", "").strip()
    if not name:
        abort(400)
    conn = get_db()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO standorte (name) VALUES (?)", (name,))
            conn.execute(
                "INSERT INTO standort_bestaende (produkt_id, standort_id, bestand, mindestbestand, sollbestand) SELECT id, ?, 0, mindestbestand, sollbestand FROM produkte",
                (cursor.lastrowid,),
            )
    except sqlite3.IntegrityError:
        conn.rollback(); conn.close(); abort(409)
    conn.close()
    return redirect("/einstellungen/standorte")


@locations_bp.post("/einstellungen/standorte/config")
@admin_required
def location_config():
    location_id = int(request.form.get("default_location_id", "1"))
    scope = request.form.get("shopping_list_scope", "shared")
    if scope not in {"shared", "separate"}:
        abort(400)
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM standorte WHERE id=? AND aktiv=1", (location_id,)).fetchone()
    conn.close()
    if not exists:
        abort(400)
    set_setting("default_location_id", location_id)
    set_setting("shopping_list_scope", scope)
    return redirect("/einstellungen/standorte")


@locations_bp.post("/einstellungen/scanner/anlegen")
@admin_required
def create_scanner():
    name = request.form.get("name", "").strip()
    scanner_id = request.form.get("scanner_id", "").strip()
    location_id = int(request.form.get("location_id", "0"))
    if not name or not re.fullmatch(r"[A-Za-z0-9._-]{2,64}", scanner_id):
        abort(400)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO scanner_geraete (scanner_id, name, standort_id, api_token_hash) VALUES (?, ?, ?, ?)",
                (scanner_id, name, location_id, digest),
            )
    except sqlite3.IntegrityError:
        conn.rollback(); conn.close(); abort(409)
    conn.close()
    return _render(token=token)


def _ensure_stock(conn, product_id, location_id):
    conn.execute(
        "INSERT OR IGNORE INTO standort_bestaende (produkt_id, standort_id) VALUES (?, ?)",
        (product_id, location_id),
    )


@locations_bp.post("/einstellungen/standorte/bestand")
@admin_required
def update_location_stock():
    product_id = int(request.form["product_id"]); location_id = int(request.form["location_id"])
    stock = max(0, int(request.form["stock"])); minimum = max(0, int(request.form["minimum"])); target = max(0, int(request.form["target"]))
    conn = get_db()
    with conn:
        _ensure_stock(conn, product_id, location_id)
        conn.execute("UPDATE standort_bestaende SET bestand=?, mindestbestand=?, sollbestand=? WHERE produkt_id=? AND standort_id=?", (stock, minimum, target, product_id, location_id))
        recalculate_product_stock(conn, product_id)
    conn.close()
    return redirect("/einstellungen/standorte")


@locations_bp.post("/einstellungen/standorte/umlagern")
@admin_required
def transfer_stock():
    product_id = int(request.form["product_id"]); source = int(request.form["from_location_id"]); target = int(request.form["to_location_id"]); quantity = max(1, int(request.form["quantity"]))
    if source == target:
        abort(400)
    conn = get_db()
    _ensure_stock(conn, product_id, source); _ensure_stock(conn, product_id, target)
    available = conn.execute("SELECT bestand FROM standort_bestaende WHERE produkt_id=? AND standort_id=?", (product_id, source)).fetchone()[0]
    if available < quantity:
        conn.close(); abort(409)
    user = current_user()
    with conn:
        conn.execute("UPDATE standort_bestaende SET bestand=bestand-? WHERE produkt_id=? AND standort_id=?", (quantity, product_id, source))
        conn.execute("UPDATE standort_bestaende SET bestand=bestand+? WHERE produkt_id=? AND standort_id=?", (quantity, product_id, target))
        conn.execute("INSERT INTO bestands_umlagerungen (produkt_id, von_standort_id, zu_standort_id, menge, benutzer_name) VALUES (?, ?, ?, ?, ?)", (product_id, source, target, quantity, user["name"] if user else None))
        recalculate_product_stock(conn, product_id)
    conn.close()
    return redirect("/einstellungen/standorte")
