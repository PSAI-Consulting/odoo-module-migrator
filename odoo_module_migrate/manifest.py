# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Manifest edition that keeps the formatting of the file."""

import ast


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
    node = _find_key(text, "depends")
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
        source = text[pos(elt.lineno, elt.col_offset):pos(elt.end_lineno, elt.end_col_offset)]
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
        indent = text[pos(first.lineno, 0):pos(first.lineno, first.col_offset)]
        closing_indent = text[pos(node.end_lineno, 0):end - 1]
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
            messages.append((
                "error",
                f"Depends on '{old}', removed from Odoo: replace or drop this "
                f"dependency by hand",
            ))
            continue
        if action not in ("renamed", "merged", "oca_moved") or not new:
            continue
        if new in result:
            del result[index]
            messages.append(("info", f"Dependency '{old}' removed ({action} into '{new}', already a dependency)"))
        else:
            result[index] = new
            messages.append(("info", f"Dependency '{old}' replaced by '{new}' ({action})"))
        if action == "oca_moved":
            messages.append(("warning", f"Check that '{new}' is available on your system"))
    return result, messages
