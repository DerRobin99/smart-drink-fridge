from flask import Blueprint, redirect, request
from translation import (
    available_languages,
    get_default_language,
)

language_bp = Blueprint("language", __name__)


@language_bp.route("/sprache/<lang>")
def sprache(lang):
    lang = str(lang).strip().lower()
    available_codes = set(available_languages())

    if lang not in available_codes:
        lang = get_default_language()

    response = redirect(
        request.referrer or "/"
    )


    response.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        samesite="Lax"
    )

    return response
