# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Manifest edition that keeps the formatting of the file."""

import ast
import io
import json
import textwrap
import tokenize

KEY_ORDER = (
    "name",
    "summary",
    "description",
    "version",
    "category",
    "author",
    "website",
    "license",
    "depends",
    "external_dependencies",
    "data",
    "demo",
    "assets",
)
SCAFFOLD_COMMENTS = (
    "categories can be used",
    "for the full list",
    "any module necessary",
    "always loaded",
    "only loaded in demonstration",
    "check https://github.com/odoo/odoo",
)


def format_manifest(text, default_website="", keep_installable=False):
    """Canonical layout without importing another client's metadata.

    Keep list order, unknown keys, nonempty descriptions and authored comments.
    Missing website is empty unless the caller explicitly supplies a default.
    """
    data = ast.literal_eval(text)
    tree = ast.parse(text)
    if (
        not isinstance(data, dict)
        or len(tree.body) != 1
        or not isinstance(tree.body[0].value, ast.Dict)
    ):
        raise ManifestError("Manifest must contain one literal dictionary")
    mapping = tree.body[0].value
    pos = _Positions(text)
    start, end = (
        pos(mapping.lineno, mapping.col_offset),
        pos(mapping.end_lineno, mapping.end_col_offset),
    )
    data.setdefault("website", default_website)
    data.setdefault("license", "LGPL-3")
    for key in ("summary", "description"):
        if isinstance(data.get(key), str) and not data[key].strip():
            data.pop(key)
    for key in ("external_dependencies", "demo", "assets"):
        if key in data and not data[key]:
            data.pop(key)
    for key, default in (
        ("installable", True),
        ("application", False),
        ("auto_install", False),
    ):
        if (
            key in data
            and data[key] is default
            and not (key == "installable" and keep_installable)
        ):
            data.pop(key)
    comments = {}
    keys = [
        (k.lineno, k.end_lineno, k.value)
        for k in mapping.keys
        if isinstance(k, ast.Constant)
    ]
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type != tokenize.COMMENT or not (
            mapping.lineno <= token.start[0] <= mapping.end_lineno
        ):
            continue
        if any(phrase in token.string.lower() for phrase in SCAFFOLD_COMMENTS):
            continue
        # An inline comment belongs to its key. A standalone comment between
        # entries documents the following key and must move with it when the
        # canonical order is applied.
        same_line = next(
            (key for line, end, key in keys if line <= token.start[0] <= end), None
        )
        owner = same_line or next(
            (key for line, _end, key in keys if line > token.start[0]), None
        )
        comments.setdefault(owner, []).append(token.string)

    def render(value, indent):
        pad = " " * indent
        if isinstance(value, (list, tuple)):
            opening, closing = ("[", "]") if isinstance(value, list) else ("(", ")")
            return (
                opening
                + (
                    "\n"
                    + "".join(
                        pad + "    " + render(v, indent + 4) + ",\n" for v in value
                    )
                    + pad
                    if value
                    else ""
                )
                + closing
            )
        if isinstance(value, dict):
            return (
                "{"
                + (
                    "\n"
                    + "".join(
                        pad
                        + "    "
                        + render(k, 0)
                        + ": "
                        + render(v, indent + 4)
                        + ",\n"
                        for k, v in value.items()
                    )
                    + pad
                    if value
                    else ""
                )
                + "}"
            )
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return repr(value)

    def render_entry(key, value):
        if (
            key == "description"
            and isinstance(value, str)
            and "\n" in value
            and '"""' not in value
        ):
            content = textwrap.dedent(value).strip()
            body = "\n".join("        " + line for line in content.splitlines())
            return f'"""\n{body}\n    """'
        return render(value, 4)

    ordered = [key for key in KEY_ORDER if key in data] + [
        key for key in data if key not in KEY_ORDER
    ]
    lines = ["{"]
    lines.extend("    " + c for c in comments.pop(None, []))
    for key in ordered:
        lines.extend("    " + c for c in comments.pop(key, []))
        lines.append(
            "    " + render(key, 0) + ": " + render_entry(key, data[key]) + ","
        )
    for remaining in comments.values():
        lines.extend("    " + c for c in remaining)
    lines.append("}")
    return text[:start] + "\n".join(lines) + text[end:]


class ManifestError(ValueError):
    pass


class _Positions:
    """Convert ast (line, utf-8 byte column) positions to text offsets."""

    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.starts = [0, 0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    def __call__(self, lineno, col_offset):
        line = self.lines[lineno - 1].encode("utf-8")
        return self.starts[lineno] + len(line[:col_offset].decode("utf-8"))


def _find_key(text, key):
    # Odoo reads manifests with ast.literal_eval(), which accepts a leading
    # indentation: do the same, and keep the node positions right
    indent = len(text) - len(text.lstrip(" \t"))
    try:
        tree = ast.parse(text[indent:])
    except SyntaxError as e:
        raise ManifestError(f"Manifest is not valid Python: {e}") from e
    if indent:
        for node in ast.walk(tree):
            if getattr(node, "lineno", None) == 1:
                node.col_offset += indent
            if getattr(node, "end_lineno", None) == 1:
                node.end_col_offset += indent
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    return v
    return None


def rewrite_depends(text, new_depends):
    """Return `text` with the 'depends' list replaced by `new_depends`.

    The quote style, the one-line / one-item-per-line layout, the indentation
    and the trailing comma of the original list are kept.
    """
    return rewrite_list(text, "depends", new_depends)


def rewrite_list(text, key, new_depends):
    node = _find_key(text, key)
    if not isinstance(node, (ast.List, ast.Tuple)):
        raise ManifestError("'depends' is not a literal list")
    pos = _Positions(text)
    start = pos(node.lineno, node.col_offset)
    end = pos(node.end_lineno, node.end_col_offset)
    original = text[start:end]
    if "#" in original:
        raise ManifestError("'depends' contains comments: not rewritten")
    opening, closing = original[0], original[-1]

    # Keep the source text (quotes...) of each item; new items take the
    # quotes of the item they replace, or of the first item
    sources, quotes = {}, []
    for elt in node.elts:
        source = text[
            pos(elt.lineno, elt.col_offset) : pos(elt.end_lineno, elt.end_col_offset)
        ]
        if isinstance(elt, ast.Constant):
            sources[elt.value] = source
            quotes.append(source[0])
    default_quote = quotes[0] if quotes else '"'
    items = []
    for index, name in enumerate(new_depends):
        if name in sources:
            items.append(sources[name])
        else:
            # replaced in place: take the quotes of the replaced item
            quote = quotes[index] if index < len(quotes) else default_quote
            items.append(f"{quote}{name}{quote}")

    if node.lineno != node.end_lineno and node.elts:
        # one item per line
        first = node.elts[0]
        indent = text[pos(first.lineno, 0) : pos(first.lineno, first.col_offset)]
        closing_indent = text[pos(node.end_lineno, 0) : end - 1]
        body = "".join(f"\n{indent}{item}," for item in items)
        new = f"{opening}{body}\n{closing_indent}{closing}"
    else:
        trailing = "," if original.rstrip(closing).rstrip().endswith(",") else ""
        if opening == "(" and len(items) == 1:
            trailing = ","
        new = f"{opening}{', '.join(items)}{trailing}{closing}"
    return text[:start] + new + text[end:]


def get_depends(text):
    node = _find_key(text, "depends")
    if node is None:
        return []
    try:
        return list(ast.literal_eval(node))
    except ValueError as e:
        raise ManifestError("'depends' is not a literal list") from e


def apply_module_rules(depends, rules):
    """Apply [old, action, new?] rules to a depends list.

    Returns (new_depends, messages) where messages are (level, text).
    """
    result = list(depends)
    messages = []
    for items in rules:
        old, action = items[0], items[1]
        new = items[2] if len(items) > 2 and items[2] else None
        if old not in result:
            continue
        index = result.index(old)
        if action == "removed":
            messages.append(
                (
                    "error",
                    f"Depends on '{old}', removed from Odoo: replace or drop this "
                    f"dependency by hand",
                )
            )
            continue
        if action not in ("renamed", "merged", "oca_moved") or not new:
            continue
        if new in result:
            del result[index]
            messages.append(
                (
                    "info",
                    f"Dependency '{old}' removed ({action} into '{new}', already a dependency)",
                )
            )
        else:
            result[index] = new
            messages.append(
                ("info", f"Dependency '{old}' replaced by '{new}' ({action})")
            )
        if action == "oca_moved":
            messages.append(
                ("warning", f"Check that '{new}' is available on your system")
            )
    return result, messages
