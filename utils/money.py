import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

CURRENCY_SYMBOLS = {
    "AUD": "A$",
    "BRL": "R$",
    "CAD": "C$",
    "CHF": "CHF",
    "CNY": "CN¥",
    "CZK": "Kč",
    "DKK": "kr",
    "EUR": "€",
    "GBP": "£",
    "HKD": "HK$",
    "HUF": "Ft",
    "IDR": "Rp",
    "ILS": "₪",
    "INR": "₹",
    "JPY": "¥",
    "KRW": "₩",
    "MXN": "MX$",
    "MYR": "RM",
    "NOK": "kr",
    "NZD": "NZ$",
    "PHP": "₱",
    "PLN": "zł",
    "RON": "lei",
    "SEK": "kr",
    "SGD": "S$",
    "THB": "฿",
    "TRY": "₺",
    "USD": "$",
    "ZAR": "R",
}

CURRENCY_CHOICES = tuple(
    (code, f"{code} ({symbol})")
    for code, symbol in CURRENCY_SYMBOLS.items()
)


def normalize_currency(value, default="EUR"):
    currency = str(value or default).strip().upper()

    if not _CURRENCY_PATTERN.fullmatch(currency):
        raise ValueError("invalid currency")

    return currency


def currency_symbol(currency):
    code = normalize_currency(currency)
    return CURRENCY_SYMBOLS.get(code, code)


def parse_optional_price_cents(value):
    raw_value = str(value or "").strip()

    if not raw_value:
        return None

    try:
        price = Decimal(raw_value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("invalid price") from exc

    if not price.is_finite() or price < 0:
        raise ValueError("invalid price")

    cents = (price * 100).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )

    return int(cents)


def weighted_average_cents(
    existing_stock,
    existing_price_cents,
    added_quantity,
    added_price_cents,
):
    total_stock = existing_stock + added_quantity

    if total_stock <= 0:
        return 0

    total_value = (
        existing_stock * existing_price_cents
        + added_quantity * added_price_cents
    )

    return int(
        (Decimal(total_value) / Decimal(total_stock)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
