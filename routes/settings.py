import re

from flask import Blueprint, flash, redirect, request
from translation import translate
from utils.render import get_language

from backup import list_backups
from database import get_setting
from utils.db import get_db
from docker_update import (
    docker_update_available,
    docker_update_in_progress,
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

    @settings_bp.route("/einstellungen", methods=["GET", "POST"])
    def einstellungen():
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
            accent_color = request.form.get(
                "theme_accent",
                "#38bdf8",
            ).strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent_color):
                accent_color = "#38bdf8"

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

        conn.close()

        backup_path = get_setting("backup_path", "/data/backups")
        backups = list_backups(backup_path)
        update_info = get_update_info()

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

                    {% if docker_update_in_progress %}
                        <div
                            style="color:#fbbf24;font-weight:700;"
                            role="status"
                            aria-live="polite"
                        >
                            ⏳ {{ t("update_install_running") }}
                        </div>
                    {% endif %}
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

            {% if docker_update_in_progress %}
            <script>
                window.setTimeout(function () {
                    window.location.reload();
                }, 5000);
            </script>
            {% endif %}

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

                    <h3>💾 {{ t("backup") }}</h3>

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
                    <div id="backup" style="margin-top:24px;">
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
            accent_color=accent_color,
        )

    @settings_bp.post("/einstellungen/update-pruefen")
    def update_pruefen():
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
        update_info = get_update_info(force=True)
        if update_info["error"] or not update_info["update_available"]:
            flash(
                translate("no_installable_update", get_language()),
                "success",
            )
            return redirect("/einstellungen#updates")

        try:
            started = start_docker_update()
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

    return settings_bp
