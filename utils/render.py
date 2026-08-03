import re

from flask import render_template_string, request
from database import get_setting
from utils.auth import accounts_enabled, current_user
from utils.money import CURRENCY_CHOICES, currency_symbol


_get_language_callback = None
_translations = {}
_current_version = ""


def configure_rendering(
    get_language_callback,
    translations,
    current_version,
):
    global _get_language_callback
    global _translations
    global _current_version

    _get_language_callback = get_language_callback
    _translations = translations
    _current_version = current_version


def get_language():
    if _get_language_callback is None:
        raise RuntimeError("Rendering wurde noch nicht konfiguriert.")

    return _get_language_callback()


HTML_START = """
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#2563eb">
    <meta name="application-name" content="Smart Drink Fridge">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Drink Fridge">
    <link rel="manifest" href="/static/manifest.webmanifest">
    <link rel="icon" href="/static/icons/icon-192.png" sizes="192x192">
    <link rel="apple-touch-icon" href="/static/icons/icon-192.png">
    <title>{{ t("title") }}</title>

    <script>
        if ("serviceWorker" in navigator) {
            window.addEventListener("load", () => {
                navigator.serviceWorker.register(
                    "/service-worker.js?v=4",
                    { updateViaCache: "none" }
                ).then((registration) => registration.update());
            });
        }
    </script>

    <style>
        * {
            box-sizing: border-box;
        }

        html {
            background: #111827;
            overflow-x: hidden;
        }

        body {
            font-family: Arial, sans-serif;
            background: #111827;
            color: white;
            width: 100%;
            max-width: 1100px;
            margin: auto;
            padding: max(20px, env(safe-area-inset-top))
                     max(20px, env(safe-area-inset-right))
                     max(20px, env(safe-area-inset-bottom))
                     max(20px, env(safe-area-inset-left));
            overflow-x: hidden;
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
            max-width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
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

        .top-navigation {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 20px;
        }

        .top-navigation .button {
            margin: 0;
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

        /* Smart appliance design system */
        :root {
            color-scheme: dark;
            --bg: #07111f;
            --surface: rgba(16, 30, 49, .88);
            --surface-strong: #14243a;
            --surface-soft: rgba(30, 50, 75, .72);
            --border: rgba(148, 184, 224, .14);
            --text: #f3f8ff;
            --muted: #93a9c4;
            --accent: {{ theme_accent }};
            --accent-strong: color-mix(in srgb, {{ theme_accent }} 82%, #0369a1);
            --success: #34d399;
            --warning: #fbbf24;
            --danger: #fb7185;
            --shadow: 0 18px 45px rgba(0, 0, 0, .22);
        }

        html {
            background:
                radial-gradient(circle at 15% -10%, rgba(14,165,233,.18), transparent 36rem),
                radial-gradient(circle at 90% 10%, rgba(45,212,191,.10), transparent 30rem),
                var(--bg);
        }

        body {
            font-family: Inter, ui-sans-serif, system-ui, -apple-system,
                         BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: transparent;
            color: var(--text);
            max-width: 1180px;
            padding-top: 104px;
        }

        h1, h2, h3 {
            letter-spacing: -.025em;
        }

        h1 {
            color: var(--text);
            font-size: clamp(2rem, 5vw, 3.4rem);
            line-height: 1.05;
            margin: 0 0 28px;
        }

        h2 {
            margin-top: 0;
        }

        p {
            color: var(--muted);
            line-height: 1.65;
        }

        a {
            color: var(--accent);
        }

        .app-bar {
            position: fixed;
            z-index: 100;
            top: 14px;
            left: 50%;
            transform: translateX(-50%);
            width: min(calc(100% - 28px), 1140px);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            padding: 12px 14px 12px 18px;
            background: rgba(7, 17, 31, .78);
            border: 1px solid var(--border);
            border-radius: 20px;
            box-shadow: 0 16px 44px rgba(0,0,0,.28);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }

        .app-brand {
            display: flex;
            align-items: center;
            gap: 11px;
            color: var(--text);
            font-weight: 800;
            white-space: nowrap;
        }

        .app-brand:hover,
        .app-nav a:hover {
            text-decoration: none;
        }

        .brand-mark {
            display: block;
            width: 38px;
            height: 38px;
            border-radius: 12px;
            object-fit: cover;
            box-shadow: 0 8px 22px color-mix(in srgb, var(--accent) 30%, transparent);
        }

        .app-nav {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .app-nav a {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 13px;
            border-radius: 12px;
            color: var(--muted);
            font-size: 14px;
            font-weight: 700;
        }

        .app-nav a.active {
            color: var(--text);
            background: var(--surface-soft);
            box-shadow: inset 0 0 0 1px var(--border);
        }

        .nav-icon {
            font-size: 18px;
            line-height: 1;
        }

        .page-hero {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 24px;
            margin-bottom: 26px;
        }

        .eyebrow {
            color: var(--accent);
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .14em;
            text-transform: uppercase;
            margin-bottom: 9px;
        }

        .page-hero h1 {
            margin-bottom: 8px;
        }

        .page-hero p {
            margin: 0;
            max-width: 620px;
        }

        .primary-action {
            background: linear-gradient(135deg, var(--accent), var(--accent-strong));
            color: #032235 !important;
            font-weight: 800;
            box-shadow: 0 12px 28px rgba(14,165,233,.25);
        }

        .card {
            background: linear-gradient(145deg, rgba(20,36,58,.92), rgba(12,25,43,.92));
            border: 1px solid var(--border);
            border-radius: 22px;
            padding: 24px;
            box-shadow: var(--shadow);
        }

        .stats {
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 14px;
        }

        .stat {
            position: relative;
            overflow: hidden;
            min-height: 128px;
            padding: 20px;
            background: linear-gradient(145deg, var(--surface-strong), rgba(21,42,67,.72));
            border: 1px solid var(--border);
            border-radius: 19px;
            box-shadow: 0 12px 30px rgba(0,0,0,.14);
        }

        .stat::after {
            content: "";
            position: absolute;
            width: 80px;
            height: 80px;
            right: -28px;
            top: -30px;
            border-radius: 50%;
            background: rgba(56,189,248,.12);
        }

        .stat-label {
            color: var(--muted);
            font-size: 13px;
            font-weight: 700;
        }

        .stat-zahl {
            margin: 8px 0 3px;
            color: var(--text);
            font-size: 34px;
            letter-spacing: -.04em;
        }

        .product-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
            gap: 14px;
        }

        .checkout-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 16px;
        }

        .checkout-card {
            display: grid;
            gap: 10px;
            padding: 18px;
            border-radius: 20px;
            background: var(--surface);
            border: 1px solid var(--border);
            text-align: center;
        }

        .checkout-image {
            display: grid;
            place-items: center;
            width: 100%;
            height: 105px;
            border-radius: 16px;
            color: var(--accent);
            background: rgba(255,255,255,.04);
            font-size: 48px;
            font-weight: 900;
        }

        .checkout-image img {
            max-width: 85%;
            max-height: 80px;
            object-fit: contain;
        }

        .checkout-name {
            font-size: 1.15rem;
            font-weight: 850;
        }

        .checkout-card .stock-pill {
            justify-self: center;
            font-size: 15px;
        }

        .checkout-form {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 10px;
            align-items: end;
        }

        .checkout-form label {
            display: grid;
            gap: 4px;
            color: var(--muted);
            text-align: left;
            font-size: 13px;
        }

        .product-card {
            display: flex;
            flex-direction: column;
            min-width: 0;
            padding: 18px;
            border-radius: 18px;
            background: rgba(28, 48, 73, .62);
            border: 1px solid var(--border);
            transition: transform .18s ease, border-color .18s ease;
        }

        .product-card:hover {
            transform: translateY(-2px);
            border-color: rgba(56,189,248,.38);
        }

        .product-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
        }

        .product-title {
            color: var(--text);
            font-size: 18px;
            font-weight: 800;
            overflow-wrap: anywhere;
        }

        .product-meta {
            margin-top: 4px;
            color: var(--muted);
            font-size: 13px;
        }

        .stock-pill {
            flex: 0 0 auto;
            min-width: 48px;
            padding: 8px 10px;
            border-radius: 14px;
            text-align: center;
            background: rgba(52,211,153,.13);
            color: #86efac;
            font-size: 20px;
            font-weight: 900;
        }

        .stock-pill.low {
            background: rgba(251,191,36,.12);
            color: #fde68a;
        }

        .stock-pill.empty {
            background: rgba(251,113,133,.12);
            color: #fda4af;
        }

        .stock-track {
            height: 7px;
            margin: 18px 0 14px;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(148,163,184,.14);
        }

        .stock-fill {
            height: 100%;
            min-width: 3px;
            border-radius: inherit;
            background: linear-gradient(90deg, #2dd4bf, #38bdf8);
        }

        .product-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-top: auto;
        }

        .product-actions {
            display: flex;
            gap: 8px;
        }

        .product-actions form {
            margin: 0;
        }

        button, .button {
            min-height: 42px;
            padding: 10px 15px;
            border-radius: 12px;
            font-family: inherit;
            font-weight: 750;
            transition: transform .15s ease, filter .15s ease;
        }

        button:hover, .button:hover {
            transform: translateY(-1px);
            filter: brightness(1.08);
            text-decoration: none;
        }

        .plus {
            background: #059669;
        }

        .minus {
            background: #e11d48;
        }

        .filter {
            background: var(--surface-soft);
            border: 1px solid var(--border);
            color: var(--text);
        }

        .filter-aktiv {
            background: var(--accent-strong);
            border-color: transparent;
        }

        th {
            color: var(--muted);
            font-size: 12px;
            letter-spacing: .07em;
            text-transform: uppercase;
        }

        th, td {
            border-bottom-color: var(--border);
        }

        input, select, textarea {
            color: var(--text);
            background: rgba(7,17,31,.66);
            border: 1px solid var(--border);
            outline: none;
        }

        input:focus, select:focus, textarea:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(56,189,248,.14);
        }

        .success-message {
            position: relative;
            color: #d1fae5;
            background: rgba(5,150,105,.20);
            border-color: rgba(52,211,153,.32);
            border-radius: 14px;
            animation: toast-in .25s ease-out;
        }

        @keyframes toast-in {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .empty-state {
            padding: 34px 20px;
            text-align: center;
            color: var(--muted);
        }

        .chart {
            display: flex;
            align-items: end;
            gap: 8px;
            min-height: 190px;
            padding-top: 18px;
        }

        .chart-column {
            display: flex;
            flex: 1 1 0;
            min-width: 0;
            height: 165px;
            flex-direction: column;
            align-items: center;
            justify-content: end;
            gap: 7px;
        }

        .chart-value {
            color: var(--muted);
            font-size: 11px;
            font-weight: 800;
        }

        .chart-bar {
            width: min(30px, 76%);
            min-height: 3px;
            border-radius: 8px 8px 3px 3px;
            background: linear-gradient(180deg, #67e8f9, #0284c7);
            box-shadow: 0 8px 20px rgba(14,165,233,.18);
        }

        .chart-label {
            max-width: 100%;
            color: var(--muted);
            font-size: 10px;
            overflow: hidden;
        }

        @media (max-width: 700px) {
            body {
                padding-top: max(22px, env(safe-area-inset-top));
                padding-bottom: calc(96px + env(safe-area-inset-bottom));
            }

            .app-bar {
                top: auto;
                bottom: max(10px, env(safe-area-inset-bottom));
                width: min(calc(100% - 20px), 520px);
                padding: 8px;
                border-radius: 22px;
            }

            .app-brand {
                display: none;
            }

            .app-nav {
                width: 100%;
                justify-content: space-around;
            }

            .app-nav a {
                flex: 1 1 0;
                flex-direction: column;
                gap: 3px;
                min-width: 0;
                padding: 8px 3px;
                font-size: 10px;
            }

            .nav-icon {
                font-size: 21px;
            }

            .page-hero {
                align-items: flex-start;
                flex-direction: column;
                gap: 16px;
            }

            .page-hero .primary-action {
                width: 100%;
                text-align: center;
            }

            .stats {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .stat {
                min-height: 116px;
                padding: 16px;
            }

            .stat-zahl {
                font-size: 30px;
            }

            .product-grid {
                grid-template-columns: 1fr;
            }

            .product-card {
                padding: 16px;
            }

            .chart {
                gap: 4px;
                overflow-x: auto;
            }

            .chart-column {
                flex: 0 0 34px;
            }

            .chart-label {
                font-size: 9px;
            }

            .zurueck {
                display: none;
            }

            body {
                padding: max(16px, env(safe-area-inset-top))
                         max(14px, env(safe-area-inset-right))
                         calc(96px + env(safe-area-inset-bottom))
                         max(14px, env(safe-area-inset-left));
            }

            h1 {
                font-size: 30px;
                margin: 20px 0 24px;
            }

            h2 {
                font-size: 23px;
                margin-top: 0;
            }

            .top-navigation {
                display: grid;
                grid-template-columns: 1fr;
            }

            .top-navigation .button {
                width: 100%;
                padding: 12px 14px;
                text-align: center;
            }

            .card {
                padding: 16px;
                border-radius: 16px;
                overflow-x: hidden;
            }

            .responsive-table,
            .responsive-table tbody {
                display: block;
                width: 100%;
            }

            .responsive-table .table-head {
                display: none;
            }

            .responsive-table tr:not(.table-head) {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 6px 12px;
                padding: 12px 0;
                border-bottom: 1px solid #374151;
            }

            .responsive-table tr:not(.table-head):last-child {
                border-bottom: 0;
            }

            .responsive-table td {
                display: block;
                min-width: 0;
                padding: 6px 0;
                border: 0;
                overflow-wrap: anywhere;
            }

            .responsive-table td::before {
                content: attr(data-label);
                display: block;
                margin-bottom: 4px;
                color: #9ca3af;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: .04em;
                text-transform: uppercase;
            }

            .responsive-table .mobile-primary,
            .responsive-table .mobile-actions {
                grid-column: 1 / -1;
            }

            .responsive-table .mobile-primary {
                font-size: 18px;
            }

            .responsive-table .mobile-actions .aktionen,
            .responsive-table .mobile-actions form {
                width: 100%;
            }

            .responsive-table .mobile-actions button {
                width: 100%;
                min-height: 44px;
                font-size: 18px;
            }

            .responsive-table .bestand {
                font-size: 22px;
            }

            input,
            select,
            textarea {
                width: 100%;
                max-width: 100%;
                min-height: 44px;
                margin: 5px 0;
            }

            input[type="radio"],
            input[type="checkbox"] {
                width: auto;
                min-height: auto;
            }

            .card form {
                max-width: 100%;
            }
        }

</style>
</head>
<body>
<header class="app-bar">
    <a class="app-brand" href="/">
        <img class="brand-mark" src="/static/icons/icon-192.png" alt="">
        <span>Smart Drink Fridge</span>
    </a>
    <nav class="app-nav" aria-label="Main navigation">
        <a href="/" {% if current_path == "/" %}class="active"{% endif %}>
            <span class="nav-icon">⌂</span><span>{{ t("home") }}</span>
        </a>
        {% if accounts_enabled and checkout_enabled %}
        <a href="/checkout" {% if current_path == "/checkout" %}class="active"{% endif %}>
            <span class="nav-icon">🥤</span><span>{{ t("checkout") }}</span>
        </a>
        {% endif %}
        <a href="/statistik" {% if current_path == "/statistik" %}class="active"{% endif %}>
            <span class="nav-icon">▥</span><span>{{ t("statistics") }}</span>
        </a>
        <a href="/barcode" {% if current_path == "/barcode" %}class="active"{% endif %}>
            <span class="nav-icon">＋</span><span>{{ t("barcode_add") }}</span>
        </a>
        <a href="/einstellungen" {% if current_path == "/einstellungen" %}class="active"{% endif %}>
            <span class="nav-icon">⚙</span><span>{{ t("settings") }}</span>
        </a>
        {% if accounts_enabled and current_user %}
        <a href="/konto" {% if current_path == "/konto" %}class="active"{% endif %}>
            <span class="nav-icon">◎</span><span>{{ current_user.name }}</span>
        </a>
        {% endif %}
    </nav>
</header>
"""


INDEX_HTML = HTML_START + """
<div class="page-hero">
    <div>
        <div class="eyebrow">Smart Drink Fridge</div>
        <h1>{{ t("home") }}</h1>
        <p>{{ t("dashboard_subtitle") }}</p>
    </div>
    <a class="button primary-action" href="/barcode">
        ＋ {{ t("barcode_add") }}
    </a>
</div>

<div class="stats">
    <div class="stat">
        <div class="stat-label">{{ t("products_count") }}</div>
        <div class="stat-zahl">{{ summary.products }}</div>
        <div class="stat-label">{{ t("products") }}</div>
    </div>
    <div class="stat">
        <div class="stat-label">{{ t("units_in_stock") }}</div>
        <div class="stat-zahl">{{ summary.units }}</div>
        <div class="stat-label">{{ t("drinks") }}</div>
    </div>
    <div class="stat">
        <div class="stat-label">{{ t("low_stock") }}</div>
        <div class="stat-zahl">{{ summary.low_stock }}</div>
        <div class="stat-label">{{ t("products") }}</div>
    </div>
    <div class="stat">
        <div class="stat-label">{{ t("last_7_days") }}</div>
        <div class="stat-zahl">{{ summary.consumed_7 }}</div>
        <div class="stat-label">{{ t("drinks") }}</div>
    </div>
</div>

<div class="card">
    <h2>{{ t('inventory_overview') }}</h2>

    <div class="product-grid">
        {% for p in produkte %}
        <article class="product-card">
            <div class="product-head">
                <div>
                    <a class="product-title" href="/produkt/{{ p.id }}">{{ p.name }}</a>
                    <div class="product-meta">
                        {{ p.marke or t("without_brand") }}
                        {% if p.verpackungsinfo %} · {{ p.verpackungsinfo }}{% endif %}
                        · {{ p.barcode_count }} Barcode{% if p.barcode_count != 1 %}s{% endif %}
                    </div>
                </div>
                <div class="stock-pill {% if p.bestand <= 0 %}empty{% elif p.bestand <= p.mindestbestand %}low{% endif %}">
                    {{ p.bestand }}
                </div>
            </div>

            <div class="stock-track" title="{{ p.bestand }} / {{ p.sollbestand or p.bestand }}">
                <div class="stock-fill" style="width:{% if p.bestand <= 0 %}0{% elif not p.sollbestand or p.bestand >= p.sollbestand %}100{% else %}{{ (p.bestand * 100 / p.sollbestand)|round|int }}{% endif %}%"></div>
            </div>

            <div class="product-footer">
                <a href="/produkt/{{ p.id }}">{{ t("open_product") }} →</a>
                <div class="product-actions">
                    <form method="post" action="/bestand/{{ p.id }}/minus">
                        <button class="minus" type="submit" aria-label="{{ t('remove_one') }}">−</button>
                    </form>
                    <form method="post" action="/bestand/{{ p.id }}/plus">
                        <button class="plus" type="submit" aria-label="{{ t('add_one') }}">＋</button>
                    </form>
                </div>
            </div>
        </article>
        {% else %}
        <div class="empty-state">
            <p>{{ t("no_products_yet") }}</p>
            <a class="button primary-action" href="/barcode">{{ t("add_first_product") }}</a>
        </div>
        {% endfor %}
    </div>
</div>

<div class="card">
    <h2>{{ t("recent_activity") }}</h2>

    <table class="responsive-table">
        <tr class="table-head">
            <th>{{ t("time") }}</th>
            <th>{{ t("product") }}</th>
            <th>{{ t("change") }}</th>
            <th>{{ t("stock") }}</th>
            <th>{{ t("source") }}</th>
            {% if accounts_enabled %}<th>{{ t("user") }}</th>{% endif %}
        </tr>

        {% for b in buchungen %}
        <tr>
            <td data-label="{{ t('time') }}">{{ b.zeitpunkt }}</td>

            <td class="mobile-primary" data-label="{{ t('product') }}">
                <a href="/produkt/{{ b.produkt_id }}">
                    {{ b.produkt }}
                </a>
            </td>

            <td data-label="{{ t('change') }}">
                {% if b.menge is not none %}
                    {% if b.menge > 0 %}+{% endif %}{{ b.menge }}
                {% else %}
                    {{ booking_action(b.aktion) }}
                {% endif %}
            </td>

            <td data-label="{{ t('stock') }}">
                {% if b.bestand_nachher is not none %}
                    {{ b.bestand_nachher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td data-label="{{ t('source') }}">{{ b.quelle or "—" }}</td>
            {% if accounts_enabled %}
            <td data-label="{{ t('user') }}">{{ b.benutzer_name or t("unassigned") }}</td>
            {% endif %}
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
    context["current_version"] = _current_version
    context["current_path"] = request.path
    theme_accent = get_setting("theme_accent", "#38bdf8")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", theme_accent or ""):
        theme_accent = "#38bdf8"
    context["theme_accent"] = theme_accent
    context["accounts_enabled"] = accounts_enabled()
    context["checkout_enabled"] = (
        context["accounts_enabled"]
        and get_setting("checkout_mode_enabled", "0").lower()
        in {"1", "true", "yes", "on"}
    )
    context["current_user"] = current_user()
    context["currency_choices"] = CURRENCY_CHOICES
    context["default_currency"] = get_setting("default_currency", "EUR")

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

        code = currency or "EUR"
        symbol = currency_symbol(code)
        return (
            f"{sign}{symbol} "
            f"{absolute // 100}{separator}{absolute % 100:02d}"
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

        <select
            name="waehrung"
            aria-label="{{ t('currency') }}"
            required
        >
            <option value="{{ produkt.waehrung }}" selected>
                {{ produkt.waehrung }}
            </option>
            {% for code, label in currency_choices %}
                {% if code != produkt.waehrung %}
                <option value="{{ code }}">{{ label }}</option>
                {% endif %}
            {% endfor %}
        </select>

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

    <table class="responsive-table">
        <tr class="table-head">
            <th>{{ t("barcode") }}</th>
            <th>{{ t("assigned_product") }}</th>
            <th>{{ t("quantity") }}</th>
            <th>{{ t("action") }}</th>
            <th></th>
        </tr>

        {% for barcode in barcodes %}
        <tr>
            <td class="mobile-primary" data-label="{{ t('barcode') }}">{{ barcode.ean }}</td>

            <td data-label="{{ t('assigned_product') }}">
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

            <td data-label="{{ t('quantity') }}">
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

            <td data-label="{{ t('action') }}">
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

            <td class="mobile-actions">
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
            <td class="mobile-primary" colspan="4">
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

    <table class="responsive-table">
        <tr class="table-head">
            <th>{{ t("time") }}</th>
            <th>{{ t("action") }}</th>
            <th>{{ t("change") }}</th>
            <th>{{ t("before") }}</th>
            <th>{{ t("after") }}</th>
            <th>{{ t("source") }}</th>
            {% if accounts_enabled %}<th>{{ t("user") }}</th>{% endif %}
            <th>{{ t("unit_price") }}</th>
            <th>{{ t("undo") }}</th>
        </tr>

        {% for b in buchungen %}
        <tr>
            <td data-label="{{ t('time') }}">{{ b.zeitpunkt }}</td>
            <td class="mobile-primary" data-label="{{ t('action') }}">{{ booking_action(b.aktion) }}</td>

            <td data-label="{{ t('change') }}">
                {% if b.menge is not none %}
                    {% if b.menge > 0 %}+{% endif %}{{ b.menge }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td data-label="{{ t('before') }}">
                {% if b.bestand_vorher is not none %}
                    {{ b.bestand_vorher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td data-label="{{ t('after') }}">
                {% if b.bestand_nachher is not none %}
                    {{ b.bestand_nachher }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td data-label="{{ t('source') }}">{{ b.quelle or "—" }}</td>
            {% if accounts_enabled %}
            <td data-label="{{ t('user') }}">{{ b.benutzer_name or t("unassigned") }}</td>
            {% endif %}

            <td data-label="{{ t('unit_price') }}">
                {% if b.einzelpreis_cent is not none %}
                    {{ format_money(b.einzelpreis_cent, b.waehrung) }}
                {% else %}
                    —
                {% endif %}
            </td>

            <td class="mobile-actions" data-label="{{ t('undo') }}">
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
            <td class="mobile-primary" colspan="7">
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
                    <select
                        id="waehrung"
                        name="waehrung"
                        required
                    >
                        {% for code, label in currency_choices %}
                        <option value="{{ code }}" {% if code == default_currency %}selected{% endif %}>
                            {{ label }}
                        </option>
                        {% endfor %}
                    </select>
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
