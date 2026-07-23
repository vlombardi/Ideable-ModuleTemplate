"""
Contract tests for module_template i18n implementation.

Verifies:
- en.json and it.json are present and structurally identical
- useTranslation hook exists and reads from hostapp.language
- TemplateItems.tsx uses useTranslation
"""

import json
import os
import pytest

SOURCES_DIR = os.path.join(os.path.dirname(__file__), "..", "SOURCES", "src")
I18N_DIR = os.path.join(SOURCES_DIR, "i18n")
HOOKS_DIR = os.path.join(SOURCES_DIR, "hooks")
PAGES_DIR = os.path.join(SOURCES_DIR, "pages")

SUPPORTED_LANGUAGES = ["en", "it"]


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def collect_keys(obj: dict, prefix: str = "") -> set:
    keys = set()
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(collect_keys(v, full_key))
        else:
            keys.add(full_key)
    return keys


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_lang_file_exists(lang: str) -> None:
    path = os.path.join(I18N_DIR, f"{lang}.json")
    assert os.path.isfile(path), f"Missing language file: {lang}.json"


def test_lang_files_have_identical_keys() -> None:
    en = load_json(os.path.join(I18N_DIR, "en.json"))
    it = load_json(os.path.join(I18N_DIR, "it.json"))
    en_keys = collect_keys(en)
    it_keys = collect_keys(it)
    missing_in_it = en_keys - it_keys
    extra_in_it = it_keys - en_keys
    assert not missing_in_it, f"Keys in en.json missing from it.json: {missing_in_it}"
    assert not extra_in_it, f"Extra keys in it.json not in en.json: {extra_in_it}"


def test_use_translation_hook_exists() -> None:
    path = os.path.join(HOOKS_DIR, "useTranslation.ts")
    assert os.path.isfile(path), "useTranslation.ts hook is missing"


def test_use_translation_reads_hostapp_language() -> None:
    path = os.path.join(HOOKS_DIR, "useTranslation.ts")
    content = open(path, encoding="utf-8").read()
    assert "hostapp.language" in content, "useTranslation must read from hostapp.language localStorage key"
    assert "hostapp:language-changed" in content, "useTranslation must listen for hostapp:language-changed event"


def test_template_items_uses_translations() -> None:
    path = os.path.join(PAGES_DIR, "TemplateItems.tsx")
    assert os.path.isfile(path), "TemplateItems.tsx not found"
    content = open(path, encoding="utf-8").read()
    assert "useTranslation" in content, "TemplateItems.tsx must import useTranslation"
    assert "t(" in content, "TemplateItems.tsx must call t() for translations"
