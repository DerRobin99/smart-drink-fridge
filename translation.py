import os
from pathlib import Path
from typing import Dict, List


BASE_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = BASE_DIR / "translations"
BUNDLED_TRANSLATIONS_DIR = BASE_DIR / "translations-bundled"
FALLBACK_LANGUAGE = "de"

LANGUAGE_NAMES = {
    "ar": "🇸🇦 العربية", "cs": "🇨🇿 Čeština", "da": "🇩🇰 Dansk",
    "de": "🇩🇪 Deutsch", "de-ch": "🇨🇭 Deutsch (Schweiz)",
    "en": "🇬🇧 English", "es": "🇪🇸 Español", "fi": "🇫🇮 Suomi",
    "fr": "🇫🇷 Français", "it": "🇮🇹 Italiano", "lb": "🇱🇺 Lëtzebuergesch",
    "nl": "🇳🇱 Nederlands", "no": "🇳🇴 Norsk", "pl": "🇵🇱 Polski",
    "pt": "🇵🇹 Português", "ru": "🇷🇺 Русский", "sv": "🇸🇪 Svenska",
    "tr": "🇹🇷 Türkçe", "uk": "🇺🇦 Українська",
}


def _language_files(directory: Path) -> Dict[str, Path]:
    """Return translation files discovered inside a trusted directory."""
    if not directory.is_dir():
        return {}

    trusted_root = directory.resolve()
    language_files = {}
    for file in directory.glob("*.lang"):
        resolved_file = file.resolve()
        if file.is_file() and resolved_file.parent == trusted_root:
            language_files[file.stem] = resolved_file
    return language_files


def load_language_file(path: Path) -> Dict[str, str]:
    translations: Dict[str, str] = {}

    if not path.is_file():
        return translations

    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.rstrip("\n\r")

            if not line or line.lstrip().startswith("#"):
                continue

            if "=" not in line:
                print(
                    f"Ungültige Übersetzungszeile übersprungen: "
                    f"{path.name}:{line_number}"
                )
                continue

            key, value = line.split("=", 1)

            key = _decode_value(key)
            value = _decode_value(value)

            if not key:
                continue

            translations[key] = value

    return translations


def _decode_value(value: str) -> str:
    return (
        value
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\=", "=")
        .replace("\\\\", "\\")
    )


def available_languages() -> List[str]:
    languages = set()
    for directory in (BUNDLED_TRANSLATIONS_DIR, TRANSLATIONS_DIR):
        languages.update(_language_files(directory))
    return sorted(languages)


def load_translations(language: str) -> Dict[str, str]:
    bundled_files = _language_files(BUNDLED_TRANSLATIONS_DIR)
    override_files = _language_files(TRANSLATIONS_DIR)
    languages = set(bundled_files) | set(override_files)

    if language not in languages:
        language = FALLBACK_LANGUAGE

    # The bundled files always provide a complete base. Existing Docker
    # installations may mount an older /app/translations directory; those
    # files are treated as optional overrides instead of replacing new keys.
    translations = {}
    if FALLBACK_LANGUAGE in bundled_files:
        translations.update(load_language_file(bundled_files[FALLBACK_LANGUAGE]))
    if language != FALLBACK_LANGUAGE and language in bundled_files:
        translations.update(load_language_file(bundled_files[language]))

    if FALLBACK_LANGUAGE in override_files:
        translations.update(load_language_file(override_files[FALLBACK_LANGUAGE]))
    if language != FALLBACK_LANGUAGE and language in override_files:
        translations.update(load_language_file(override_files[language]))
    return translations


def normalize_language(language: str) -> str:
    if not language:
        return FALLBACK_LANGUAGE

    language = language.strip().lower().replace("_", "-")
    languages = set(available_languages())
    if language in languages:
        return language
    base_language = language.split("-", 1)[0]
    if base_language in languages:
        return base_language

    return FALLBACK_LANGUAGE


def language_display_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code.upper())


def translate(text: str, language: str) -> str:
    translations = load_translations(
        normalize_language(language)
    )

    return translations.get(text, text)


def invert_translations(lang="de"):
    return {
        value: key
        for key, value in TRANSLATIONS.get(lang, {}).items()
    }


def get_default_language() -> str:
    languages = available_languages()

    if "en" in languages:
        return "en"

    return languages[0] if languages else "en"
