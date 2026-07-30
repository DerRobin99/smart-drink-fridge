from flask import Blueprint, flash, redirect, request
from translation import translate
from utils.render import get_language

from backup import list_backups
from database import get_setting
from utils.db import get_db


def create_settings_blueprint(
    render_page,
    html_start,
    available_languages,
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

        conn.close()

        backup_path = get_setting("backup_path", "/data/backups")
        backups = list_backups(backup_path)

        return render_page(
            html_start + """
            <a href="/" style="display:inline-block;margin-bottom:20px;">
                {{ t('back_to_fridge') }}
            </a>

            <h1>⚙️ {{ t("settings") }}</h1>

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
                    </label>

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
                        {% with messages = get_flashed_messages(with_categories=true) %}
      {% for category, message in messages %}
        <div class="success-message">{{ message }}</div>
      {% endfor %}
    {% endwith %}

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
        )

    return settings_bp
