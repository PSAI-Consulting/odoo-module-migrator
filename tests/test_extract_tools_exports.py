# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""tools/extract_tools_exports.py on a small git repository built by the test."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "extract"))
import extract_tools_exports as ete  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo, files, message, delete=()):
    for path, text in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for path in delete:
        (repo / path).unlink()
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


@pytest.fixture
def odoo_repo(tmp_path):
    repo = tmp_path / "odoo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "v1")
    _commit(repo, {
        "odoo/__init__.py": "",
        "odoo/models/__init__.py": "",
        "odoo/orm/__init__.py": "",
        "odoo/tools/__init__.py": (
            "from .mail import *\nfrom .misc import *\nfrom .query import Query\n"
        ),
        "odoo/tools/mail.py": (
            "from markupsafe import Markup\nimport re\nfrom PIL import Image\n"
            "Image._initialized = 2\n"
            "def html_to_inner_content(html):\n    return html\n"
        ),
        "odoo/tools/misc.py": (
            "from typing import TypeVar\nfrom collections import OrderedDict\n"
            "T = TypeVar('T')\n"
            "try:\n    import xlwt\nexcept ImportError:\n    xlwt = None\n"
            "def street_split(street):\n    return street\n"
            "def ustr(value):\n    return str(value)\n"
            "def kept(x):\n    return x\n"
        ),
        "odoo/tools/query.py": "class Query:\n    pass\n",
    }, "v1")
    _git(repo, "checkout", "-q", "-b", "v2")
    _commit(repo, {
        "odoo/tools/mail.py": (
            "from markupsafe import Markup\nimport re\n__all__ = ['Markup']\n"
            "def html_to_inner_content(html):\n    return html\n"
        ),
    }, "[IMP] tools: mail __all__")
    _commit(repo, {
        "odoo/tools/misc.py": (
            "from collections import OrderedDict\n__all__ = ['kept']\n"
            "def kept(x):\n    return x\n"
        ),
        "odoo/tools/business_data.py": "def street_split(street):\n    return street.strip()\n",
    }, "[REF] tools: isolate business code")
    _commit(repo, {
        "odoo/tools/__init__.py": "from .mail import *\nfrom .misc import *\n",
        "odoo/orm/query.py": "class Query:\n    pass\n",
        "odoo/models/__init__.py": "from odoo.orm.query import Query\n",
    }, "[MOV] core: move Query into odoo.orm", delete=["odoo/tools/query.py"])
    return repo


def test_extractor(odoo_repo):
    rules = {(r["from"], r["name"]): r for r in ete.compare(odoo_repo, "v1", "v2")}
    # star export lost (__all__ added): still defined in odoo.tools.mail
    assert rules[("odoo.tools", "html_to_inner_content")]["to"] == "odoo.tools.mail"
    assert rules[("odoo.tools", "html_to_inner_content")]["proof"] == "odoo %s '[IMP] tools: mail __all__'" % (
        rules[("odoo.tools", "html_to_inner_content")]["proof"].split()[1])
    # re-export of another library: its real origin
    assert rules[("odoo.tools", "OrderedDict")]["import"] == "from collections import OrderedDict"
    # "Image._initialized = 2" does not define Image
    assert rules[("odoo.tools", "Image")]["import"] == "from PIL import Image"
    # moved with its code adapted, by one commit: proved by that commit
    assert rules[("odoo.tools", "street_split")]["to"] == "odoo.tools.business_data"
    assert "[REF] tools: isolate business code" in rules[("odoo.tools", "street_split")]["proof"]
    assert rules[("odoo.tools.misc", "street_split")]["to"] == "odoo.tools.business_data"
    # moved to odoo.orm: the public module re-exporting it
    assert rules[("odoo.tools", "Query")]["to"] == "odoo.models"
    assert rules[("odoo.tools.query", "Query")]["to"] == "odoo.models"
    assert rules[("odoo.tools", "query")] == {
        "from": "odoo.tools", "name": "query", "to": None, "module": True,
        "proof": rules[("odoo.tools", "query")]["proof"],
    }
    assert "[MOV] core: move Query into odoo.orm" in rules[("odoo.tools", "query")]["proof"]
    # removed
    assert rules[("odoo.tools", "ustr")]["to"] is None
    assert rules[("odoo.tools.misc", "ustr")]["to"] is None
    # never reported: still exported, module imports, conditional names, TypeVar
    for name in ("Markup", "kept", "re", "xlwt", "T", "mail", "misc"):
        assert ("odoo.tools", name) not in rules
    text = ete.dump(list(rules.values()), "v1", "v2")
    assert "- {from: 'odoo.tools', name: 'ustr', to: null," in text
