"""
Contract tests for module_template i18n implementation.

Verifies:
- en.json and it.json are present and structurally identical
- useTranslation hook exists and reads from hostapp.language
- entity pages use useTranslation

Reports (never forbids):
- which @ideable/ui strings this module overrides, per language
- which keys copy an @ideable/ui string verbatim in EVERY language, and so override nothing
"""

import json
import os
import re
import warnings
import pytest

SOURCES_DIR = os.path.join(os.path.dirname(__file__), "..", "SOURCES", "src")
I18N_DIR = os.path.join(SOURCES_DIR, "i18n")
HOOKS_DIR = os.path.join(SOURCES_DIR, "hooks")
PAGES_DIR = os.path.join(SOURCES_DIR, "pages")
#: The shared widget library, three levels up from this module's frontend. It owns the strings of
#: its own widgets, so it is read here to say which of this module's keys are OVERRIDES of it.
REUSABLE_UI_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "reusable.ui")

SUPPORTED_LANGUAGES = ["en", "it"]

#: WHO OWNS WHICH STRING, and it decides everything below.
#:
#: `reusable.ui/i18n/*.json` defines the strings of every reusable widget — the library owns its
#: own chrome, and a module that renders `ServerDataTable` gets a complete, translated table
#: without holding a single `table.*` key. A module owns its page strings and resolves them with
#: its own `useTranslation`.
#:
#: A module OVERRIDES a widget string by including that key in its own bundle: inclusion IS the
#: override, and `registerModuleMessages` (called by this module's own hook) is what puts the
#: bundle in front of the library's. So a key a module holds and does not mean to change is not
#: harmless duplication — it pins the library's text at today's wording, silently, the day the
#: library improves it. Every override is reported below rather than forbidden: which strings a
#: module means to change is the module's decision, and a *reader* is what the set needs.
#:
#: What this module MUST carry is therefore only what its OWN code resolves — the module's hook
#: reads the module bundle alone, so a key its pages ask for and it does not have renders as the
#: key itself. `table.viewAuditTrail` is the standing example: the page owns the action and passes
#: the label INTO the shared table, which is how a module shipped without it while every check
#: stayed green — absent from BOTH language files, so a comparison between them agreed.


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


def module_resolved_keys(namespace: str = "") -> set:
    """Every key THIS MODULE'S own code passes to `t()`, read from its sources at test time.

    DERIVED, NEVER LISTED — a list goes stale the first time a page gains a control, and this one
    went stale in the opposite direction too: it named keys no module code ever resolved.
    """
    keys = set()
    pattern = re.compile(r"""\bt\(\s*['"](%s[A-Za-z0-9_.]+)['"]""" % re.escape(namespace))
    for folder, _dirs, files in os.walk(SOURCES_DIR):
        if "node_modules" in folder:
            continue
        for name in files:
            if not name.endswith((".tsx", ".ts")):
                continue
            content = open(os.path.join(folder, name), encoding="utf-8").read()
            keys.update(pattern.findall(content))
    return keys


def library_messages(lang: str) -> dict:
    """The shared library's own bundle for `lang`, flattened to `a.b.c` → string."""
    path = os.path.join(REUSABLE_UI_DIR, "i18n", f"{lang}.json")
    if not os.path.isfile(path):
        return {}
    return flatten(load_json(path))


def module_messages(lang: str) -> dict:
    """This module's own bundle for `lang`, flattened to `a.b.c` → string."""
    return flatten(load_json(os.path.join(I18N_DIR, f"{lang}.json")))


def flatten(obj: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, full_key))
        else:
            out[full_key] = v
    return out


def test_the_library_bundle_is_readable() -> None:
    """The override report below measures nothing if the library's own bundle cannot be found."""
    assert os.path.isdir(REUSABLE_UI_DIR), (
        f"the shared widget library is not at {REUSABLE_UI_DIR} — which strings are the library's "
        "cannot be established, so the override report would pass by reporting nothing"
    )
    keys = library_messages("en")
    assert len(keys) > 10, (
        f"only {len(keys)} keys found in reusable.ui/i18n/en.json — the library's bundle has moved "
        "or is empty, and an override cannot be told from a module's own string"
    )


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_every_table_key_the_module_resolves_itself_is_translated(lang: str) -> None:
    """A `table.*` key a PAGE passes to `t()` comes from the module's bundle, or not at all.

    The module's hook reads the module bundle alone — it has no library fallback — so a key its
    own code asks for and it does not carry renders as the key itself. Keys the WIDGETS resolve
    are not required here: the widget reads the library's bundle, which always has them.
    """
    present = collect_keys(load_json(os.path.join(I18N_DIR, f"{lang}.json")))
    required = module_resolved_keys("table.")
    assert required, "no table.* key is resolved by this module's own code — the scan has drifted"
    missing = sorted(required - present)
    assert not missing, (
        f"{lang}.json is missing {len(missing)} key(s) this module's own code resolves: {missing}. "
        "A missing key is displayed as the key itself, so these appear verbatim in the UI."
    )


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_module_overrides_of_library_strings_are_reported(lang: str) -> None:
    """Name every library string this module overrides in `lang`, and what it became.

    REPORTS, DOES NOT FORBID. Which widget strings a module means to change is the module's own
    decision, so this cannot be an assertion; what it can be is a *reader*, because an override is
    otherwise invisible — a key sitting in a module bundle looks exactly like a page string.

    PER LANGUAGE, and legitimately so: *this key changes the library's Italian string* is a fact
    about Italian. The companion report below — which keys override nothing — is not, and is
    computed across every language for the reason its own docstring gives.
    """
    module, library = module_messages(lang), library_messages(lang)
    overrides = sorted(k for k in module.keys() & library.keys() if module[k] != library[k])

    report = [f"[i18n {lang}] {len(overrides)} override(s) of @ideable/ui strings:"]
    report += [f"    {k}: {library[k]!r} → {module[k]!r}" for k in overrides] or ["    (none)"]
    text = "\n".join(report)
    print(text)
    if overrides:
        warnings.warn(text, stacklevel=1)


def keys_that_override_nothing_in_any_language() -> list:
    """Keys this module copies from the library VERBATIM IN EVERY LANGUAGE and resolves nowhere.

    JUDGED ACROSS ALL LANGUAGES AT ONCE, which is why this is a function and not an expression
    inside the per-language report above. `test_lang_files_have_identical_keys` requires every
    language file to hold the same keys, so a key can only be dropped from all of them or from
    none — which makes "is this key a copy?" a question about the key, never about one language.

    Judged one language at a time it produced advice the module could not act on: a key that
    changes the library's string in `it` and happens to coincide with it in `en` was named in the
    English report as a copy that overrides nothing, while the key-parity test in this same file
    required English to keep it. Removing it from `en.json` alone breaks parity; removing it from
    both loses the Italian override. Two assertions in one file, disagreeing about the same key.

    So a key is a no-op only when, in EVERY supported language, the library carries it and the
    module's value is byte-identical to it. A language where the library carries no such key is not
    a coincidence either — there the module's string is the only one there is.

    Keys the module's own code resolves are excluded whatever their value: the module's hook has no
    library fallback, so dropping one renders the key itself in the UI.
    """
    copied_in = []
    for lang in SUPPORTED_LANGUAGES:
        module, library = module_messages(lang), library_messages(lang)
        copied_in.append({k for k in module.keys() & library.keys() if module[k] == library[k]})
    if not copied_in:
        return []
    return sorted(set.intersection(*copied_in) - module_resolved_keys())


def test_keys_that_override_nothing_in_any_language_are_reported() -> None:
    """Name every key this module copies from @ideable/ui verbatim in EVERY language.

    The list that costs something. A module key whose value is byte-identical to the library's
    overrides nothing today and pins that wording forever: the day the library improves the string,
    every module holding a copy keeps the old one and nothing says why.

    ONE LIST FOR ALL LANGUAGES, never one per language — see
    `keys_that_override_nothing_in_any_language`. These keys, and only these, can actually be
    deleted: every one of them can go from every language file at once, leaving key parity intact
    and no override behind. That is what makes this a report a module can act on.

    Like the override report it names rather than forbids; a module's bundle holds its own
    decisions, including the copies it inherited before this rule existed.
    """
    no_ops = keys_that_override_nothing_in_any_language()
    if not no_ops:
        print(
            f"[i18n] no key copies an @ideable/ui string verbatim in every language "
            f"({', '.join(SUPPORTED_LANGUAGES)})"
        )
        return
    text = (
        f"[i18n] {len(no_ops)} key(s) copied from @ideable/ui with the SAME value in EVERY "
        f"language ({', '.join(SUPPORTED_LANGUAGES)}), which override nothing and pin the "
        "library's wording: " + ", ".join(no_ops)
    )
    print(text)
    warnings.warn(text, stacklevel=1)


def test_use_translation_hook_exists() -> None:
    path = os.path.join(HOOKS_DIR, "useTranslation.ts")
    assert os.path.isfile(path), "useTranslation.ts hook is missing"


def test_use_translation_reads_hostapp_language() -> None:
    path = os.path.join(HOOKS_DIR, "useTranslation.ts")
    content = open(path, encoding="utf-8").read()
    assert "hostapp.language" in content, "useTranslation must read from hostapp.language localStorage key"
    assert "hostapp:language-changed" in content, "useTranslation must listen for hostapp:language-changed event"


def test_entity_pages_use_translations() -> None:
    # Every entity page (renders ServerDataTable against a data service) must localize
    # via useTranslation — derived from the module's own pages, not a literal
    # TemplateItems.tsx. The dev-only Widget Gallery (synthetic data, no service) is
    # excluded.
    page_files = [
        os.path.join(PAGES_DIR, f) for f in os.listdir(PAGES_DIR) if f.endswith(".tsx")
    ]
    entity_pages = []
    for path in page_files:
        content = open(path, encoding="utf-8").read()
        if "ServerDataTable" in content and re.search(r"from ['\"][^'\"]*services/", content):
            entity_pages.append(path)
    assert entity_pages, "No entity pages (ServerDataTable + data service) found"
    for path in entity_pages:
        content = open(path, encoding="utf-8").read()
        name = os.path.basename(path)
        assert "useTranslation" in content, f"{name} must import useTranslation"
        assert "t(" in content, f"{name} must call t() for translations"
