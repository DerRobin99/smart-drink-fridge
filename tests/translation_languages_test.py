"""Ensure every shipped language is complete and regional codes work."""

import os
import sys

sys.path.insert(0, "/app")

from translation import available_languages, load_translations, normalize_language


expected = {
    "ar", "cs", "da", "de", "de-ch", "en", "es", "fi", "fr", "it",
    "lb", "nl", "no", "pl", "pt", "ru", "sv", "tr", "uk",
}
available = set(available_languages())
assert expected <= available, expected - available
reference_keys = set(load_translations("en"))
for language in expected:
    translations = load_translations(language)
    assert set(translations) == reference_keys, language
    assert translations["language_name"]
assert normalize_language("de-CH") == "de-ch"
assert normalize_language("es-MX") == "es"
assert normalize_language("ar-SA") == "ar"
assert normalize_language("unknown") == "de"
print("All translation language tests passed.")
