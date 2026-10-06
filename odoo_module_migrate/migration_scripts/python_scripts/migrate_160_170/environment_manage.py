# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""``api.Environment.manage()`` is removed in 17.0.

Source: odoo commit 6c6ca1662662 "[REM] core: deprecated Environment methods";
16.0 odoo/api.py: ``manage()`` only warns "Since Odoo 15.0, Environment.manage()
is useless." and yields.

    with api.Environment.manage():      ->      do_something()
        do_something()

The ``with`` is dropped and its body dedented (lines inside a multi-line string
are kept as is). A ``with`` having other context managers or ``as`` is reported.
"""

import ast
import io
import tokenize

MANAGE = ("api.Environment.manage()", "Environment.manage()", "odoo.api.Environment.manage()")


def _string_continuation_lines(text):
    """Line numbers (1-based) starting inside a multi-line string."""
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.STRING and token.end[0] > token.start[0]:
            lines.update(range(token.start[0] + 1, token.end[0] + 1))
    return lines


def _manage_withs(tree):
    """(convertible with nodes, unconverted lines)"""
    withs, unconverted = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(ast.unparse(item.context_expr) in MANAGE for item in node.items):
            continue
        if len(node.items) != 1 or node.items[0].optional_vars is not None:
            unconverted.append(node.lineno)
        elif node.body[0].lineno == node.lineno:
            unconverted.append(node.lineno)  # body on the with line
        else:
            withs.append(node)
    return withs, unconverted


def _unwrap(text, node):
    """Text without the `with` node (body dedented), or None."""
    lines = text.splitlines(keepends=True)
    in_string = _string_continuation_lines(text)
    shift = node.body[0].col_offset - node.col_offset
    new_lines = {}
    for number in range(node.body[0].lineno, node.end_lineno + 1):
        line = lines[number - 1]
        if number in in_string or not line.strip():
            continue
        if line[:shift].strip():
            return None
        new_lines[number] = line[shift:]
    for number, line in new_lines.items():
        lines[number - 1] = line
    del lines[node.lineno - 1:node.body[0].lineno - 1]
    return "".join(lines)


def _rewrite(text):
    """Return (new_text, [unconverted lines])."""
    failed = set()
    while True:
        withs, unconverted = _manage_withs(ast.parse(text))
        withs = [n for n in withs if n.lineno not in failed]
        if not withs:
            return text, sorted(set(unconverted) | failed)
        node = withs[0]
        new_text = _unwrap(text, node)
        if new_text is None:
            failed.add(node.lineno)
        else:
            text = new_text


def migrate_environment_manage(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        text = tools._read_content(path)
        if "Environment.manage(" not in text:
            continue
        try:
            new_text, unconverted = _rewrite(text)
            ast.parse(new_text)
        except SyntaxError:
            continue
        if new_text != text:
            tools._write_content(path, new_text)
            logger.info("[17] with api.Environment.manage() removed (odoo 6c6ca1662662) in %s" % path)
        for line in unconverted:
            logger.error(
                "[17] api.Environment.manage() is removed since 17.0 (odoo 6c6ca1662662):"
                " drop it. File %s:%s" % (path, line)
            )
