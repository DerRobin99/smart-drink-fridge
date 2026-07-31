import os
from pathlib import Path
from typing import Dict, List


BASE_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = BASE_DIR / "translations"
BUNDLED_TRANSLATIONS_DIR = BASE_DIR / "translations-bundled"
FALLBACK_LANGUAGE = "de"


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
        if directory.is_dir():
            languages.update(
                file.stem
                for file in directory.glob("*.lang")
                if file.is_file()
            )
    return sorted(languages)


def load_translations(language: str) -> Dict[str, str]:
    languages = available_languages()

    if language not in languages:
        language = FALLBACK_LANGUAGE

    # The bundled files always provide a complete base. Existing Docker
    # installations may mount an older /app/translations directory; those
    # files are treated as optional overrides instead of replacing new keys.
    translations = load_language_file(
        BUNDLED_TRANSLATIONS_DIR / f"{FALLBACK_LANGUAGE}.lang"
    )
    if language != FALLBACK_LANGUAGE:
        translations.update(load_language_file(
            BUNDLED_TRANSLATIONS_DIR / f"{language}.lang"
        ))

    translations.update(load_language_file(
        TRANSLATIONS_DIR / f"{FALLBACK_LANGUAGE}.lang"
    ))
    if language != FALLBACK_LANGUAGE:
        translations.update(load_language_file(
            TRANSLATIONS_DIR / f"{language}.lang"
        ))
    return translations


def normalize_language(language: str) -> str:
    if not language:
        return FALLBACK_LANGUAGE

    language = language.strip().lower().replace("_", "-")
    language = language.split("-", 1)[0]

    if language in available_languages():
        return language

    return FALLBACK_LANGUAGE


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
