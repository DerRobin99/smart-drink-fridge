from datetime import datetime

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, request
from werkzeug.security import generate_password_hash

from database import get_setting, set_setting
from docker_update import docker_request
from translation import normalize_language, translate
from utils.auth import login_user
from utils.db import get_db
from utils.money import CURRENCY_CHOICES, normalize_currency, parse_optional_price_cents
from utils.notifications import save_pushover_credentials
from utils.render import HTML_START, get_language, render_page
from utils.system_status import get_system_status
from location_inventory import initialize_product_location


setup_bp = Blueprint("setup", __name__)


def setup_complete():
    return get_setting("setup_completed", "0") == "1"


@setup_bp.before_app_request
def require_initial_setup():
    if current_app.config.get("TESTING") or setup_complete():
        return None
    if request.path.startswith(("/setup", "/static/", "/service-worker.js", "/api/")):
        return None
    return redirect("/setup")


def _t(key):
    return translate(key, get_language())


def _scanner_container_test():
    status = get_system_status()["containers"]
    camera = status.get("camera") or {}
    return {
        "ok": bool(camera.get("configured") and camera.get("running")),
        "message": _t("setup_scanner_ready") if camera.get("configured") and camera.get("running")
        else _t("setup_scanner_not_ready"),
    }


def _test_beep():
    containers = docker_request("GET", "/containers/json?all=true")
    scanner = next(
        (item for item in containers if "/smart-drink-fridge-scanner" in item.get("Names", [])),
        None,
    )
    if not scanner or scanner.get("State") != "running":
        raise RuntimeError("scanner container unavailable")
    created = docker_request(
        "POST",
        f"/containers/{scanner['Id']}/exec",
        {
            "AttachStdout": True,
            "AttachStderr": True,
            "Cmd": [
                "python3", "-c",
                "from scanner_booking import _beep; from gpiozero import Buzzer; _beep(Buzzer(17), 2, 0.08)",
            ],
        },
    )
    docker_request("POST", f"/exec/{created['Id']}/start", {"Detach": False, "Tty": False})


@setup_bp.get("/setup")
def setup():
    if setup_complete():
        return redirect("/")
    return render_page(
        HTML_START + """
        <div class="page-hero"><div><div class="eyebrow">{{ t("setup_assistant") }}</div>
        <h1>{{ t("setup_welcome") }}</h1><p>{{ t("setup_intro") }}</p></div></div>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% for category, message in messages %}<div class="success-message">{{ message }}</div>{% endfor %}
        {% endwith %}
        <form method="post" action="/setup/complete" style="display:grid;gap:18px;">
          <section class="card"><h2>1. {{ t("setup_language_currency") }}</h2>
            <div class="form-grid"><label>{{ t("language") }}<select name="language">
              {% for code, name in languages %}<option value="{{ code }}">{{ name }}</option>{% endfor %}
            </select></label><label>{{ t("default_currency") }}<select name="currency">
              {% for code, label in currencies %}<option value="{{ code }}" {% if code == 'EUR' %}selected{% endif %}>{{ label }}</option>{% endfor %}
            </select></label></div></section>
          <section class="card"><h2>2. {{ t("setup_admin") }}</h2><div class="form-grid">
            <input name="admin_name" placeholder="{{ t('display_name') }}" required>
            <input name="admin_login" placeholder="{{ t('username') }}" required>
            <input name="admin_password" type="password" minlength="4" placeholder="{{ t('pin_or_password') }}" required>
          </div></section>
          <section class="card"><h2>3. {{ t("setup_hardware") }}</h2>
            <p>{{ t("setup_hardware_desc") }}</p><div style="display:flex;gap:10px;flex-wrap:wrap;">
              <button type="button" class="filter setup-test" data-test="scanner">{{ t("test_camera_scanner") }}</button>
              <button type="button" class="filter setup-test" data-test="beep">{{ t("test_beep") }}</button>
            </div><div id="setup-test-result" style="margin-top:12px;"></div>
            <div class="stats" style="margin-top:16px;">{% for item in containers %}<div class="stat"><strong>{{ item.name }}</strong><br>{{ item.state }}<br><small>{{ item.status }}</small></div>{% endfor %}</div>
          </section>
          <section class="card"><h2>4. {{ t("setup_integrations") }}</h2><p>{{ t("setup_optional") }}</p>
            <div class="form-grid"><input name="ha_url" placeholder="Home Assistant URL"><input name="ha_token" type="password" placeholder="Home Assistant token">
            <input name="pushover_user" type="password" placeholder="Pushover user key"><input name="pushover_token" type="password" placeholder="Pushover app token"></div>
          </section>
          <section class="card"><h2>5. {{ t("setup_first_product") }}</h2><p>{{ t("setup_optional") }}</p>
            <div class="form-grid"><input name="product_ean" placeholder="EAN / UPC"><input name="product_name" placeholder="{{ t('product') }}">
            <input name="product_stock" type="number" min="0" value="0"><input name="product_price" inputmode="decimal" placeholder="0.00"></div>
          </section>
          <section class="card"><h2>6. {{ t("setup_finish") }}</h2><p>{{ t("setup_finish_desc") }}</p>
            <button class="plus" type="submit">{{ t("complete_setup") }}</button></section>
        </form>
        <script>document.querySelectorAll('.setup-test').forEach(button => button.addEventListener('click', async () => {
          const result = document.getElementById('setup-test-result'); result.textContent = '{{ t("testing") }}';
          const response = await fetch('/setup/test/' + button.dataset.test, {method:'POST'});
          const data = await response.json(); result.textContent = data.message; result.style.color = data.ok ? '#22c55e' : '#fb7185';
        }));</script></body></html>
        """,
        languages=[("de", "Deutsch"), ("en", "English"), ("fr", "Français")],
        currencies=CURRENCY_CHOICES,
        containers=get_system_status()["containers"].get("containers", []),
    )


@setup_bp.post("/setup/test/<component>")
def setup_test(component):
    if setup_complete():
        abort(404)
    if component == "scanner":
        return jsonify(_scanner_container_test())
    if component == "beep":
        try:
            _test_beep()
        except (KeyError, OSError, RuntimeError):
            return jsonify(ok=False, message=_t("setup_beep_unavailable")), 503
        return jsonify(ok=True, message=_t("setup_beep_success"))
    abort(404)


@setup_bp.post("/setup/complete")
def complete_setup():
    if setup_complete():
        return redirect("/")
    language = normalize_language(request.form.get("language"))
    currency = normalize_currency(request.form.get("currency"), "EUR")
    name = request.form.get("admin_name", "").strip()
    login = request.form.get("admin_login", "").strip()
    password = request.form.get("admin_password", "")
    if not name or not login or len(password) < 4:
        flash(_t("invalid_account_data"), "error")
        return redirect("/setup")

    conn = get_db()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO benutzer (name, login_name, password_hash, rolle) VALUES (?, ?, ?, 'admin')",
                (name, login, generate_password_hash(password)),
            )
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('language', ?)", (language,))
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('default_currency', ?)", (currency,))
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('benutzerkonten_aktiv', '1')")
            ha_url = request.form.get("ha_url", "").strip().rstrip("/")
            ha_token = request.form.get("ha_token", "").strip()
            if ha_url and ha_token:
                conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('ha_url', ?)", (ha_url,))
                conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('ha_token', ?)", (ha_token,))
                conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('ha_einkaufsliste_aktiv', '1')")
            ean = request.form.get("product_ean", "").strip()
            product_name = request.form.get("product_name", "").strip()
            if ean and product_name:
                stock = max(0, int(request.form.get("product_stock", "0")))
                price = parse_optional_price_cents(request.form.get("product_price")) or 0
                product = conn.execute(
                    "INSERT INTO produkte (name, bestand, preis_cent, waehrung) VALUES (?, ?, ?, ?)",
                    (product_name, stock, price, currency),
                )
                initialize_product_location(conn, product.lastrowid, stock)
                conn.execute("INSERT INTO produkt_barcodes (ean, produkt_id) VALUES (?, ?)", (ean, product.lastrowid))
                if stock:
                    conn.execute(
                        "INSERT INTO buchungen (ean, produkt, aktion, zeitpunkt, menge, bestand_vorher, bestand_nachher, quelle, einzelpreis_cent, waehrung) VALUES (?, ?, 'Anfangsbestand', ?, ?, 0, ?, 'setup', ?, ?)",
                        (ean, product_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), stock, stock, price, currency),
                    )
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('setup_completed', '1')")
            user = conn.execute("SELECT * FROM benutzer WHERE id = ?", (cursor.lastrowid,)).fetchone()
    except (ValueError, TypeError):
        conn.rollback(); conn.close()
        flash(_t("settings_invalid"), "error")
        return redirect("/setup")
    conn.close()

    pushover_user = request.form.get("pushover_user", "").strip()
    pushover_token = request.form.get("pushover_token", "").strip()
    if pushover_user and pushover_token:
        save_pushover_credentials(pushover_user, pushover_token)
        set_setting("pushover_enabled", "1")
    login_user(user)
    response = redirect("/")
    response.set_cookie("lang", language, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response
