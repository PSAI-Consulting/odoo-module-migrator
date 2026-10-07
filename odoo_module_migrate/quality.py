"""Post-migration diagnostics and semantics-preserving source cleanup."""

import ast
import io
import re
import symtable
import tokenize

from . import tools
from .log import logger
from .manifest import _find_key, _Positions


def readable_strings(text):
    """Decode printable Unicode escapes only if literal values stay equal."""
    edits = []
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.STRING:
                continue
            original = token.string
            if re.match(r"(?i)[rubf]*[rbf]", original):
                continue
            candidate = re.sub(
                r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})",
                lambda m: (
                    chr(int(m[1] or m[2], 16))
                    if int(m[1] or m[2], 16) <= 0x10FFFF
                    and chr(int(m[1] or m[2], 16)).isprintable()
                    and int(m[1] or m[2], 16) > 127
                    else m[0]
                ),
                original,
            )
            try:
                if candidate != original and ast.literal_eval(
                    candidate
                ) == ast.literal_eval(original):
                    edits.append(
                        (
                            starts[token.start[0] - 1] + token.start[1],
                            starts[token.end[0] - 1] + token.end[1],
                            candidate,
                        )
                    )
            except (SyntaxError, ValueError):
                pass
    except (tokenize.TokenError, IndentationError):
        return text
    for start, end, value in reversed(edits):
        text = text[:start] + value + text[end:]
    return text


def check_python(path, text):
    try:
        tree = ast.parse(text)
        symbols = symtable.symtable(text, str(path), "exec")
    except SyntaxError:
        return

    def missing_translation(table):
        for symbol in table.get_symbols():
            if (
                symbol.get_name() == "_"
                and symbol.is_referenced()
                and symbol.is_global()
            ):
                if "_" not in symbols.get_identifiers() or not (
                    symbols.lookup("_").is_assigned()
                    or symbols.lookup("_").is_imported()
                ):
                    return True
        return any(missing_translation(child) for child in table.get_children())

    if missing_translation(symbols):
        line = next(
            (
                n.lineno
                for n in ast.walk(tree)
                if isinstance(n, ast.Name)
                and n.id == "_"
                and isinstance(n.ctx, ast.Load)
            ),
            1,
        )
        logger.warning(
            "[quality] '_' is used without an import or definition (F821). File %s:%s",
            path,
            line,
        )
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name)
            and node.func.id == "_"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "_"
        ):
            if node.args and isinstance(node.args[0], ast.JoinedStr):
                logger.warning(
                    "[quality] f-string evaluated before translation (INT001): use _('... %%(value)s', value=...). File %s:%s",
                    path,
                    node.lineno,
                )
        if isinstance(node, ast.ClassDef):
            declarations = {
                s.targets[0].id
                for s in node.body
                if isinstance(s, ast.Assign)
                and len(s.targets) == 1
                and isinstance(s.targets[0], ast.Name)
            }
            if "_name" in declarations and "_description" not in declarations:
                logger.warning(
                    "[quality] Model declares _name without _description; supply a meaningful description. File %s:%s",
                    path,
                    node.lineno,
                )
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("_compute_"):
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "write"
                ):
                    logger.warning(
                        "[quality] write() in a compute method: consider assigning the computed field directly; review side effects. File %s:%s",
                        path,
                        call.lineno,
                    )


def finish_module(
    module, cosmetic=True, original_data=(), manifest_layout=False, default_website=""
):
    manifest = module / "__manifest__.py"
    if manifest.exists():
        text = tools._read_content(manifest)
        try:
            data = ast.literal_eval(text)
            node = _find_key(text, "data")
            if isinstance(node, (ast.List, ast.Tuple)):
                values = ast.literal_eval(node)
                if len(values) != len(set(values)):
                    logger.warning(
                        "[quality] Duplicate files in manifest data; review repeated loads before removing them. File %s:%s",
                        manifest,
                        node.lineno,
                    )
                # Official ir.access converter appends the replacement. Restore
                # its original load position without reordering other data.
                old = "security/ir.model.access.csv"
                new = "security/ir.access.csv"
                if old in original_data and new in values and old not in values:
                    values.remove(new)
                    preceding = set(original_data[: original_data.index(old)])
                    offset = sum(v in preceding for v in values)
                    values.insert(offset, new)
                    if values != ast.literal_eval(node):
                        from .manifest import rewrite_list

                        text = rewrite_list(text, "data", values)
            if cosmetic and manifest_layout:
                from .manifest import format_manifest

                text = format_manifest(
                    text,
                    default_website,
                    keep_installable=tools.RUN_CONTEXT.get("set_installable", False),
                )
            elif cosmetic and "license" not in data:
                # Missing license already defaults to LGPL-3 in Odoo.
                tree = ast.parse(text)
                mapping = tree.body[0].value
                pos = _Positions(text)
                start = pos(mapping.lineno, mapping.col_offset) + 1
                text = text[:start] + "'license': 'LGPL-3', " + text[start:]
                logger.info("Added Odoo's default license LGPL-3. File %s:1", manifest)
            if text != tools._read_content(manifest):
                tools._write_content(manifest, text)
        except (SyntaxError, ValueError, TypeError) as error:
            logger.warning(
                "[quality] Manifest could not be inspected (%s: %s). File %s:1",
                type(error).__name__,
                error,
                manifest,
            )
    for path in tools.get_files(module, (".py",)):
        text = tools._read_content(path)
        check_python(path, text)
        if cosmetic:
            new = readable_strings(text).lstrip("\r\n")
            if new and not new.endswith("\n"):
                new += "\n"
            if new != text:
                tools._write_content(path, new)
    for path in module.rglob("*.po"):
        if path.parent != module / "i18n":
            logger.warning(
                "[quality] Translation outside i18n/ is not loaded by Odoo; review before moving it. File %s:1",
                path,
            )
