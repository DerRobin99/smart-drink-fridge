from flask import Blueprint, request
from translation import (
    available_languages,
    get_default_language,
)
from utils.redirects import safe_redirect

language_bp = Blueprint("language", __name__)


@language_bp.route("/sprache/<lang>")
def sprache(lang):
    lang = str(lang).strip().lower()
    available_codes = set(available_languages())

    if lang not in available_codes:
        lang = get_default_language()

    response = safe_redirect(request.referrer)


    response.set_cookie(
        "lang",
        lang,
        max_age=60 * 60 * 24 * 365,
        samesite="Lax"
    )

    return response
