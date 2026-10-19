"""Backend localization: the language list and the system-phrase catalog."""

from dodaios.i18n.catalog import pick, t, table, variant_table, variants
from dodaios.i18n.locales import (
    DEFAULT_LOCALE,
    LANGUAGE_NAMES,
    SUPPORTED_LOCALES,
    is_known_language,
    is_supported_locale,
    language_name,
    phrase_locale,
)

__all__ = [
    "DEFAULT_LOCALE",
    "LANGUAGE_NAMES",
    "SUPPORTED_LOCALES",
    "is_known_language",
    "is_supported_locale",
    "language_name",
    "phrase_locale",
    "pick",
    "t",
    "table",
    "variant_table",
    "variants",
]
