import hmac
import os
import re

from flask import Blueprint, abort, flash, jsonify, redirect, request
from translation import translate
from utils.render import get_language

from backup import BACKUP_FREQUENCIES, backup_schedule, list_backups
from database import get_setting, set_setting
from utils.auth import accounts_enabled, current_user
from utils.db import get_db
from utils.system_status import get_system_status
from utils.notifications import (
    PUSHOVER_EVENTS,
    pushover_configured,
    save_pushover_credentials,
    send_pushover,
)
from utils.money import CURRENCY_CHOICES, normalize_currency
from werkzeug.security import check_password_hash
from host_control import request_host_action
from docker_update import (
    docker_update_available,
    docker_update_in_progress,
    docker_update_status,
    start_docker_update,
)


def create_settings_blueprint(
    render_page,
    html_start,
    available_languages,
    get_update_info,
    current_version,
):
    settings_bp = Blueprint("settings", __name__)

    def require_settings_admin():
        if not accounts_enabled():
            return
        user = current_user()
        if user is None or user["rolle"] != "admin":
            abort(403)

    def verify_control_password(password):
        user = current_user()
        if accounts_enabled():
            if user is None or user["rolle"] != "admin":
                return False
            conn = get_db()
            row = conn.execute(
                "SELECT password_hash FROM benutzer WHERE id = ?",
                (user["id"],),
            ).fetchone()
            conn.close()
            return bool(row and check_password_hash(row["password_hash"], password))
        expected = os.environ.get("STORNO_PASSWORT", "")
        return bool(expected and hmac.compare_digest(expected, password))

    @settings_bp.route("/einstellungen", methods=["GET", "POST"])
    def einstellungen():
        require_settings_admin()
        conn = get_db()

        if request.method == "POST":
            enabled = (
                "1"
                if request.form.get("ha_einkaufsliste_aktiv") == "on"
                else "0"
            )
            ha_url = request.form.get("ha_url", "").strip()
            ha_token = request.form.get("ha_token", "").strip()

            show_empty_products = (
                "1"
                if request.form.get("show_empty_products") == "on"
                else "0"
            )
            checkout_mode_enabled = (
                "1" if request.form.get("checkout_mode_enabled") == "on" else "0"
            )
            host_control_enabled = (
                "1" if request.form.get("host_control_enabled") == "on" else "0"
            )
            display_show_user = (
                "1" if request.form.get("display_show_user") == "on" else "0"
            )
            display_show_booking = (
                "1" if request.form.get("display_show_booking") == "on" else "0"
            )
            display_show_inventory = (
                "1" if request.form.get("display_show_inventory") == "on" else "0"
            )
            try:
                default_currency = normalize_currency(
                    request.form.get("default_currency"), "EUR"
                )
                display_rotate_seconds = min(120, max(3, int(
                    request.form.get("display_rotate_seconds", "10")
                )))
            except (TypeError, ValueError):
                flash(translate("settings_invalid", get_language()), "error")
                conn.close()
                return redirect("/einstellungen")
            accent_color = request.form.get(
                "theme_accent",
                "#38bdf8",
            ).strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent_color):
                accent_color = "#38bdf8"

            backup_enabled = (
                "1" if request.form.get("backup_enabled") == "on" else "0"
            )
            backup_frequency = request.form.get("backup_frequency", "daily")
            if backup_frequency not in BACKUP_FREQUENCIES:
                backup_frequency = "daily"
            backup_time = request.form.get("backup_time", "03:00")
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", backup_time):
                backup_time = "03:00"
            try:
                backup_weekday = min(6, max(0, int(
                    request.form.get("backup_weekday", "0")
                )))
                backup_max_backups = min(365, max(1, int(
                    request.form.get("backup_max_backups", "30")
                )))
                backup_max_age_days = min(3650, max(0, int(
                    request.form.get("backup_max_age_days", "90")
                )))
            except ValueError:
                flash(translate("backup_settings_invalid", get_language()), "error")
                conn.close()
                return redirect("/einstellungen#backup")

            conn.execute(
                """
                INSERT INTO einstellungen (schluessel, wert)
                VALUES ('ha_einkaufsliste_aktiv', ?)
                ON CONFLICT(schluessel)
                DO UPDATE SET wert = excluded.wert
                """,
                (enabled,),
            )
            conn.execute(
                "INSERT INTO einstellungen (schluessel, wert) VALUES (\"ha_url\", ?) ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
                (ha_url,),
            )

            conn.execute(
                "INSERT INTO einstellungen (schluessel, wert) VALUES (\"ha_token\", ?) ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
                (ha_token,),
            )

            conn.execute(
                """
                INSERT INTO einstellungen (schluessel, wert)
                VALUES ('show_empty_products', ?)
                ON CONFLICT(schluessel)
                DO UPDATE SET wert = excluded.wert
                """,
                (show_empty_products,),
            )
            conn.execute(
                """
                INSERT INTO einstellungen (schluessel, wert)
                VALUES ('theme_accent', ?)
                ON CONFLICT(schluessel)
                DO UPDATE SET wert = excluded.wert
                """,
                (accent_color.lower(),),
            )
            conn.executemany(
                """
                INSERT INTO einstellungen (schluessel, wert)
                VALUES (?, ?)
                ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert
                """,
                [
                    ("backup_enabled", backup_enabled),
                    ("backup_frequency", backup_frequency),
                    ("backup_time", backup_time),
                    ("backup_weekday", str(backup_weekday)),
                    ("backup_max_backups", str(backup_max_backups)),
                    ("backup_max_age_days", str(backup_max_age_days)),
                    ("default_currency", default_currency),
                    ("checkout_mode_enabled", checkout_mode_enabled),
                    ("host_control_enabled", host_control_enabled),
                    ("display_show_user", display_show_user),
                    ("display_show_booking", display_show_booking),
                    ("display_show_inventory", display_show_inventory),
                    ("display_rotate_seconds", str(display_rotate_seconds)),
                ],
            )

            conn.commit()
            conn.close()

            flash(translate("settings_saved_success", get_language()), "success"); return redirect("/einstellungen")

        setting = conn.execute(
            """
            SELECT wert
            FROM einstellungen
            WHERE schluessel = 'ha_einkaufsliste_aktiv'
            """
        ).fetchone()

        enabled = bool(
            setting
            and str(setting["wert"]).lower()
            in ("1", "true", "yes", "on")
        )

        ha_url_row = conn.execute(
            "SELECT wert FROM einstellungen WHERE schluessel = 'ha_url'"
        ).fetchone()
        ha_url = ha_url_row["wert"] if ha_url_row else ""

        ha_token_row = conn.execute(
            "SELECT wert FROM einstellungen WHERE schluessel = 'ha_token'"
        ).fetchone()
        ha_token = ha_token_row["wert"] if ha_token_row else ""

        row = conn.execute(
            "SELECT wert FROM einstellungen WHERE schluessel='show_empty_products'"
        ).fetchone()

        show_empty_products = (
            True
            if row is None
            else str(row["wert"]).lower() in ("1","true","yes","on")
        )
        accent_color_row = conn.execute(
            """
            SELECT wert
            FROM einstellungen
            WHERE schluessel = 'theme_accent'
            """
        ).fetchone()
        accent_color = (
            accent_color_row["wert"]
            if accent_color_row
            else "#38bdf8"
        )
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent_color):
            accent_color = "#38bdf8"

        default_currency = get_setting("default_currency", "EUR")
        checkout_mode_enabled = get_setting("checkout_mode_enabled", "0") == "1"
        host_control_enabled = get_setting("host_control_enabled", "0") == "1"
        display_show_user = get_setting("display_show_user", "1") == "1"
        display_show_booking = get_setting("display_show_booking", "1") == "1"
        display_show_inventory = get_setting("display_show_inventory", "0") == "1"
        try:
            display_rotate_seconds = int(get_setting("display_rotate_seconds", "10"))
        except ValueError:
            display_rotate_seconds = 10

        conn.close()

        backup_path = get_setting("backup_path", "/data/backups")
        backups = list_backups(backup_path)
        backup_config = backup_schedule()
        update_info = get_update_info()
        update_status = docker_update_status()

        return render_page(
            html_start + """
            <a href="/" style="display:inline-block;margin-bottom:20px;">
                {{ t('back_to_fridge') }}
            </a>

            <h1>⚙️ {{ t("settings") }}</h1>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% for category, message in messages %}
                    <div class="success-message">{{ message }}</div>
                {% endfor %}
            {% endwith %}

            <div class="card" id="updates">
                <h2>🔄 {{ t("software_update") }}</h2>
                <div style="display:grid;gap:10px;margin-bottom:18px;">
                    <div><strong>{{ t("current_version") }}:</strong> {{ current_version }}</div>

                    {% if not update_info.enabled %}
                        <div style="color:#fbbf24;">{{ t("update_checker_disabled") }}</div>
                    {% elif update_info.error %}
                        <div style="color:#fca5a5;">{{ t("update_check_failed") }}</div>
                    {% elif update_info.latest_version %}
                        <div><strong>{{ t("latest_version") }}:</strong> {{ update_info.latest_version }}</div>
                        {% if update_info.update_available %}
                            <div style="color:#fbbf24;font-weight:700;">↑ {{ t("update_available") }}</div>
                            <a href="{{ update_info.release_url }}" target="_blank" rel="noopener noreferrer">
                                {{ t("view_release") }}
                            </a>
                        {% else %}
                            <div style="color:#86efac;font-weight:700;">✓ {{ t("up_to_date") }}</div>
                        {% endif %}
                    {% else %}
                        <div style="opacity:.75;">{{ t("update_not_checked") }}</div>
                    {% endif %}

                    {% if update_info.checked_at %}
                        <div style="opacity:.7;font-size:14px;">
                            {{ t("last_update_check") }}:
                            {{ update_info.checked_at.strftime("%d.%m.%Y %H:%M UTC") }}
                        </div>
                    {% endif %}

                    <div id="update-progress" {% if update_status.status not in ('running', 'failed', 'success') %}hidden{% endif %}>
                        <div style="display:flex;justify-content:space-between;gap:12px;">
                            <strong id="update-phase">{{ t('update_phase_' ~ update_status.phase) }}</strong>
                            <span id="update-percent">{{ update_status.progress }}%</span>
                        </div>
                        <div style="height:10px;background:rgba(255,255,255,.08);border-radius:999px;overflow:hidden;margin-top:8px;">
                            <div id="update-progress-bar" style="height:100%;width:{{ update_status.progress }}%;background:var(--accent);transition:width .35s;"></div>
                        </div>
                        <div id="update-detail" style="opacity:.72;font-size:14px;margin-top:8px;overflow-wrap:anywhere;">{{ update_status.error or update_status.detail }}</div>
                    </div>
                </div>

                {% if update_info.enabled %}
                <div style="display:flex;gap:10px;flex-wrap:wrap;">
                    <form method="post" action="/einstellungen/update-pruefen">
                        <button type="submit" class="button filter">🔍 {{ t("check_for_updates_now") }}</button>
                    </form>
                    {% if update_info.update_available and docker_update_available %}
                    <form method="post" action="/einstellungen/update-installieren"
                          onsubmit="return confirm('{{ t("install_update_confirm") }}');">
                        <button
                            type="submit"
                            class="button plus"
                            {% if docker_update_in_progress %}disabled aria-disabled="true"{% endif %}
                        >
                            {% if docker_update_in_progress %}
                                ⏳ {{ t("update_installing") }}
                            {% else %}
                                ⬆️ {{ t("install_update") }}
                            {% endif %}
                        </button>
                    </form>
                    {% endif %}
                </div>
                {% endif %}
            </div>

            <div class="card">
                <h2>👥 {{ t("user_accounts") }}</h2>
                <p style="color:var(--muted);line-height:1.6;">
                    {{ t("user_accounts_description") }}
                </p>
                <a class="button filter" href="/einstellungen/benutzer">
                    {{ t("manage_user_accounts") }} →
                </a>
            </div>

            <div class="card">
                <h2>🔔 {{ t("pushover_notifications") }}</h2>
                <p style="color:var(--muted);line-height:1.6;">
                    {{ t("pushover_settings_description") }}
                </p>
                <a class="button filter" href="/einstellungen/benachrichtigungen">
                    {{ t("configure_pushover") }} →
                </a>
            </div>

            <div class="card">
                <h2>🖥️ {{ t("system_dashboard") }}</h2>
                <p style="color:var(--muted);line-height:1.6;">
                    {{ t("system_dashboard_desc") }}
                </p>
                <a class="button filter" href="/einstellungen/system">
                    {{ t("open_system_dashboard") }} →
                </a>
            </div>

            <div class="card">
                <h2>📷 {{ t("scanner_diagnostics") }}</h2>
                <p style="color:var(--muted);line-height:1.6;">
                    {{ t("scanner_diagnostics_desc") }}
                </p>
                <a class="button filter" href="/einstellungen/scanner-diagnose">
                    {{ t("open_scanner_diagnostics") }} →
                </a>
            </div>

            <script>
                (function pollUpdateStatus() {
                    fetch("/einstellungen/update-status", {cache: "no-store"})
                        .then(function (response) { return response.json(); })
                        .then(function (data) {
                            const wrapper = document.getElementById("update-progress");
                            if (!wrapper) return;
                            const visible = ["running", "failed", "success"].includes(data.status);
                            wrapper.hidden = !visible;
                            document.getElementById("update-phase").textContent = data.phase_label;
                            document.getElementById("update-percent").textContent = data.progress + "%";
                            document.getElementById("update-progress-bar").style.width = data.progress + "%";
                            document.getElementById("update-detail").textContent = data.error || data.detail || "";
                            if (data.status === "success" && data.reload) window.location.reload();
                        })
                        .catch(function () {
                            const detail = document.getElementById("update-detail");
                            if (detail) detail.textContent = "{{ t('update_reconnecting') }}";
                        })
                        .finally(function () { window.setTimeout(pollUpdateStatus, 2000); });
                })();
            </script>

            <div class="card">
                <h2>{{ t("home_assistant") }}</h2>

                <form method="post">
                <div style="
                    margin-bottom:24px;
                    padding:20px;
                    border-radius:14px;
                    background:rgba(255,255,255,0.035);
                    border:1px solid rgba(255,255,255,0.08);
                ">
                    <label for="language" style="
                        display:block;
                        margin-bottom:10px;
                        font-weight:700;
                    ">
                        🌐 {{ t("language") }}
                    <select
                        id="language"
                        name="language"
                        onchange="window.location.href='/sprache/' + this.value"
                        style="
                            width:100%;
                            max-width:420px;
                            padding:12px 14px;
                            border-radius:10px;
                            font-size:16px;
                            cursor:pointer;
                        "
                    >
                        
                        {% for code, display_name in available_languages %}
                        <option value="{{ code }}" {% if lang == code %}selected{% endif %}>
                            {{ display_name }}
                        </option>
                        {% endfor %}

                    </select>

                    <div style="margin-top:22px;">
                        <label for="theme-accent" style="
                            display:block;
                            margin-bottom:10px;
                            font-weight:700;
                        ">
                            ◉ {{ t("accent_color") }}
                        </label>
                        <div style="
                            display:flex;
                            align-items:center;
                            gap:14px;
                            flex-wrap:wrap;
                        ">
                            <input
                                type="color"
                                id="theme-accent"
                                name="theme_accent"
                                value="{{ accent_color }}"
                                aria-label="{{ t('accent_color') }}"
                                oninput="document.documentElement.style.setProperty('--accent', this.value); document.documentElement.style.setProperty('--accent-strong', this.value);"
                                style="
                                    width:64px;
                                    height:48px;
                                    padding:4px;
                                    margin:0;
                                    cursor:pointer;
                                "
                            >
                            <div style="color:var(--muted);line-height:1.5;">
                                {{ t("accent_color_desc") }}
                            </div>
                        </div>
                    </div>
                </div>

                    <div style="
                        display:flex;
                        justify-content:space-between;
                        align-items:center;
                        gap:20px;
                        flex-wrap:wrap;
                    ">
                        <div style="flex:1;min-width:240px;">
                            <strong>
                                {{ t("shopping_sync") }}
                            </strong>

                            <div style="
                                margin-top:8px;
                                opacity:0.75;
                                line-height:1.5;
                            ">
                                {{ t("shopping_sync_desc") }}
                            </div>
                        </div>

                        <label style="
                            display:flex;
                            align-items:center;
                            gap:10px;
                            cursor:pointer;
                        ">
                            <input
                                type="checkbox"
                                name="ha_einkaufsliste_aktiv"
                                {% if enabled %}checked{% endif %}
                                style="
                                    width:22px;
                                    height:22px;
                                    accent-color:#4caf50;
                                "
                            >
                            <span>
                                {% if enabled %}
                                    {{ t("active") }}
                                {% else %}
                                    {{ t("disabled") }}
                                {% endif %}
                            </span>
                        </label>
                    </div>
                    <div style="margin-top:24px; display:grid; gap:16px;">
                        <div>
                            <label for="ha_url"><strong>{{ t("home_assistant_url") }}</strong></label>
                            <input
                                type="text"
                                id="ha_url"
                                name="ha_url"
                                value="{{ ha_url }}"
                                placeholder="{{ t('home_assistant_url_placeholder') }}"
                                style="width:100%; margin-top:8px;"
                            >
                        </div>

                        <div>
                            <label for="ha_token"><strong>{{ t("home_assistant_token") }}</strong></label>
                            <input
                                type="password"
                                id="ha_token"
                                name="ha_token"
                                value="{{ ha_token }}"
                                placeholder="{{ t('home_assistant_token_placeholder') }}"
                                style="width:100%; margin-top:8px;"
                            >
                        </div>
                    </div>


                    <div style="
                        display:flex;
                        justify-content:space-between;
                        align-items:center;
                        gap:20px;
                        flex-wrap:wrap;
                        margin-top:24px;
                        margin-bottom:24px;
                    ">
                        <div style="flex:1;min-width:240px;">
                            <strong>{{ t("show_empty_products") }}</strong>

                            <div style="
                                margin-top:8px;
                                opacity:0.75;
                                line-height:1.5;
                            ">
                                {{ t("show_empty_products_desc") }}
                            </div>
                        </div>

                        <label style="
                            display:flex;
                            align-items:center;
                            gap:10px;
                            cursor:pointer;
                        ">
                            <input
                                type="checkbox"
                                name="show_empty_products"
                                {% if show_empty_products %}checked{% endif %}
                                style="
                                    width:22px;
                                    height:22px;
                                    accent-color:#4caf50;
                                "
                            >

                            <span>
                                {% if show_empty_products %}
                                    {{ t("active") }}
                                {% else %}
                                    {{ t("disabled") }}
                                {% endif %}
                            </span>
                        </label>
                    </div>

                    <hr style="margin:32px 0;">

                    <h3>🧾 {{ t("checkout_and_currency") }}</h3>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-top:16px;">
                        <label style="display:grid;gap:8px;">
                            <strong>{{ t("default_currency") }}</strong>
                            <select name="default_currency">
                                {% for code, label in currency_choices %}
                                <option value="{{ code }}" {% if code == default_currency %}selected{% endif %}>{{ label }}</option>
                                {% endfor %}
                            </select>
                            <span style="color:var(--muted);font-size:.9rem;">{{ t("default_currency_desc") }}</span>
                        </label>
                        <label style="display:flex;gap:12px;align-items:flex-start;">
                            <input type="checkbox" name="checkout_mode_enabled" {% if checkout_mode_enabled %}checked{% endif %}>
                            <span><strong>{{ t("enable_checkout_home") }}</strong><br><small style="color:var(--muted);">{{ t("enable_checkout_home_desc") }}</small></span>
                        </label>
                        <label style="display:flex;gap:12px;align-items:flex-start;">
                            <input type="checkbox" name="host_control_enabled" {% if host_control_enabled %}checked{% endif %}>
                            <span><strong>{{ t("enable_host_controls") }}</strong><br><small style="color:var(--muted);">{{ t("enable_host_controls_desc") }}</small></span>
                        </label>
                    </div>

                    <hr style="margin:32px 0;">

                    <h3>🖥️ {{ t("display_options") }}</h3>
                    <p>{{ t("display_options_desc") }}</p>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;">
                        <label><input type="checkbox" name="display_show_user" {% if display_show_user %}checked{% endif %}> {{ t("display_option_user") }}</label>
                        <label><input type="checkbox" name="display_show_booking" {% if display_show_booking %}checked{% endif %}> {{ t("display_option_booking") }}</label>
                        <label><input type="checkbox" name="display_show_inventory" {% if display_show_inventory %}checked{% endif %}> {{ t("display_option_inventory") }}</label>
                        <label style="display:grid;gap:6px;">{{ t("display_rotate_seconds") }}
                            <input type="number" min="3" max="120" name="display_rotate_seconds" value="{{ display_rotate_seconds }}">
                        </label>
                    </div>

                    <hr style="margin:32px 0;">

                    <h3>💾 {{ t("backup") }}</h3>

                    <div id="backup" style="display:grid;gap:16px;margin-top:16px;">
                        <label style="display:flex;align-items:center;gap:10px;">
                            <input type="checkbox" name="backup_enabled" {% if backup_config.enabled %}checked{% endif %}>
                            <strong>{{ t("automatic_backups") }}</strong>
                        </label>
                        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;">
                            <label>{{ t("backup_frequency") }}
                                <select name="backup_frequency" style="width:100%;margin-top:6px;">
                                    {% for value in ('6h','12h','daily','weekly') %}
                                    <option value="{{ value }}" {% if backup_config.frequency == value %}selected{% endif %}>{{ t("backup_frequency_" ~ value) }}</option>
                                    {% endfor %}
                                </select>
                            </label>
                            <label>{{ t("backup_time") }}
                                <input type="time" name="backup_time" value="{{ backup_config.time }}" style="width:100%;margin-top:6px;">
                            </label>
                            <label>{{ t("backup_weekday") }}
                                <select name="backup_weekday" style="width:100%;margin-top:6px;">
                                    {% for day in range(7) %}<option value="{{ day }}" {% if backup_config.weekday == day %}selected{% endif %}>{{ t("weekday_" ~ day) }}</option>{% endfor %}
                                </select>
                            </label>
                        </div>
                        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;">
                            <label>{{ t("backup_max_count") }}
                                <input type="number" min="1" max="365" name="backup_max_backups" value="{{ backup_config.max_backups }}" style="width:100%;margin-top:6px;">
                            </label>
                            <label>{{ t("backup_max_age") }}
                                <input type="number" min="0" max="3650" name="backup_max_age_days" value="{{ backup_config.max_age_days }}" style="width:100%;margin-top:6px;">
                            </label>
                        </div>
                        <div style="color:var(--muted);font-size:.9rem;">
                            {% if backup_config.next_backup %}<div>{{ t("next_backup") }}: {{ backup_config.next_backup.strftime("%d.%m.%Y %H:%M") }}</div>{% endif %}
                            {% if backup_config.last_backup %}<div>{{ t("last_backup") }}: {{ backup_config.last_backup.strftime("%d.%m.%Y %H:%M:%S") }}</div>{% endif %}
                            {% if backup_config.last_status == 'failed' %}<div style="color:#fca5a5;">{{ t("backup_last_failed") }}: {{ backup_config.last_error }}</div>{% endif %}
                        </div>
                    </div>

                    <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:16px;">
                        <button
                            type="submit"
                            class="button filter"
                            formaction="/settings/backup/create"
                            formmethod="post"
                        >
                            📦 {{ t("create_backup_now") }}
                        </button>
                    </div>


                    {% if backups %}
                    <div id="backup-list" style="margin-top:24px;">
                        <h4>{{ t("available_backups") }}</h4>

                        <table class="responsive-table" style="width:100%;margin-top:10px;">
                            <tr class="table-head">
                                <th>{{ t("filename") }}</th>
                                <th>{{ t("size") }}</th>
                                <th>{{ t("created") }}</th>
                                <th>{{ t("download") }}</th>
                            </tr>

                            {% for backup in backups %}
                            <tr>
                                <td class="mobile-primary" data-label="{{ t('filename') }}">{{ backup.filename }}</td>
                                <td data-label="{{ t('size') }}">{{ "%.1f"|format(backup.size_bytes/1024/1024) }} MB</td>
                                <td data-label="{{ t('created') }}">{{ backup.created_at }}</td>
                                <td class="mobile-actions" data-label="{{ t('download') }}">
                                    <a class="button filter" href="/settings/backup/download/{{ backup.filename }}">
                                        ⬇️ {{ t("download") }}
                                    </a>
                                </td>
                                <td class="mobile-actions" data-label="{{ t('restore') }}">
                                    <button
                                        type="submit"
                                        class="button warning"
                                        formaction="/settings/backup/restore/{{ backup.filename }}"
                                        formmethod="post"
                                        onclick="return confirm('{{ t("restore_backup_confirm") }}');">
                                        ♻️ {{ t("restore") }}
                                    </button>
                                </td>
                                <td class="mobile-actions" data-label="{{ t('delete') }}">
                                    <button
                                        type="submit"
                                        class="button danger"
                                        formaction="/settings/backup/delete/{{ backup.filename }}"
                                        formmethod="post"
                                        onclick="return confirm('{{ t("delete_backup_confirm") }}');">
                                        🗑️ {{ t("delete") }}
                                    </button>
                                </td>
                            </tr>
                            {% endfor %}
                        </table>
                    </div>
                    {% endif %}

                    {% if backups %}
                    <div style="margin-top:24px;">
                        
                    </div>
                    {% endif %}

                    <div style="
                        margin-top:24px;
                        display:flex;
                        gap:10px;
                        flex-wrap:wrap;
                    ">
                        <button type="submit" class="button filter">
                            💾 {{ t("save") }}
                        </button>

                        <a class="button filter" href="/">
                            ← {{ t("back") }}
                        </a>
                    </div>
                </form>
            </div>
            """,
            enabled=enabled,
            ha_url=ha_url,
            ha_token=ha_token,
            show_empty_products=show_empty_products,
            backups=backups,
            backup_config=backup_config,
            available_languages=[
                (
                    code,
                    {
                        "de": "🇩🇪 Deutsch",
                        "en": "🇬🇧 English",
                        "fr": "🇫🇷 Français",
                    }.get(code, code.upper()),
                )
                for code in available_languages()
            ],
            update_info=update_info,
            current_version=current_version,
            docker_update_available=docker_update_available(),
            docker_update_in_progress=docker_update_in_progress(),
            update_status=update_status,
            accent_color=accent_color,
            currency_choices=CURRENCY_CHOICES,
            default_currency=default_currency,
            checkout_mode_enabled=checkout_mode_enabled,
            host_control_enabled=host_control_enabled,
            display_show_user=display_show_user,
            display_show_booking=display_show_booking,
            display_show_inventory=display_show_inventory,
            display_rotate_seconds=display_rotate_seconds,
        )

    @settings_bp.route(
        "/einstellungen/benachrichtigungen",
        methods=["GET", "POST"],
    )
    def notification_settings():
        require_settings_admin()

        if request.method == "POST":
            user_key = request.form.get("pushover_user", "").strip()
            app_token = request.form.get("pushover_token", "").strip()
            clear_credentials = request.form.get("clear_credentials") == "1"

            key_pattern = r"[A-Za-z0-9]{20,64}"
            if user_key and not re.fullmatch(key_pattern, user_key):
                flash(
                    translate("pushover_invalid_user_key", get_language()),
                    "error",
                )
                return redirect("/einstellungen/benachrichtigungen")
            if app_token and not re.fullmatch(key_pattern, app_token):
                flash(
                    translate("pushover_invalid_app_token", get_language()),
                    "error",
                )
                return redirect("/einstellungen/benachrichtigungen")
            stored_user = bool(get_setting("pushover_user_encrypted", ""))
            stored_token = bool(get_setting("pushover_token_encrypted", ""))
            if (
                not clear_credentials
                and (user_key or app_token)
                and bool(user_key or stored_user) != bool(app_token or stored_token)
            ):
                flash(
                    translate("pushover_credentials_incomplete", get_language()),
                    "error",
                )
                return redirect("/einstellungen/benachrichtigungen")

            save_pushover_credentials(
                user_key=user_key or None,
                app_token=app_token or None,
                clear=clear_credentials,
            )
            set_setting(
                "pushover_enabled",
                "1" if request.form.get("pushover_enabled") == "on" else "0",
            )
            for event, setting_key in PUSHOVER_EVENTS.items():
                set_setting(
                    setting_key,
                    "1" if request.form.get(f"event_{event}") == "on" else "0",
                )

            flash(
                translate("pushover_settings_saved", get_language()),
                "success",
            )
            return redirect("/einstellungen/benachrichtigungen")

        configured, credential_source = pushover_configured()
        enabled = get_setting("pushover_enabled", "0").lower() in {
            "1", "true", "yes", "on"
        }
        selected_events = {
            event: get_setting(setting_key, "0").lower()
            in {"1", "true", "yes", "on"}
            for event, setting_key in PUSHOVER_EVENTS.items()
        }

        return render_page(
            html_start + """
            <a class="zurueck" href="/einstellungen">
                ← {{ t("back_to_settings") }}
            </a>
            <div class="page-hero">
                <div>
                    <div class="eyebrow">Pushover</div>
                    <h1>🔔 {{ t("pushover_notifications") }}</h1>
                    <p>{{ t("pushover_settings_description") }}</p>
                </div>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% for category, message in messages %}
                    <div class="success-message">{{ message }}</div>
                {% endfor %}
            {% endwith %}

            <div class="card">
                <h2>{{ t("pushover_access_data") }}</h2>
                <p style="color:var(--muted);line-height:1.6;">
                    {{ t("pushover_secret_notice") }}
                </p>
                <div style="margin:14px 0;color:{% if configured %}#86efac{% else %}#fbbf24{% endif %};font-weight:700;">
                    {% if configured %}
                        ✓ {{ t("pushover_configured") }}
                        {% if credential_source == "environment" %}
                            ({{ t("legacy_env_configuration") }})
                        {% endif %}
                    {% else %}
                        {{ t("pushover_not_configured") }}
                    {% endif %}
                </div>

                <form method="post" style="display:grid;gap:18px;">
                    <label style="display:flex;gap:12px;align-items:center;">
                        <input type="checkbox" name="pushover_enabled"
                               {% if enabled %}checked{% endif %}>
                        <strong>{{ t("enable_pushover") }}</strong>
                    </label>

                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;">
                        <label>
                            <strong>{{ t("pushover_user_key") }}</strong>
                            <input type="password" name="pushover_user"
                                   autocomplete="new-password"
                                   placeholder="{{ t('leave_blank_to_keep') }}"
                                   style="width:100%;margin-top:8px;">
                        </label>
                        <label>
                            <strong>{{ t("pushover_app_token") }}</strong>
                            <input type="password" name="pushover_token"
                                   autocomplete="new-password"
                                   placeholder="{{ t('leave_blank_to_keep') }}"
                                   style="width:100%;margin-top:8px;">
                        </label>
                    </div>

                    <h3 style="margin-bottom:0;">{{ t("notify_me_for") }}</h3>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;">
                        {% for event, label_key in event_labels.items() %}
                        <label style="display:flex;gap:10px;align-items:center;padding:12px;border:1px solid var(--border);border-radius:12px;">
                            <input type="checkbox" name="event_{{ event }}"
                                   {% if selected_events[event] %}checked{% endif %}>
                            <span>{{ t(label_key) }}</span>
                        </label>
                        {% endfor %}
                    </div>

                    {% if configured %}
                    <label style="display:flex;gap:10px;align-items:center;color:#fca5a5;">
                        <input type="checkbox" name="clear_credentials" value="1">
                        <span>{{ t("delete_pushover_credentials") }}</span>
                    </label>
                    {% endif %}

                    <div style="display:flex;gap:10px;flex-wrap:wrap;">
                        <button class="plus" type="submit">{{ t("save") }}</button>
                    </div>
                </form>

                {% if configured %}
                <form method="post" action="/einstellungen/benachrichtigungen/test"
                      style="margin-top:14px;">
                    <button class="filter" type="submit">
                        🔔 {{ t("send_test_notification") }}
                    </button>
                </form>
                {% endif %}
            </div>
            """,
            configured=configured,
            credential_source=credential_source,
            enabled=enabled,
            selected_events=selected_events,
            event_labels={
                "low_stock": "pushover_low_stock",
                "out_of_stock": "pushover_out_of_stock",
                "removed": "pushover_removed",
                "restocked": "pushover_restocked",
                "unknown_barcode": "pushover_unknown_barcode",
                "scan_blocked": "pushover_scan_blocked",
            },
        )

    @settings_bp.post("/einstellungen/benachrichtigungen/test")
    def test_notification():
        require_settings_admin()
        success, _ = send_pushover(
            None,
            translate("pushover_test_title", get_language()),
            translate("pushover_test_message", get_language()),
            force=True,
        )
        flash(
            translate(
                "pushover_test_sent" if success else "pushover_test_failed",
                get_language(),
            ),
            "success" if success else "error",
        )
        return redirect("/einstellungen/benachrichtigungen")

    @settings_bp.get("/einstellungen/system")
    def system_dashboard():
        status = get_system_status()
        return render_page(
            html_start + """
            <a class="zurueck" href="/einstellungen">
                ← {{ t("back_to_settings") }}
            </a>

            <div style="
                display:flex;
                align-items:flex-start;
                justify-content:space-between;
                gap:16px;
                flex-wrap:wrap;
                margin-bottom:22px;
            ">
                <div>
                    <div style="
                        color:var(--accent);
                        font-size:.78rem;
                        font-weight:800;
                        letter-spacing:.14em;
                        text-transform:uppercase;
                        margin-bottom:8px;
                    ">{{ t("live_system_status") }}</div>
                    <h1 style="margin:0;">🖥️ {{ t("system_dashboard") }}</h1>
                    <p style="color:var(--muted);margin:10px 0 0;">
                        {{ t("system_dashboard_desc") }}
                    </p>
                </div>
                <a class="button filter" href="/einstellungen/system">
                    ↻ {{ t("refresh") }}
                </a>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% for category, message in messages %}
                    <div class="success-message">{{ message }}</div>
                {% endfor %}
            {% endwith %}

            <div class="stats" style="
                grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
            ">
                <div class="stat">
                    <div style="color:var(--muted);">{{ t("cpu_temperature") }}</div>
                    <div class="stat-zahl" style="margin-top:8px;">
                        {% if status.temperature is not none %}
                            {{ status.temperature }} °C
                        {% else %}
                            {{ t("not_available") }}
                        {% endif %}
                    </div>
                </div>
                <div class="stat">
                    <div style="color:var(--muted);">{{ t("memory_usage") }}</div>
                    <div class="stat-zahl" style="margin-top:8px;">
                        {% if status.memory %}
                            {{ status.memory.percent }}%
                        {% else %}
                            {{ t("not_available") }}
                        {% endif %}
                    </div>
                    {% if status.memory %}
                    <div style="color:var(--muted);margin-top:6px;">
                        {{ status.memory.used }} / {{ status.memory.total }}
                    </div>
                    {% endif %}
                </div>
                <div class="stat">
                    <div style="color:var(--muted);">{{ t("storage_usage") }}</div>
                    <div class="stat-zahl" style="margin-top:8px;">
                        {% if status.disk %}
                            {{ status.disk.percent }}%
                        {% else %}
                            {{ t("not_available") }}
                        {% endif %}
                    </div>
                    {% if status.disk %}
                    <div style="color:var(--muted);margin-top:6px;">
                        {{ status.disk.free }} {{ t("free") }}
                    </div>
                    {% endif %}
                </div>
                <div class="stat">
                    <div style="color:var(--muted);">{{ t("system_uptime") }}</div>
                    <div class="stat-zahl" style="margin-top:8px;font-size:1.65rem;">
                        {{ status.uptime or t("not_available") }}
                    </div>
                </div>
            </div>

            <div class="card" style="margin-top:18px;">
                <h2>⏻ {{ t("host_power_controls") }}</h2>
                {% if host_control_enabled %}
                <p>{{ t("host_power_controls_warning") }}</p>
                <form method="post" action="/einstellungen/system/aktion"
                      style="display:flex;gap:12px;align-items:end;flex-wrap:wrap;">
                    <label style="display:grid;gap:6px;min-width:230px;">
                        {{ t("admin_password_confirmation") }}
                        <input type="password" name="password" required autocomplete="current-password">
                    </label>
                    <button class="filter" name="action" value="reboot" type="submit"
                            onclick="return confirm('{{ t("reboot_confirm") }}');">
                        ↻ {{ t("reboot_system") }}
                    </button>
                    <button class="minus" name="action" value="poweroff" type="submit"
                            onclick="return confirm('{{ t("poweroff_confirm") }}');">
                        ⏻ {{ t("power_off_system") }}
                    </button>
                </form>
                {% else %}
                <p>{{ t("host_power_controls_disabled") }}</p>
                {% endif %}
            </div>

            <div style="
                display:grid;
                grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));
                gap:18px;
            ">
                <div class="card" style="margin:0;">
                    <h2 style="margin-top:0;">🐳 {{ t("container_status") }}</h2>
                    {% if not status.containers.available %}
                        <div style="color:var(--muted);">
                            {{ t("docker_status_unavailable") }}
                        </div>
                    {% elif not status.containers.containers %}
                        <div style="color:var(--muted);">
                            {{ t("no_app_containers") }}
                        </div>
                    {% else %}
                        <div style="display:grid;gap:12px;">
                        {% for container in status.containers.containers %}
                            <div style="
                                display:flex;
                                align-items:flex-start;
                                justify-content:space-between;
                                gap:12px;
                                padding:14px;
                                border:1px solid var(--border);
                                border-radius:12px;
                                background:rgba(255,255,255,.025);
                            ">
                                <div style="min-width:0;">
                                    <strong style="overflow-wrap:anywhere;">
                                        {{ container.name }}
                                    </strong>
                                    <div style="
                                        color:var(--muted);
                                        font-size:.82rem;
                                        margin-top:5px;
                                    ">{{ container.status }}</div>
                                </div>
                                <span style="
                                    color:{% if container.state == 'running' %}var(--success){% else %}var(--danger){% endif %};
                                    font-weight:800;
                                    white-space:nowrap;
                                ">
                                    ● {{ t("running") if container.state == "running" else t("stopped") }}
                                </span>
                            </div>
                        {% endfor %}
                        </div>
                    {% endif %}
                </div>

                <div class="card" style="margin:0;">
                    <h2 style="margin-top:0;">📟 {{ t("device_status") }}</h2>
                    <div style="display:grid;gap:14px;">
                        <div>
                            <div style="color:var(--muted);">{{ t("camera") }}</div>
                            <strong>
                                {% if status.containers.camera and status.containers.camera.configured and status.containers.camera.running %}
                                    <span style="color:var(--success);">● {{ t("ready") }}</span>
                                {% elif status.containers.camera %}
                                    <span style="color:var(--danger);">● {{ t("not_ready") }}</span>
                                {% else %}
                                    {{ t("not_available") }}
                                {% endif %}
                            </strong>
                        </div>
                        <div>
                            <div style="color:var(--muted);">{{ t("database_size") }}</div>
                            <strong>{{ status.database.size or t("not_available") }}</strong>
                        </div>
                        <div>
                            <div style="color:var(--muted);">{{ t("system_load") }}</div>
                            <strong>{{ status.load_average or t("not_available") }}</strong>
                        </div>
                    </div>
                </div>

                <div class="card" style="margin:0;">
                    <h2 style="margin-top:0;">ℹ️ {{ t("system_information") }}</h2>
                    <div style="
                        display:grid;
                        grid-template-columns:auto 1fr;
                        gap:10px 18px;
                        overflow-wrap:anywhere;
                    ">
                        <span style="color:var(--muted);">{{ t("hostname") }}</span>
                        <strong>{{ status.hostname }}</strong>
                        <span style="color:var(--muted);">{{ t("architecture") }}</span>
                        <strong>{{ status.architecture }}</strong>
                        <span style="color:var(--muted);">{{ t("kernel") }}</span>
                        <strong>{{ status.kernel }}</strong>
                        <span style="color:var(--muted);">{{ t("app_version") }}</span>
                        <strong>{{ current_version }}</strong>
                    </div>
                </div>
            </div>

            <div style="
                color:var(--muted);
                font-size:.82rem;
                margin-top:18px;
                text-align:center;
            ">
                {{ t("system_status_updated") }}:
                {{ status.checked_at.strftime("%d.%m.%Y %H:%M:%S UTC") }}
            </div>

            <script>
                window.setTimeout(function () {
                    window.location.reload();
                }, 15000);
            </script>
            """,
            status=status,
            current_version=current_version,
            host_control_enabled=get_setting("host_control_enabled", "0") == "1",
        )

    @settings_bp.post("/einstellungen/system/aktion")
    def system_action():
        require_settings_admin()
        if get_setting("host_control_enabled", "0") != "1":
            abort(403)
        action = request.form.get("action", "")
        if action not in {"reboot", "poweroff"}:
            abort(400)
        if not verify_control_password(request.form.get("password", "")):
            flash(translate("control_password_invalid", get_language()), "error")
            return redirect("/einstellungen/system")
        try:
            request_host_action(action)
        except (KeyError, OSError, RuntimeError, ValueError):
            flash(translate("host_action_failed", get_language()), "error")
            return redirect("/einstellungen/system")
        return (
            translate(
                "system_rebooting" if action == "reboot" else "system_powering_off",
                get_language(),
            ),
            202,
        )

    @settings_bp.post("/einstellungen/update-pruefen")
    def update_pruefen():
        require_settings_admin()
        update_info = get_update_info(force=True)
        message_key = (
            "update_check_failed"
            if update_info["error"]
            else "update_check_completed"
        )
        flash(translate(message_key, get_language()), "success")
        return redirect("/einstellungen#updates")

    @settings_bp.post("/einstellungen/update-installieren")
    def update_installieren():
        require_settings_admin()
        update_info = get_update_info(force=True)
        if update_info["error"] or not update_info["update_available"]:
            flash(
                translate("no_installable_update", get_language()),
                "success",
            )
            return redirect("/einstellungen#updates")

        try:
            started = start_docker_update(update_info["latest_version"])
            flash(
                translate(
                    "update_install_started"
                    if started
                    else "update_install_already_running",
                    get_language(),
                ),
                "success",
            )
        except (OSError, RuntimeError):
            flash(
                translate("update_install_failed", get_language()),
                "success",
            )

        return redirect("/einstellungen#updates")

    @settings_bp.get("/einstellungen/update-status")
    def update_status_api():
        require_settings_admin()
        status = docker_update_status()
        language = get_language()
        return jsonify({
            **status,
            "phase_label": translate(
                f"update_phase_{status['phase']}",
                language,
            ),
            "reload": status["status"] == "success"
            and current_version != status.get("target", "").lstrip("v"),
        })

    return settings_bp
