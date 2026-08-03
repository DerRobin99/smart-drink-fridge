from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, request

from database import get_setting
from routes.home_assistant import sync_home_assistant_shopping_list_data
from translation import translate
from utils.auth import accounts_enabled, booking_user, clear_scanner_user, current_user
from utils.db import get_db
from utils.render import HTML_START, get_language, render_page


checkout_bp = Blueprint("checkout", __name__)


def checkout_enabled():
    return accounts_enabled() and get_setting(
        "checkout_mode_enabled", "0"
    ).lower() in {"1", "true", "yes", "on"}


def _t(key):
    return translate(key, get_language())


@checkout_bp.get("/checkout")
def checkout():
    if not checkout_enabled():
        return redirect("/")
    if current_user() is None:
        return redirect("/anmelden?next=/checkout")

    conn = get_db()
    products = conn.execute(
        """
        SELECT p.*, COUNT(pb.ean) AS barcode_count
        FROM produkte p
        LEFT JOIN produkt_barcodes pb ON pb.produkt_id = p.id
        WHERE p.bestand > 0
        GROUP BY p.id
        ORDER BY p.name COLLATE NOCASE
        """
    ).fetchall()
    conn.close()

    return render_page(
        HTML_START + """
        <div class="page-hero">
            <div>
                <div class="eyebrow">{{ t("checkout") }}</div>
                <h1>🥤 {{ t("choose_your_drink") }}</h1>
                <p>{{ t("checkout_description") }}</p>
            </div>
            <a class="button filter" href="/dashboard">{{ t("open_dashboard") }}</a>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}
                <div class="success-message">{{ message }}</div>
            {% endfor %}
        {% endwith %}

        <div class="checkout-grid">
        {% for product in products %}
            {% set logo = brand_logo(product.marke) %}
            <article class="checkout-card">
                <div class="checkout-image">
                    {% if logo %}
                    <img src="{{ logo }}" alt="" loading="lazy"
                         onerror="this.replaceWith(document.createTextNode('{{ product.name[:1]|upper }}'))">
                    {% else %}{{ product.name[:1]|upper }}{% endif %}
                </div>
                <div class="checkout-name">{{ product.name }}</div>
                <div class="product-meta">{{ product.marke or t("without_brand") }}</div>
                <div class="stock-pill {% if product.bestand <= product.mindestbestand %}low{% endif %}">
                    {{ product.bestand }} {{ t("in_stock") }}
                </div>
                <form method="post" action="/checkout/remove" class="checkout-form">
                    <input type="hidden" name="product_id" value="{{ product.id }}">
                    <label>{{ t("quantity") }}
                        <select name="quantity">
                        {% for amount in range(1, ([product.bestand, 10]|min) + 1) %}
                            <option value="{{ amount }}">{{ amount }}</option>
                        {% endfor %}
                        </select>
                    </label>
                    <button class="minus" type="submit">
                        {{ t("take_drink") }}
                    </button>
                </form>
            </article>
        {% else %}
            <div class="empty-state">{{ t("no_drinks_available") }}</div>
        {% endfor %}
        </div>
        </body></html>
        """,
        products=products,
    )


@checkout_bp.post("/checkout/remove")
def checkout_remove():
    if not checkout_enabled() or current_user() is None:
        return redirect("/anmelden?next=/checkout")
    try:
        product_id = int(request.form.get("product_id", "0"))
        quantity = min(100, max(1, int(request.form.get("quantity", "1"))))
    except ValueError:
        return redirect("/checkout")

    conn = get_db()
    product = conn.execute(
        "SELECT * FROM produkte WHERE id = ?", (product_id,)
    ).fetchone()
    if product is None or product["bestand"] < quantity:
        conn.close()
        flash(_t("not_enough_stock"), "error")
        return redirect("/checkout")

    barcode = conn.execute(
        "SELECT ean FROM produkt_barcodes WHERE produkt_id = ? ORDER BY ean LIMIT 1",
        (product_id,),
    ).fetchone()
    user_id, user_name = booking_user()
    new_stock = product["bestand"] - quantity
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute(
            "UPDATE produkte SET bestand = ? WHERE id = ?",
            (new_stock, product_id),
        )
        conn.execute(
            """
            INSERT INTO buchungen (
                ean, produkt, aktion, zeitpunkt, menge,
                bestand_vorher, bestand_nachher, quelle,
                einzelpreis_cent, waehrung, benutzer_id, benutzer_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                barcode["ean"] if barcode else f"produkt:{product_id}",
                product["name"], "Checkout", now, -quantity,
                product["bestand"], new_stock, "checkout",
                product["preis_cent"], product["waehrung"], user_id, user_name,
            ),
        )
    conn.close()
    clear_scanner_user()
    try:
        sync_home_assistant_shopping_list_data()
    except Exception as exc:
        current_app.logger.warning(
            "Home Assistant sync after checkout failed: %s", exc
        )
    flash(_t("checkout_booking_saved"), "success")
    return redirect("/checkout")
