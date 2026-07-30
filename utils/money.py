import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def normalize_currency(value, default="EUR"):
    currency = str(value or default).strip().upper()

    if not _CURRENCY_PATTERN.fullmatch(currency):
        raise ValueError("invalid currency")

    return currency


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
