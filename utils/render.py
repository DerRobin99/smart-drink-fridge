from flask import render_template_string


_get_language_callback = None
_get_update_info_callback = None
_translations = {}
_current_version = ""


def configure_rendering(
    get_language_callback,
    get_update_info_callback,
    translations,
    current_version,
):
    global _get_language_callback
    global _get_update_info_callback
    global _translations
    global _current_version

    _get_language_callback = get_language_callback
    _get_update_info_callback = get_update_info_callback
    _translations = translations
    _current_version = current_version


def get_language():
    if _get_language_callback is None:
        raise RuntimeError("Rendering wurde noch nicht konfiguriert.")

    return _get_language_callback()


def get_update_info():
    if _get_update_info_callback is None:
        raise RuntimeError("Rendering wurde noch nicht konfiguriert.")

    return _get_update_info_callback()


HTML_START = """
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title></title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #111827;
            color: white;
            max-width: 1100px;
            margin: auto;
            padding: 20px;
        }

        h1 {
            color: #60a5fa;
        }

        a {
            color: #60a5fa;
            text-decoration: none;
        }

        a:hover {
            text-decoration: underline;
        }

        .card {
            background: #1f2937;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }

        .stat {
            background: #374151;
            padding: 15px;
            border-radius: 10px;
        }

        .stat-zahl {
            font-size: 28px;
            font-weight: bold;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #374151;
        }

        input {
            padding: 10px;
            margin: 5px;
            border-radius: 6px;
            border: none;
        }

        button, .button {
            padding: 8px 14px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            display: inline-block;
            text-decoration: none;
        }

        .plus {
            background: #22c55e;
            color: white;
        }

        .minus {
            background: #ef4444;
            color: white;
        }

        .filter {
            background: #374151;
            color: white;
            margin: 3px;
        }

        .filter-aktiv {
            background: #2563eb;
            color: white;
        }

        .bestand {
            font-size: 24px;
            font-weight: bold;
        }

        .aktionen {
            display: flex;
            gap: 8px;
        }

        .leer {
            color: #ef4444;
            font-weight: bold;
        }

        .zurueck {
            display: inline-block;
            margin-bottom: 20px;
        }
    
.success-message {
    background: #d1fae5;
    color: #065f46;
    border: 1px solid #10b981;
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 15px;
}

</style>
</head>
<body>
"""


INDEX_HTML = HTML_START + """
<h1>🥤 {{ t("home") }}</h1>

<div style="margin-bottom: 20px;">
    <a
        class="button filter"
        href="/statistik"
    >
        📊 {{ t("statistics") }}
    </a>

    <a
        class="button filter"
        href="/barcode"
    >
        {{ t('barcode_add') }}
    </a>

    <a
        class="button filter"
        href="/einstellungen"
    >
        ⚙️ {{ t("settings") }}
    </a>
</div>

<div class="card">
    <h2>{{ t('current_stock') }}</h2>

    <table>
        <tr>
            <th>{{ t("manufacturer") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("packaging") }}</th>
            <th>{{ t("barcodes") }}</th>
            <th>{{ t("stock") }}</th>
            <th>{{ t("change") }}</th>
        </tr>

        {% for p in produkte %}
        <tr>
            <td>
                {% set logo = brand_logo(p.marke) %}
                <span style="display:inline-flex;width:70px;height:28px;align-items:center;justify-content:center;vertical-align:middle;margin-right:8px;">
                    {% if logo %}
                        <img src="{{ logo }}" alt="" style="max-height:28px;max-width:70px;object-fit:contain;" onerror="this.style.display='none'">
                    {% endif %}
                </span>
                {{ p.marke or "—" }}
            </td>

            <td>
                <a href="/produkt/{{ p.id }}">
                    {{ p.name }}
                </a>
            </td>

            <td>
                {{ p.verpackungsinfo or "—" }}
            </td>

            <td>{{ p.barcode_count }} Barcode{% if p.barcode_count != 1 %}s{% endif %}</td>

            <td class="bestand">
                {% if p.bestand == 0 %}
                    <span class="leer">{{ t("empty") }}</span>
                {% else %}
                    {{ p.bestand }}
                {% endif %}
            </td>

            <td>
                <div class="aktionen">
                    <form method="post" action="/bestand/{{ p.id }}/minus">
                        <button class="minus" type="submit">−1</button>
                    </form>

                    <form method="post" action="/bestand/{{ p.id }}/plus">
                        <button class="plus" type="submit">+1</button>
                    </form>
                </div>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>

<div class="card">
    <h2>{{ t("last_bookings") }}</h2>

    <table>
        <tr>
            <th>{{ t("time") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("change") }}</th>
            <th>{{ t("stock") }}</th>
            <th>{{ t("source") }}</th>
        </tr>

        {% for b in buchungen %}
        <tr>
            <td>{{ b.zeitpunkt }}</td>

            <td>
                <a href="/produkt/{{ b.produkt_id }}">
                    {{ b.produkt }}
                </a>
            </td>

            <td>
                {% if b.menge is not none %}
                    {% if b.menge > 0 %}+{% endif %}{{ b.menge }}
                {% else %}
                    {{ booking_action(b.aktion) }}
                {% endif %}
            </td>

            <td>
                {% if b.bestand_nachher is not none %}
                    {{ b.bestand_nachher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>{{ b.quelle or "—" }}</td>
        </tr>
        {% endfor %}
    </table>
</div>

</body>
</html>
"""


def render_page(template, **context):
    lang = get_language()

    context["lang"] = lang
    context["update_info"] = get_update_info()
    context["current_version"] = _current_version

    action_translation_keys = {
        "Anfangsbestand": "booking_initial_stock",
        "Eingelagert": "booking_stocked",
        "Manuell eingelagert": "booking_stocked",
        "Manuell entnommen": "booking_removed_manually",
        "Scanner-Buchung storniert": "booking_scanner_undone",
    }

    def booking_action(action):
        key = action_translation_keys.get(action)

        if not key:
            return action

        return _translations.get(lang, {}).get(key, action)

    context["booking_action"] = booking_action

    def format_money(cents, currency):
        if cents is None:
            return "—"

        cents = int(cents)
        sign = "-" if cents < 0 else ""
        absolute = abs(cents)
        separator = "," if lang in ("de", "fr") else "."

        return (
            f"{sign}{absolute // 100}"
            f"{separator}{absolute % 100:02d} "
            f"{currency or 'EUR'}"
        )

    context["format_money"] = format_money

    html = render_template_string(
        template,
        t=lambda key: _translations.get(lang, {}).get(key, key),
        **context
    )

    return html


DETAIL_HTML = HTML_START + """
<a class="zurueck" href="/">{{ t('back_to_fridge') }}</a>

{% set logo = brand_logo(produkt.marke) %}
<h1>
    {% if logo %}
        <img src="{{ logo }}" alt="" style="height:48px;max-width:120px;object-fit:contain;vertical-align:middle;margin-right:10px;" onerror="this.style.display='none'">
    {% endif %}
    {% if produkt.marke %}{{ produkt.marke }} · {% endif %}{{ produkt.name }}{% if produkt.verpackungsinfo %} · {{ produkt.verpackungsinfo }}{% endif %}
</h1>

<div class="stats">

    <div class="stat">
        <div>{{ t('current_stock') }}</div>
        <div class="stat-zahl">{{ produkt.bestand }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_7_days") }}</div>
        <div class="stat-zahl">{{ stats.tage7 }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_30_days") }}</div>
        <div class="stat-zahl">{{ stats.tage30 }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_3_months") }}</div>
        <div class="stat-zahl">{{ stats.monate3 }}</div>
    </div>

    <div class="stat">
        <div>{{ t("consumption_total") }}</div>
        <div class="stat-zahl">{{ stats.gesamt }}</div>
    </div>

    <div class="stat">
        <div>{{ t("average_unit_price") }}</div>
        <div class="stat-zahl" style="font-size:24px;">
            {{ format_money(produkt.preis_cent, produkt.waehrung) }}
        </div>
    </div>

</div>

<div class="card">
    <h2>{{ t("edit_product") }}</h2>

    <form
        method="post"
        action="/produkt/{{ produkt.id }}/bearbeiten"
    >
        <div style="
            display:grid;
            grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
            gap:14px;
            width:100%;
            margin-bottom:14px;
        ">
            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('product_name') }}</span>
                <input
                    name="name"
                    value="{{ produkt.name }}"
                    required
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('brand_manufacturer') }}</span>
                <input
                    name="marke"
                    value="{{ produkt.marke }}"
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('packaging_info') }}</span>
                <input
                    name="verpackungsinfo"
                    value="{{ produkt.verpackungsinfo }}"
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t('current_stock') }}</span>
                <input
                    name="bestand"
                    type="number"
                    min="0"
                    value="{{ produkt.bestand }}"
                    required
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t("minimum_stock") }}</span>
                <input
                    name="mindestbestand"
                    type="number"
                    min="0"
                    value="{{ produkt.mindestbestand or 0 }}"
                >
            </label>

            <label style="display:flex;flex-direction:column;gap:6px;">
                <span>{{ t("target_stock") }}</span>
                <input
                    name="sollbestand"
                    type="number"
                    min="0"
                    value="{{ produkt.sollbestand or 0 }}"
                >
            </label>
        </div>

        <button type="submit">
            {{ t("save_changes") }}
        </button>
    </form>
</div>


<div class="card">
    <h2>{{ t("change_stock") }}</h2>

    <div class="aktionen">

        <form
            method="post"
            action="/bestand/{{ produkt.id }}/minus"
        >
            <button class="minus" type="submit">
                −1 {{ t("remove") }}
            </button>
        </form>

        <form
            method="post"
            action="/bestand/{{ produkt.id }}/plus"
        >
            <button class="plus" type="submit">
                +1 {{ t("add_stock") }}
            </button>
        </form>

    </div>

    <hr style="margin: 20px 0; border-color: #374151;">

    <h3>{{ t("store_multiple") }}</h3>

    <form
        method="post"
        action="/bestand/{{ produkt.id }}/einlagern"
    >
        <input
            type="number"
            name="menge"
            min="1"
            value="1"
            required
        >

        <input
            type="text"
            name="preis"
            inputmode="decimal"
            placeholder="{{ t('purchase_price_per_unit') }}"
        >

        <input
            type="text"
            name="waehrung"
            maxlength="3"
            pattern="[A-Za-z]{3}"
            value="{{ produkt.waehrung }}"
            aria-label="{{ t('currency') }}"
            required
        >

        <button class="plus" type="submit">
            {{ t("store_multiple") }}
        </button>
    </form>
</div>


<div class="card">
    <h2>{{ t("merge_product") }}</h2>

    <p>
        {{ t("merge_description") }}
    </p>

    <form
        method="post"
        action="/produkt/{{ produkt.id }}/zusammenfuehren"
    >
        <select
            name="ziel_id"
            required
        >
            {% for p in alle_produkte %}
                {% if p.id != produkt.id %}
                <option value="{{ p.id }}">
                    {% if p.marke %}
                        {{ p.marke }} –
                    {% endif %}
                    {{ p.name }}
                </option>
                {% endif %}
            {% endfor %}
        </select>

        <button
            class="minus"
            type="submit"
            onclick="return confirm('{{ t("merge_confirm") }}')"
        >
            {{ t("merge_button") }}
        </button>
    </form>
</div>


<div class="card">
    <h2>{{ t("assigned_barcodes") }}</h2>

    <table>
        <tr>
            <th>{{ t("barcode") }}</th>
            <th>{{ t("assigned_product") }}</th>
            <th>{{ t("quantity") }}</th>
            <th>{{ t("action") }}</th>
            <th></th>
        </tr>

        {% for barcode in barcodes %}
        <tr>
            <td>{{ barcode.ean }}</td>

            <td>
                <select
                    form="barcode-{{ loop.index }}"
                    name="produkt_id"
                >
                    {% for p in alle_produkte %}
                    <option
                        value="{{ p.id }}"
                        {% if p.id == barcode.produkt_id %}selected{% endif %}
                    >
                        {% if p.marke %}
                            {{ p.marke }} –
                        {% endif %}
                        {{ p.name }}
                    </option>
                    {% endfor %}
                </select>
            </td>

            <td>
                <input
                    form="barcode-{{ loop.index }}"
                    name="menge"
                    type="number"
                    min="1"
                    value="{{ barcode.menge }}"
                    required
                    style="width: 80px;"
                >
            </td>

            <td>
                <select
                    form="barcode-{{ loop.index }}"
                    name="aktion"
                >
                    <option
                        value="entnehmen"
                        {% if barcode.aktion == "entnehmen" %}selected{% endif %}
                    >
                        {{ t("remove") }}
                    </option>

                    <option
                        value="einlagern"
                        {% if barcode.aktion == "einlagern" %}selected{% endif %}
                    >
                        {{ t("add_stock") }}
                    </option>
                </select>
            </td>

            <td>
                <form
                    id="barcode-{{ loop.index }}"
                    method="post"
                    action="/barcode/{{ barcode.ean }}/bearbeiten"
                    style="margin:0 0 8px 0;"
                >
                    <button type="submit">
                        {{ t("save") }}
                    </button>
                </form>

                <form
                    method="post"
                    action="/produkt/{{ produkt.id }}/barcode/{{ barcode.ean }}/loeschen"
                    style="margin:0;"
                    onsubmit="return confirm('{{ t("delete_barcode_confirm") }}');"
                >
                    <button
                        type="submit"
                        class="minus"
                        title="{{ t("delete_barcode") }}"
                    >
                        🗑️ {{ t("delete_barcode") }}
                    </button>
                </form>
            </td>
        </tr>
        {% else %}
        <tr>
            <td colspan="4">
                {{ t("no_barcodes_assigned") }}
            </td>
        </tr>
        {% endfor %}

    </table>

    <div style="margin-top: 20px;">
        <a class="button filter" href="/barcode">
            + {{ t("add_another_barcode") }}
        </a>
    </div>
</div>


<div class="card">
    <h2>{{ t("delete_product") }}</h2>

    <p>
        {{ t("delete_product_warning") }}
    </p>

    {% if produkt.bestand == 0 %}
    <form
        method="post"
        action="/produkt/{{ produkt.id }}/loeschen"
    >
        <button
            class="minus"
            type="submit"
            onclick="return confirm('{{ t("delete_product_confirm") }}')"
        >
            {{ t("delete_product_button") }}
        </button>
    </form>
    {% else %}
    <p>
        ⚠️ {{ t("delete_product_stock_not_empty") }}
    </p>
    {% endif %}
</div>


<div class="card">

    <h2>{{ t("booking_history") }}</h2>

    <div style="margin-bottom: 20px;">

        <a
            class="button filter {% if zeitraum == '7' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=7"
        >{{ t("last_7_days") }}</a>

        <a
            class="button filter {% if zeitraum == '30' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=30"
        >{{ t("last_30_days") }}</a>

        <a
            class="button filter {% if zeitraum == '3m' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=3m"
        >{{ t("last_3_months") }}</a>

        <a
            class="button filter {% if zeitraum == '6m' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=6m"
        >{{ t("last_6_months") }}</a>

        <a
            class="button filter {% if zeitraum == '1j' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=1j"
        >{{ t("last_year") }}</a>

        <a
            class="button filter {% if zeitraum == 'alle' %}filter-aktiv{% endif %}"
            href="/produkt/{{ produkt.id }}?zeitraum=alle"
        >
            {{ t("total") }}
        </a>

    </div>

    <table>
        <tr>
            <th>{{ t("time") }}</th>
            <th>{{ t("action") }}</th>
            <th>{{ t("change") }}</th>
            <th>{{ t("before") }}</th>
            <th>{{ t("after") }}</th>
            <th>{{ t("source") }}</th>
            <th>{{ t("unit_price") }}</th>
            <th>{{ t("undo") }}</th>
        </tr>

        {% for b in buchungen %}
        <tr>
            <td>{{ b.zeitpunkt }}</td>
            <td>{{ booking_action(b.aktion) }}</td>

            <td>
                {% if b.menge is not none %}
                    {% if b.menge > 0 %}+{% endif %}{{ b.menge }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>
                {% if b.bestand_vorher is not none %}
                    {{ b.bestand_vorher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>
                {% if b.bestand_nachher is not none %}
                    {{ b.bestand_nachher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>{{ b.quelle or "—" }}</td>

            <td>
                {% if b.einzelpreis_cent is not none %}
                    {{ format_money(b.einzelpreis_cent, b.waehrung) }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td>
                {% if b.quelle == "scanner" and b.storniert == 0 %}
                    <form method="post" action="/buchung/{{ b.id }}/stornieren">
                        <input
                            type="password"
                            name="passwort"
                            placeholder="{{ t('password') }}"
                            required
                            style="width: 110px;"
                        >
                        <button class="minus" type="submit">
                            {{ t("undo") }}
                        </button>
                    </form>

                {% elif b.storniert == 1 %}
                    {{ t("undone") }}

                {% else %}
                    —
                {% endif %}
            </td>

        </tr>

        {% else %}

        <tr>
            <td colspan="7">
                {{ t("no_bookings_period") }}
            </td>
        </tr>

        {% endfor %}
    </table>

</div>

</body>
</html>
"""


BARCODE_HTML = HTML_START + """
<a class="zurueck" href="/">{{ t('back_to_fridge') }}</a>

<h1>{{ t('barcode_add') }}</h1>

<div class="card">
    <h2>{{ t('product_lookup') }}</h2>

    <div>
        <input
            id="lookup-ean"
            placeholder="{{ t('ean_upc') }}"
            autocomplete="off"
        >

        <button
            type="button"
            onclick="lookupProduct()"
        >
            {{ t('product_lookup') }}
        </button>
    </div>

    <p id="lookup-status"></p>
</div>


<div class="card">

    <form method="post" action="/barcode/speichern">

        <input
            type="hidden"
            id="barcode-ean"
            name="ean"
            required
        >

        <h2>{{ t("product") }}</h2>

        <label>
            <input
                type="radio"
                name="modus"
                value="neu"
                checked
                onchange="updateMode()"
            >
            {{ t('new_product') }}
        </label>

        <label>
            <input
                type="radio"
                name="modus"
                value="bestehend"
                onchange="updateMode()"
            >
            {{ t('assign_existing') }}
        </label>

        <div id="new-product-fields" style="margin-top: 15px;">

            <input
                id="produkt-name"
                name="name"
                placeholder="{{ t('product_name') }}"
            >

            <input
                id="produkt-marke"
                name="marke"
                placeholder="{{ t('brand_manufacturer') }}"
            >

            <input
                id="api-menge"
                name="verpackungsinfo"
                placeholder="{{ t('packaging_info') }}"
            >

            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:14px; width:100%;">

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="bestand">
                        {{ t('current_stock') }}
                    </label>
                    <input
                        id="bestand"
                        name="bestand"
                        type="number"
                        min="0"
                        value="0"
                    >
                </div>

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="mindestbestand">
                        {{ t("minimum_stock") }}
                    </label>
                    <input
                        id="mindestbestand"
                        name="mindestbestand"
                        type="number"
                        min="0"
                        value="0"
                    >
                </div>

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="sollbestand">
                        {{ t("target_stock") }}
                    </label>
                    <input
                        id="sollbestand"
                        name="sollbestand"
                        type="number"
                        min="0"
                        value="0"
                    >
                </div>

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="preis">
                        {{ t("purchase_price_per_unit") }}
                    </label>
                    <input
                        id="preis"
                        name="preis"
                        type="text"
                        inputmode="decimal"
                        placeholder="0.00"
                    >
                </div>

                <div style="display:flex; flex-direction:column; gap:6px;">
                    <label for="waehrung">
                        {{ t("currency") }}
                    </label>
                    <input
                        id="waehrung"
                        name="waehrung"
                        type="text"
                        maxlength="3"
                        pattern="[A-Za-z]{3}"
                        value="EUR"
                        required
                    >
                </div>

            </div>

        </div>

        <div
            id="existing-product-fields"
            style="display: none; margin-top: 15px;"
        >

            <select
                name="produkt_id"
                style="
                    padding: 10px;
                    border-radius: 6px;
                    min-width: 280px;
                "
            >
                {% for p in produkte %}
                    <option value="{{ p.id }}">
                        {{ p.name }} ({{ p.bestand }})
                    </option>
                {% endfor %}
            </select>

        </div>

        <hr style="margin: 20px 0; border-color: #374151;">

        <h2>{{ t("barcode_action") }}</h2>

        <select
            name="aktion"
            style="
                padding: 10px;
                border-radius: 6px;
            "
        >
            <option value="entnehmen">
                {{ t("remove") }}
            </option>

            <option value="einlagern">
                {{ t("add_stock") }}
            </option>
        </select>

        <input
            name="menge"
            type="number"
            min="1"
            value="1"
            required
            placeholder="{{ t('quantity_per_scan') }}"
        >

        <button type="submit">
            {{ t("save_barcode") }}
        </button>

    </form>

</div>


<script>
function t(key) {
    const translations = {
        enter_ean: "{{ t('enter_ean') }}",
        searching: "{{ t('product_searching') }}",
        found: "{{ t('product_found') }}",
        not_found_manual: "{{ t('product_not_found_manual') }}",
        product_search_error: "{{ t('product_search_error') }}"
    };

    return translations[key] || key;
}

async function lookupProduct() {
    const eanInput = document.getElementById("lookup-ean");
    const ean = eanInput.value.trim();
    const status = document.getElementById("lookup-status");

    if (!ean) {
        status.textContent = t("enter_ean");
        return;
    }

    status.textContent = t("searching");

    try {
        const response = await fetch(
            "/api/produkt-suche/" + encodeURIComponent(ean)
        );

        const data = await response.json();

        document.getElementById("barcode-ean").value = ean;

        if (data.gefunden) {
            document.getElementById("produkt-name").value =
                data.name || "";

            document.getElementById("produkt-marke").value =
                data.marke || "";

            document.getElementById("api-menge").value =
                data.menge || "";

            status.textContent =
                t("found") + " " +
                [data.marke, data.name, data.menge]
                    .filter(Boolean)
                    .join(" – ");
        } else {
            status.textContent =
                t("not_found_manual");

            document.getElementById("produkt-name").value = "";
            document.getElementById("produkt-marke").value = "";
            document.getElementById("api-menge").value = "";
        }

    } catch (error) {
        status.textContent =
            t("product_search_error");
    }
}


function updateMode() {
    const mode = document.querySelector(
        'input[name="modus"]:checked'
    ).value;

    const newFields =
        document.getElementById("new-product-fields");

    const existingFields =
        document.getElementById("existing-product-fields");

    if (mode === "neu") {
        newFields.style.display = "block";
        existingFields.style.display = "none";
    } else {
        newFields.style.display = "none";
        existingFields.style.display = "block";
    }
}
</script>

</body>
</html>
"""
