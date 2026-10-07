# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Every rule file of migration_scripts/ is valid: YAML syntax, structure of
its type (see BaseMigrationScript) and regular expressions that compile."""

import pathlib
import re

import pytest
import yaml

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "odoo_module_migrate" / "migration_scripts"

# type of rule -> minimum length of an entry (list types)
LIST_TYPES = {
    "field_types": 5,
    "deprecated_modules": 2,   # [module, state, (new module)]
    "renamed_fields": 3,       # [model, old, new (or null), (source)]
    "removed_fields": 2,       # [model, field, (message)]
    "renamed_models": 2,       # [old, new, (source)]
    "removed_models": 1,       # [model, (message)]
}
TEXT_TYPES = ("text_replaces", "text_errors", "text_warnings")

FILES = sorted(
    p for kind in (*LIST_TYPES, *TEXT_TYPES) for p in (SCRIPTS / kind).glob("*/*.yaml")
)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(SCRIPTS)))
def test_rule_file(path):
    kind = path.relative_to(SCRIPTS).parts[0]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return  # empty file: skipped by the loader
    if kind in LIST_TYPES:
        assert isinstance(data, list), "a list of entries is expected"
        for entry in data:
            assert isinstance(entry, list) and len(entry) >= LIST_TYPES[kind], entry
            assert all(isinstance(v, str) or v is None for v in entry), entry
            assert isinstance(entry[0], str) and entry[0], entry
    else:
        assert isinstance(data, dict), "{extension: {pattern: value}} is expected"
        for extension, rules in data.items():
            assert isinstance(extension, str) and extension.startswith(("*", ".")), extension
            assert isinstance(rules, dict), extension
            for pattern, value in rules.items():
                re.compile(pattern)  # raises on an invalid regex
                # text_replaces: null = remove the match (tools._replace_in_file)
                assert isinstance(value, str) or (value is None and kind == "text_replaces"), pattern


def test_rule_files_found():
    assert len(FILES) > 50
