import time
import hmac
import os
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_setting, set_setting
from translation import translate
from utils.auth import (
    accounts_enabled,
    admin_required,
    current_user,
    consume_rfid_enrollment,
    hash_rfid,
    login_user,
    rfid_enrollment_status,
    start_rfid_enrollment,
)
from utils.db import get_db
from utils.render import HTML_START, get_language, render_page
from utils.redirects import safe_redirect


auth_bp = Blueprint("auth", __name__)
_login_attempts = defaultdict(list)


def _t(key):
    return translate(key, get_language())


def _rate_limited():
    key = request.remote_addr or "unknown"
    now = time.monotonic()
    attempts = [
        timestamp
        for timestamp in _login_attempts[key]
        if now - timestamp < 300
    ]
    _login_attempts[key] = attempts
    return len(attempts) >= 10


def _record_failed_login():
    key = request.remote_addr or "unknown"
    _login_attempts[key].append(time.monotonic())


@auth_bp.before_app_request
def require_web_login():
    if not accounts_enabled():
        return None

    if request.path.startswith((
        "/static/",
        "/api/",
        "/service-worker.js",
        "/anmelden",
        "/abmelden",
        "/sprache/",
    )):
        return None

    if current_user() is None:
        return redirect(url_for("auth.login", next=request.path))
    return None


@auth_bp.route("/anmelden", methods=["GET", "POST"])
def login():
    if not accounts_enabled():
        return redirect("/")

    if current_user() is not None:
        return redirect("/")

    if request.method == "POST":
        if _rate_limited():
            flash(_t("login_rate_limited"), "error")
            return redirect("/anmelden")

        conn = get_db()
        user = None
        rfid_value = request.form.get("rfid", "").strip()

        if rfid_value:
            try:
                rfid_digest = hash_rfid(rfid_value)
            except ValueError:
                rfid_digest = ""
            if rfid_digest:
                user = conn.execute(
                    """
                    SELECT *
                    FROM benutzer
                    WHERE rfid_hash = ? AND aktiv = 1
                    """,
                    (rfid_digest,),
                ).fetchone()
        else:
            login_name = request.form.get("login_name", "").strip()
            password = request.form.get("password", "")
            candidate = conn.execute(
                """
                SELECT *
                FROM benutzer
                WHERE login_name = ? COLLATE NOCASE AND aktiv = 1
                """,
                (login_name,),
            ).fetchone()
            if candidate and check_password_hash(
                candidate["password_hash"],
                password,
            ):
                user = candidate

        conn.close()

        if user is None:
            _record_failed_login()
            flash(_t("login_failed"), "error")
            return redirect("/anmelden")

        _login_attempts.pop(request.remote_addr or "unknown", None)
        login_user(user)
        return safe_redirect(request.args.get("next", "/"))

    return render_page(
        HTML_START + """
        <div style="max-width:520px;margin:8vh auto 0;">
            <div class="card" style="padding:clamp(24px,5vw,40px);">
                <div class="eyebrow">{{ t("account_login") }}</div>
                <h1 style="margin-top:8px;">👤 {{ t("welcome_back") }}</h1>
                <p style="color:var(--muted);">{{ t("login_description") }}</p>

                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% for category, message in messages %}
                        <div class="success-message">{{ message }}</div>
                    {% endfor %}
                {% endwith %}

                <form method="post" style="display:grid;gap:14px;">
                    <label>
                        <span>{{ t("username") }}</span>
                        <input name="login_name" autocomplete="username" required>
                    </label>
                    <label>
                        <span>{{ t("pin_or_password") }}</span>
                        <input
                            name="password"
                            type="password"
                            autocomplete="current-password"
                            required
                        >
                    </label>
                    <button class="plus" type="submit">{{ t("login") }}</button>
                </form>

                <div style="
                    display:flex;
                    align-items:center;
                    gap:12px;
                    color:var(--muted);
                    margin:24px 0;
                ">
                    <span style="height:1px;background:var(--border);flex:1;"></span>
                    {{ t("or") }}
                    <span style="height:1px;background:var(--border);flex:1;"></span>
                </div>

                <form method="post" id="rfid-login-form" style="display:grid;gap:10px;">
                    <label>
                        <span>{{ t("scan_rfid_chip") }}</span>
                        <input
                            id="rfid-login"
                            name="rfid"
                            autocomplete="off"
                            inputmode="none"
                            placeholder="{{ t('waiting_for_chip') }}"
                            required
                        >
                    </label>
                    <button class="filter" type="submit">◉ {{ t("rfid_login") }}</button>
                </form>
            </div>
        </div>
        <script>
            const rfidInput = document.getElementById("rfid-login");
            let rfidBuffer = "";
            let lastKeyAt = 0;
            document.addEventListener("keydown", (event) => {
                if (event.target.matches("input:not(#rfid-login)")) return;
                const now = Date.now();
                if (now - lastKeyAt > 120) rfidBuffer = "";
                lastKeyAt = now;
                if (event.key === "Enter" && rfidBuffer.length >= 4) {
                    event.preventDefault();
                    rfidInput.value = rfidBuffer;
                    document.getElementById("rfid-login-form").submit();
                    return;
                }
                if (event.key.length === 1 && /[a-zA-Z0-9]/.test(event.key)) {
                    rfidBuffer += event.key;
                    rfidInput.value = rfidBuffer;
                }
            });
        </script>
        """
    )


@auth_bp.post("/abmelden")
def logout():
    session.clear()
    return redirect("/anmelden" if accounts_enabled() else "/")


@auth_bp.get("/konto")
def account_dashboard():
    user = current_user()
    if user is None:
        return redirect("/anmelden")

    return _render_user_statistics(user)


@auth_bp.get("/einstellungen/benutzer/<int:user_id>/statistik")
@admin_required
def user_statistics(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM benutzer WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if user is None:
        flash(_t("user_not_found"), "error")
        return redirect("/einstellungen/benutzer")

    return _render_user_statistics(user, admin_view=True)


def _render_user_statistics(user, admin_view=False):
    periods = {
        "7": ("-7 days", 7, "last_7_days"),
        "30": ("-30 days", 30, "last_30_days"),
        "90": ("-90 days", 90, "last_3_months"),
        "365": ("-365 days", 365, "last_year"),
        "all": (None, None, "total"),
    }
    period = request.args.get("zeitraum", "30")
    if period not in periods:
        period = "30"
    modifier, period_days, period_label = periods[period]
    period_sql = ""
    period_params = [user["id"]]
    if modifier:
        period_sql = (
            " AND zeitpunkt >= datetime('now', 'localtime', ?)"
        )
        period_params.append(modifier)

    base_where = """
        benutzer_id = ?
        AND menge < 0
        AND storniert = 0
        AND quelle != 'storno'
    """

    conn = get_db()
    summary = conn.execute(
        f"""
        SELECT
            COUNT(*) AS buchungen,
            COALESCE(SUM(-menge), 0) AS getraenke,
            COUNT(DISTINCT date(zeitpunkt)) AS aktive_tage,
            MIN(zeitpunkt) AS erste_buchung,
            MAX(zeitpunkt) AS letzte_buchung
        FROM buchungen
        WHERE {base_where}{period_sql}
        """,
        period_params,
    ).fetchone()
    today = conn.execute(
        f"""
        SELECT COALESCE(SUM(-menge), 0) AS getraenke
        FROM buchungen
        WHERE {base_where}
          AND date(zeitpunkt) = date('now', 'localtime')
        """,
        (user["id"],),
    ).fetchone()["getraenke"]
    money_totals = conn.execute(
        f"""
        SELECT
            COALESCE(waehrung, 'EUR') AS waehrung,
            COALESCE(SUM(-menge * COALESCE(einzelpreis_cent, 0)), 0)
                AS kosten_cent,
            COALESCE(SUM(CASE WHEN einzelpreis_cent IS NOT NULL
                THEN -menge ELSE 0 END), 0) AS bepreiste_getraenke
        FROM buchungen
        WHERE {base_where}{period_sql}
        GROUP BY COALESCE(waehrung, 'EUR')
        ORDER BY waehrung
        """,
        period_params,
    ).fetchall()
    products = conn.execute(
        f"""
        SELECT produkt, COALESCE(SUM(-menge), 0) AS getraenke,
               COUNT(*) AS buchungen
        FROM buchungen
        WHERE {base_where}{period_sql}
        GROUP BY produkt
        ORDER BY getraenke DESC, buchungen DESC, produkt COLLATE NOCASE
        LIMIT 10
        """,
        period_params,
    ).fetchall()
    daily_rows = conn.execute(
        f"""
        SELECT date(zeitpunkt) AS datum,
               COALESCE(SUM(-menge), 0) AS getraenke
        FROM buchungen
        WHERE {base_where}{period_sql}
        GROUP BY date(zeitpunkt)
        ORDER BY datum DESC
        LIMIT 30
        """,
        period_params,
    ).fetchall()
    daily = list(reversed(daily_rows))
    chart_max = max((row["getraenke"] for row in daily), default=1)
    weekdays_raw = conn.execute(
        f"""
        SELECT CAST(strftime('%w', zeitpunkt) AS INTEGER) AS weekday,
               COALESCE(SUM(-menge), 0) AS getraenke
        FROM buchungen
        WHERE {base_where}{period_sql}
        GROUP BY strftime('%w', zeitpunkt)
        ORDER BY getraenke DESC
        """,
        period_params,
    ).fetchall()
    weekday_keys = [
        "sunday", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday",
    ]
    weekdays = [
        {
            "name": _t(weekday_keys[row["weekday"]]),
            "getraenke": row["getraenke"],
        }
        for row in weekdays_raw
    ]
    time_slots = conn.execute(
        f"""
        SELECT
            CASE
                WHEN CAST(strftime('%H', zeitpunkt) AS INTEGER) < 6
                    THEN 'night'
                WHEN CAST(strftime('%H', zeitpunkt) AS INTEGER) < 12
                    THEN 'morning'
                WHEN CAST(strftime('%H', zeitpunkt) AS INTEGER) < 18
                    THEN 'afternoon'
                ELSE 'evening'
            END AS slot,
            COALESCE(SUM(-menge), 0) AS getraenke
        FROM buchungen
        WHERE {base_where}{period_sql}
        GROUP BY slot
        ORDER BY getraenke DESC
        """,
        period_params,
    ).fetchall()
    recent = conn.execute(
        f"""
        SELECT *
        FROM buchungen
        WHERE benutzer_id = ?{period_sql}
        ORDER BY id DESC
        LIMIT 100
        """,
        period_params,
    ).fetchall()
    conn.close()

    active_days = summary["aktive_tage"] or 0
    average_active_day = (
        summary["getraenke"] / active_days if active_days else 0
    )
    if period_days:
        average_calendar_day = summary["getraenke"] / period_days
    elif summary["erste_buchung"]:
        first = datetime.fromisoformat(summary["erste_buchung"])
        calendar_days = max((datetime.now() - first).days + 1, 1)
        average_calendar_day = summary["getraenke"] / calendar_days
    else:
        average_calendar_day = 0

    return render_page(
        HTML_START + """
        {% if admin_view %}
        <a class="zurueck" href="/einstellungen/benutzer">← {{ t("back_to_users") }}</a>
        {% endif %}
        <div class="page-hero">
            <div>
                <div class="eyebrow">{{ t("user_statistics") }}</div>
                <h1>👤 {{ user.name }}</h1>
                <p>{{ t("detailed_user_statistics_description") }}</p>
            </div>
            {% if not admin_view %}
            <form method="post" action="/abmelden">
                <button class="filter" type="submit">{{ t("logout") }}</button>
            </form>
            {% endif %}
        </div>

        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;">
            {% for value, label in period_options %}
            <a class="button filter {% if period == value %}filter-aktiv{% endif %}"
               href="?zeitraum={{ value }}">{{ t(label) }}</a>
            {% endfor %}
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-label">{{ t(period_label) }}</div>
                <div class="stat-zahl">{{ summary.getraenke }}</div>
                <div class="stat-label">{{ t("drinks") }}</div>
            </div>
            <div class="stat">
                <div class="stat-label">{{ t("today") }}</div>
                <div class="stat-zahl">{{ today }}</div>
                <div class="stat-label">{{ t("drinks") }}</div>
            </div>
            <div class="stat">
                <div class="stat-label">{{ t("active_days") }}</div>
                <div class="stat-zahl">{{ summary.aktive_tage }}</div>
                <div class="stat-label">{{ t("days_with_consumption") }}</div>
            </div>
            <div class="stat">
                <div class="stat-label">{{ t("average_per_active_day") }}</div>
                <div class="stat-zahl">{{ "%.1f"|format(average_active_day) }}</div>
                <div class="stat-label">{{ t("drinks") }}</div>
            </div>
            <div class="stat">
                <div class="stat-label">{{ t("average_per_calendar_day") }}</div>
                <div class="stat-zahl">{{ "%.2f"|format(average_calendar_day) }}</div>
                <div class="stat-label">{{ t("drinks") }}</div>
            </div>
            <div class="stat">
                <div class="stat-label">{{ t("booking_events") }}</div>
                <div class="stat-zahl">{{ summary.buchungen }}</div>
                <div class="stat-label">{{ t("withdrawals") }}</div>
            </div>
        </div>

        <div class="card">
            <h2>💰 {{ t("personal_costs") }}</h2>
            <p style="color:var(--muted);">{{ t("currencies_not_converted") }}</p>
            <div class="stats" style="margin-top:18px;">
                {% for total in money_totals %}
                <div class="stat">
                    <div class="stat-label">{{ total.waehrung }}</div>
                    <div class="stat-zahl" style="font-size:clamp(1.45rem,4vw,2.25rem);">
                        {{ format_money(total.kosten_cent, total.waehrung) }}
                    </div>
                    <div class="stat-label">
                        {{ total.bepreiste_getraenke }} {{ t("priced_drinks") }}
                    </div>
                </div>
                {% else %}
                <p>{{ t("no_price_data") }}</p>
                {% endfor %}
            </div>
        </div>

        <div class="card">
            <h2>📈 {{ t("personal_consumption_trend") }}</h2>
            <p style="color:var(--muted);">{{ t("last_30_active_calendar_days_hint") }}</p>
            {% if daily %}
            <div class="chart" aria-label="{{ t('personal_consumption_trend') }}">
                {% for day in daily %}
                <div class="chart-column">
                    <span class="chart-value">{{ day.getraenke }}</span>
                    <div class="chart-bar" style="height:{{ (day.getraenke * 130 / chart_max)|round|int }}px"></div>
                    <span class="chart-label">{{ day.datum[5:] }}</span>
                </div>
                {% endfor %}
            </div>
            {% else %}<p>{{ t("no_consumption_period") }}</p>{% endif %}
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px;">
            <div class="card" style="margin:0;">
                <h2>🏆 {{ t("favorite_products") }}</h2>
                <table class="responsive-table">
                    <tr class="table-head"><th>#</th><th>{{ t("product") }}</th><th>{{ t("drinks") }}</th></tr>
                    {% for product in products %}
                    <tr><td>{{ loop.index }}</td><td class="mobile-primary">{{ product.produkt }}</td><td>{{ product.getraenke }}</td></tr>
                    {% else %}<tr><td colspan="3">{{ t("no_consumption_period") }}</td></tr>{% endfor %}
                </table>
            </div>
            <div class="card" style="margin:0;">
                <h2>📅 {{ t("consumption_patterns") }}</h2>
                <h3>{{ t("weekdays") }}</h3>
                {% for item in weekdays %}
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
                    <span>{{ item.name }}</span><strong>{{ item.getraenke }}</strong>
                </div>
                {% else %}<p>{{ t("no_consumption_period") }}</p>{% endfor %}
                <h3 style="margin-top:22px;">{{ t("times_of_day") }}</h3>
                {% for item in time_slots %}
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
                    <span>{{ t(item.slot) }}</span><strong>{{ item.getraenke }}</strong>
                </div>
                {% else %}<p>{{ t("no_consumption_period") }}</p>{% endfor %}
            </div>
        </div>

        <div class="card">
            <h2>{{ t("booking_history") }}</h2>
            <table class="responsive-table">
                <tr class="table-head">
                    <th>{{ t("time") }}</th>
                    <th>{{ t("product") }}</th>
                    <th>{{ t("change") }}</th>
                    <th>{{ t("value") }}</th>
                    <th>{{ t("source") }}</th>
                    <th>{{ t("status") }}</th>
                </tr>
                {% for booking in recent %}
                <tr>
                    <td>{{ booking.zeitpunkt }}</td>
                    <td class="mobile-primary">{{ booking.produkt }}</td>
                    <td>{% if booking.menge > 0 %}+{% endif %}{{ booking.menge }}</td>
                    <td>
                        {% if booking.einzelpreis_cent is not none %}
                            {{ format_money(
                                booking.einzelpreis_cent * (booking.menge|abs),
                                booking.waehrung
                            ) }}
                        {% else %}—{% endif %}
                    </td>
                    <td>{{ booking.quelle or "—" }}</td>
                    <td>{{ t("cancelled") if booking.storniert else t("booked") }}</td>
                </tr>
                {% else %}
                <tr><td colspan="6">{{ t("no_bookings_period") }}</td></tr>
                {% endfor %}
            </table>
        </div>
        """,
        user=user,
        admin_view=admin_view,
        period=period,
        period_label=period_label,
        period_options=[(key, value[2]) for key, value in periods.items()],
        summary=summary,
        today=today,
        average_active_day=average_active_day,
        average_calendar_day=average_calendar_day,
        money_totals=money_totals,
        products=products,
        daily=daily,
        chart_max=chart_max,
        weekdays=weekdays,
        time_slots=time_slots,
        recent=recent,
    )


@auth_bp.get("/einstellungen/benutzer")
def user_management():
    enabled = accounts_enabled()
    user = current_user()
    if enabled and (user is None or user["rolle"] != "admin"):
        return redirect("/anmelden")

    conn = get_db()
    users = conn.execute(
        """
        SELECT id, name, login_name, rolle, aktiv,
               CASE WHEN rfid_hash IS NULL THEN 0 ELSE 1 END AS has_rfid
        FROM benutzer
        ORDER BY name COLLATE NOCASE
        """
    ).fetchall()
    unassigned_bookings = conn.execute(
        """
        SELECT id, produkt, zeitpunkt, menge, quelle,
               einzelpreis_cent, waehrung
        FROM buchungen
        WHERE benutzer_id IS NULL
          AND menge < 0
          AND storniert = 0
          AND quelle != 'storno'
        ORDER BY id DESC
        LIMIT 100
        """
    ).fetchall()
    conn.close()
    scanner_user_required = get_setting(
        "scanner_benutzer_erforderlich", "0"
    ).lower() in ("1", "true", "yes", "on")

    return render_page(
        HTML_START + """
        <a class="zurueck" href="/einstellungen">← {{ t("back_to_settings") }}</a>
        <div class="page-hero">
            <div>
                <div class="eyebrow">{{ t("optional_feature") }}</div>
                <h1>👥 {{ t("user_accounts") }}</h1>
                <p>{{ t("user_accounts_description") }}</p>
            </div>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}
                <div class="success-message">{{ message }}</div>
            {% endfor %}
        {% endwith %}

        {% if not enabled %}
        <div class="card">
            <h2>{{ t("enable_user_accounts") }}</h2>
            <p style="color:var(--muted);">{{ t("create_first_admin") }}</p>
            <form method="post" action="/einstellungen/benutzer/aktivieren"
                  style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;">
                <input name="name" placeholder="{{ t('display_name') }}" required>
                <input name="login_name" placeholder="{{ t('username') }}" required>
                <input name="password" type="password"
                       placeholder="{{ t('pin_or_password') }}" minlength="4" required>
                <input name="setup_password" type="password"
                       placeholder="{{ t('current_admin_password') }}" required>
                <button class="plus" type="submit">{{ t("enable") }}</button>
            </form>
        </div>
        {% else %}
        <div class="card">
            <h2>{{ t("scanner_account_policy") }}</h2>
            <p style="color:var(--muted);">
                {{ t("require_user_for_scanner_desc") }}
            </p>
            <form method="post"
                  action="/einstellungen/benutzer/scanner-regel">
                <label style="display:flex;gap:12px;align-items:center;">
                    <input type="checkbox" name="required" value="1"
                           {% if scanner_user_required %}checked{% endif %}>
                    <span>{{ t("require_user_for_scanner") }}</span>
                </label>
                <button class="plus" type="submit" style="margin-top:14px;">
                    {{ t("save") }}
                </button>
            </form>
        </div>

        <div class="card">
            <h2>{{ t("create_user") }}</h2>
            <form method="post" action="/einstellungen/benutzer/anlegen"
                  id="create-user-form"
                  style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;">
                <input name="name" placeholder="{{ t('display_name') }}" required>
                <input name="login_name" placeholder="{{ t('username') }}" required>
                <input name="password" type="password"
                       placeholder="{{ t('pin_or_password') }}" minlength="4" required>
                <input name="rfid" autocomplete="off" id="rfid-value"
                       placeholder="{{ t('rfid_chip_optional') }}">
                <input name="rfid_enrollment_token" type="hidden"
                       id="rfid-enrollment-token">
                <button class="filter" type="button" id="rfid-enroll-button">
                    ◉ {{ t("learn_rfid_chip") }}
                </button>
                <div id="rfid-enroll-status" aria-live="polite"
                     style="color:var(--muted);align-self:center;"></div>
                <select name="rolle">
                    <option value="user">{{ t("user") }}</option>
                    <option value="admin">{{ t("administrator") }}</option>
                </select>
                <button class="plus" type="submit">{{ t("create") }}</button>
            </form>
            <script>
            (() => {
                const button = document.getElementById("rfid-enroll-button");
                const status = document.getElementById("rfid-enroll-status");
                const tokenInput = document.getElementById("rfid-enrollment-token");
                const manualInput = document.getElementById("rfid-value");
                let pollTimer;

                const text = {
                    starting: {{ t("rfid_enrollment_starting")|tojson }},
                    waiting: {{ t("rfid_enrollment_waiting")|tojson }},
                    captured: {{ t("rfid_enrollment_captured")|tojson }},
                    expired: {{ t("rfid_enrollment_expired")|tojson }},
                    failed: {{ t("rfid_enrollment_failed")|tojson }}
                };

                async function poll(token) {
                    try {
                        const response = await fetch(
                            "/einstellungen/benutzer/rfid-anlernen/status?token=" +
                            encodeURIComponent(token),
                            {cache: "no-store"}
                        );
                        if (!response.ok) throw new Error();
                        const data = await response.json();
                        if (data.status === "captured") {
                            status.textContent = "✓ " + text.captured;
                            manualInput.value = "";
                            manualInput.disabled = true;
                            button.disabled = false;
                            return;
                        }
                        if (data.status === "expired" || data.status === "invalid") {
                            status.textContent = text.expired;
                            tokenInput.value = "";
                            button.disabled = false;
                            return;
                        }
                        pollTimer = setTimeout(() => poll(token), 1000);
                    } catch (_) {
                        status.textContent = text.failed;
                        tokenInput.value = "";
                        button.disabled = false;
                    }
                }

                button.addEventListener("click", async () => {
                    clearTimeout(pollTimer);
                    button.disabled = true;
                    status.textContent = text.starting;
                    manualInput.disabled = false;
                    manualInput.value = "";
                    try {
                        const response = await fetch(
                            "/einstellungen/benutzer/rfid-anlernen/start",
                            {method: "POST", cache: "no-store"}
                        );
                        if (!response.ok) throw new Error();
                        const data = await response.json();
                        tokenInput.value = data.token;
                        status.textContent = text.waiting;
                        poll(data.token);
                    } catch (_) {
                        status.textContent = text.failed;
                        button.disabled = false;
                    }
                });
            })();
            </script>
        </div>

        <div class="card">
            <h2>{{ t("existing_users") }}</h2>
            <table class="responsive-table">
                <tr class="table-head">
                    <th>{{ t("display_name") }}</th>
                    <th>{{ t("username") }}</th>
                    <th>{{ t("role") }}</th>
                    <th>RFID</th>
                    <th>{{ t("status") }}</th>
                    <th>{{ t("actions") }}</th>
                </tr>
                {% for account in users %}
                <tr>
                    <td class="mobile-primary">{{ account.name }}</td>
                    <td>{{ account.login_name }}</td>
                    <td>{{ t("administrator") if account.rolle == "admin" else t("user") }}</td>
                    <td>{{ "✓" if account.has_rfid else "—" }}</td>
                    <td>{{ t("active") if account.aktiv else t("inactive") }}</td>
                    <td>
                        <a class="button filter"
                           href="/einstellungen/benutzer/{{ account.id }}/statistik">
                            📊 {{ t("view_statistics") }}
                        </a>
                        <button class="filter existing-rfid-enroll" type="button"
                                data-user-id="{{ account.id }}">
                            ◉ {{ t("replace_rfid_chip") if account.has_rfid else t("add_rfid_chip") }}
                        </button>
                        <div id="rfid-status-{{ account.id }}" aria-live="polite"
                             style="color:var(--muted);margin-top:6px;"></div>
                    </td>
                </tr>
                {% endfor %}
            </table>
            <script>
            (() => {
                const text = {
                    starting: {{ t("rfid_enrollment_starting")|tojson }},
                    waiting: {{ t("rfid_enrollment_waiting")|tojson }},
                    captured: {{ t("rfid_assignment_saving")|tojson }},
                    expired: {{ t("rfid_enrollment_expired")|tojson }},
                    failed: {{ t("rfid_enrollment_failed")|tojson }}
                };

                async function enroll(button) {
                    const userId = button.dataset.userId;
                    const status = document.getElementById("rfid-status-" + userId);
                    button.disabled = true;
                    status.textContent = text.starting;
                    try {
                        const startResponse = await fetch(
                            "/einstellungen/benutzer/rfid-anlernen/start",
                            {method: "POST", cache: "no-store"}
                        );
                        if (!startResponse.ok) throw new Error();
                        const {token} = await startResponse.json();
                        status.textContent = text.waiting;

                        while (true) {
                            await new Promise(resolve => setTimeout(resolve, 1000));
                            const checkResponse = await fetch(
                                "/einstellungen/benutzer/rfid-anlernen/status?token=" +
                                encodeURIComponent(token),
                                {cache: "no-store"}
                            );
                            if (!checkResponse.ok) throw new Error();
                            const data = await checkResponse.json();
                            if (data.status === "waiting") continue;
                            if (data.status !== "captured") {
                                status.textContent = text.expired;
                                button.disabled = false;
                                return;
                            }

                            status.textContent = text.captured;
                            const body = new URLSearchParams({token});
                            const assignResponse = await fetch(
                                "/einstellungen/benutzer/" + userId + "/rfid-zuordnen",
                                {method: "POST", body}
                            );
                            const result = await assignResponse.json();
                            if (!assignResponse.ok || !result.success) {
                                status.textContent = result.message || text.failed;
                                button.disabled = false;
                                return;
                            }
                            window.location.reload();
                            return;
                        }
                    } catch (_) {
                        status.textContent = text.failed;
                        button.disabled = false;
                    }
                }

                document.querySelectorAll(".existing-rfid-enroll").forEach(button => {
                    button.addEventListener("click", () => enroll(button));
                });
            })();
            </script>
        </div>

        <div class="card">
            <h2>{{ t("unassigned_bookings") }}</h2>
            <p style="color:var(--muted);">
                {{ t("unassigned_bookings_description") }}
            </p>
            <table class="responsive-table">
                <tr class="table-head">
                    <th>{{ t("time") }}</th>
                    <th>{{ t("product") }}</th>
                    <th>{{ t("source") }}</th>
                    <th>{{ t("value") }}</th>
                    <th>{{ t("assign_to_user") }}</th>
                </tr>
                {% for booking in unassigned_bookings %}
                <tr>
                    <td>{{ booking.zeitpunkt }}</td>
                    <td class="mobile-primary">{{ booking.produkt }}</td>
                    <td>{{ booking.quelle or "—" }}</td>
                    <td>
                        {% if booking.einzelpreis_cent is not none %}
                            {{ format_money(
                                booking.einzelpreis_cent * (booking.menge|abs),
                                booking.waehrung
                            ) }}
                        {% else %}—{% endif %}
                    </td>
                    <td>
                        <form method="post"
                              action="/einstellungen/benutzer/buchung/{{ booking.id }}/zuordnen"
                              style="display:flex;gap:8px;min-width:240px;">
                            <select name="benutzer_id" required>
                                <option value="">{{ t("select_user") }}</option>
                                {% for account in users if account.aktiv %}
                                <option value="{{ account.id }}">{{ account.name }}</option>
                                {% endfor %}
                            </select>
                            <button class="plus" type="submit">{{ t("assign") }}</button>
                        </form>
                    </td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="5">{{ t("no_unassigned_bookings") }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <div class="card" style="border-color:rgba(251,113,133,.35);">
            <h2>{{ t("disable_user_accounts") }}</h2>
            <p style="color:var(--muted);">{{ t("disable_user_accounts_desc") }}</p>
            <form method="post" action="/einstellungen/benutzer/deaktivieren"
                  onsubmit="return confirm('{{ t("disable_user_accounts_confirm") }}');">
                <button class="minus" type="submit">{{ t("disable") }}</button>
            </form>
        </div>
        {% endif %}
        """,
        enabled=enabled,
        users=users,
        unassigned_bookings=unassigned_bookings,
        scanner_user_required=scanner_user_required,
    )


@auth_bp.post("/einstellungen/benutzer/aktivieren")
def enable_accounts():
    if accounts_enabled():
        return redirect("/einstellungen/benutzer")

    name = request.form.get("name", "").strip()
    login_name = request.form.get("login_name", "").strip()
    password = request.form.get("password", "")
    setup_password = request.form.get("setup_password", "")
    expected_setup_password = os.environ.get("STORNO_PASSWORT", "")
    if (
        not expected_setup_password
        or not hmac.compare_digest(
            setup_password,
            expected_setup_password,
        )
    ):
        flash(_t("wrong_admin_password"), "error")
        return redirect("/einstellungen/benutzer")

    if not name or not login_name or len(password) < 4:
        flash(_t("invalid_account_data"), "error")
        return redirect("/einstellungen/benutzer")

    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO benutzer (
                name, login_name, password_hash, rolle
            )
            VALUES (?, ?, ?, 'admin')
            """,
            (name, login_name, generate_password_hash(password)),
        )
        conn.commit()
        user = conn.execute(
            "SELECT * FROM benutzer WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    except Exception:
        conn.rollback()
        conn.close()
        flash(_t("account_create_failed"), "error")
        return redirect("/einstellungen/benutzer")
    conn.close()

    set_setting("benutzerkonten_aktiv", "1")
    login_user(user)
    return redirect("/einstellungen/benutzer")


@auth_bp.post("/einstellungen/benutzer/anlegen")
@admin_required
def create_user():
    name = request.form.get("name", "").strip()
    login_name = request.form.get("login_name", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("rolle", "user")
    rfid_value = request.form.get("rfid", "").strip()
    enrollment_token = request.form.get("rfid_enrollment_token", "").strip()

    if role not in {"user", "admin"}:
        role = "user"
    if not name or not login_name or len(password) < 4:
        flash(_t("invalid_account_data"), "error")
        return redirect("/einstellungen/benutzer")

    try:
        rfid_digest = (
            consume_rfid_enrollment(enrollment_token)
            if enrollment_token
            else (hash_rfid(rfid_value) if rfid_value else None)
        )
    except ValueError:
        flash(_t("invalid_rfid"), "error")
        return redirect("/einstellungen/benutzer")
    if enrollment_token and not rfid_digest:
        flash(_t("rfid_enrollment_expired"), "error")
        return redirect("/einstellungen/benutzer")

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO benutzer (
                name, login_name, password_hash, rfid_hash, rolle
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                login_name,
                generate_password_hash(password),
                rfid_digest,
                role,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        flash(_t("account_create_failed"), "error")
    else:
        flash(_t("account_created"), "success")
    finally:
        conn.close()
    return redirect("/einstellungen/benutzer")


@auth_bp.post("/einstellungen/benutzer/rfid-anlernen/start")
@admin_required
def begin_rfid_enrollment():
    return jsonify(token=start_rfid_enrollment())


@auth_bp.get("/einstellungen/benutzer/rfid-anlernen/status")
@admin_required
def get_rfid_enrollment_status():
    token = request.args.get("token", "")
    return jsonify(status=rfid_enrollment_status(token))


@auth_bp.post("/einstellungen/benutzer/<int:user_id>/rfid-zuordnen")
@admin_required
def assign_rfid_to_user(user_id):
    digest = consume_rfid_enrollment(request.form.get("token", ""))
    if not digest:
        return jsonify(
            success=False,
            message=_t("rfid_enrollment_expired"),
        ), 400

    conn = get_db()
    user = conn.execute(
        "SELECT id FROM benutzer WHERE id = ? AND aktiv = 1",
        (user_id,),
    ).fetchone()
    if user is None:
        conn.close()
        return jsonify(success=False, message=_t("invalid_user")), 404

    try:
        conn.execute(
            "UPDATE benutzer SET rfid_hash = ? WHERE id = ?",
            (digest, user_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return jsonify(
            success=False,
            message=_t("rfid_already_assigned"),
        ), 409
    conn.close()
    return jsonify(success=True)


@auth_bp.post(
    "/einstellungen/benutzer/buchung/<int:booking_id>/zuordnen"
)
@admin_required
def assign_booking(booking_id):
    try:
        user_id = int(request.form.get("benutzer_id", "0"))
    except ValueError:
        user_id = 0

    conn = get_db()
    user = conn.execute(
        """
        SELECT id, name
        FROM benutzer
        WHERE id = ? AND aktiv = 1
        """,
        (user_id,),
    ).fetchone()
    if user is None:
        conn.close()
        flash(_t("invalid_user"), "error")
        return redirect("/einstellungen/benutzer")

    cursor = conn.execute(
        """
        UPDATE buchungen
        SET benutzer_id = ?, benutzer_name = ?
        WHERE id = ?
          AND benutzer_id IS NULL
          AND menge < 0
          AND storniert = 0
          AND quelle != 'storno'
        """,
        (user["id"], user["name"], booking_id),
    )
    conn.commit()
    conn.close()
    flash(
        _t(
            "booking_assigned"
            if cursor.rowcount
            else "booking_assignment_failed"
        ),
        "success",
    )
    return redirect("/einstellungen/benutzer")


@auth_bp.post("/einstellungen/benutzer/scanner-regel")
@admin_required
def set_scanner_policy():
    required = request.form.get("required") == "1"
    set_setting(
        "scanner_benutzer_erforderlich",
        "1" if required else "0",
    )
    flash(_t("scanner_policy_saved"), "success")
    return redirect("/einstellungen/benutzer")


@auth_bp.post("/einstellungen/benutzer/deaktivieren")
@admin_required
def disable_accounts():
    set_setting("benutzerkonten_aktiv", "0")
    set_setting("scanner_benutzer_erforderlich", "0")
    set_setting("aktiver_scanner_benutzer", "")
    set_setting("aktiver_scanner_benutzer_bis", "")
    session.clear()
    return redirect("/einstellungen/benutzer")
