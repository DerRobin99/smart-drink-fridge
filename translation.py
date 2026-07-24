import os
from pathlib import Path
from typing import Dict, List


BASE_DIR = Path(__file__).resolve().parent
TRANSLATIONS_DIR = BASE_DIR / "translations"
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
    if not TRANSLATIONS_DIR.is_dir():
        return []

    return sorted(
        file.stem
        for file in TRANSLATIONS_DIR.glob("*.lang")
        if file.is_file()
    )


def load_translations(language: str) -> Dict[str, str]:
    languages = available_languages()

    if language not in languages:
        language = FALLBACK_LANGUAGE

    translations = load_language_file(
        TRANSLATIONS_DIR / f"{language}.lang"
    )

    if language != FALLBACK_LANGUAGE:
        fallback = load_language_file(
            TRANSLATIONS_DIR / f"{FALLBACK_LANGUAGE}.lang"
        )

        return {**fallback, **translations}

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
