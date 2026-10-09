"""Post-migration diagnostics and semantics-preserving source cleanup."""

import ast
import io
import re
import symtable
import tokenize
import warnings

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


def check_adjacent_string_apostrophes(path, text):
    """Warn when SQL-style doubled quotes concatenate two Python strings."""
    previous = None
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.STRING:
                if previous is not None and previous.end == token.start:
                    try:
                        left = ast.literal_eval(previous.string)
                        right = ast.literal_eval(token.string)
                    except (SyntaxError, ValueError):
                        pass
                    else:
                        if (
                            isinstance(left, str)
                            and isinstance(right, str)
                            and left
                            and right
                            and left[-1].isalpha()
                            and right[0].isalpha()
                        ):
                            logger.warning(
                                "[quality] Adjacent Python string literals join %r and %r; "
                                "an apostrophe is probably missing (use an escaped apostrophe "
                                "or the other quote style). File %s:%s",
                                left,
                                right,
                                path,
                                token.start[0],
                            )
                previous = token
            elif token.type not in (
                tokenize.ENCODING,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.COMMENT,
            ):
                previous = None
    except (tokenize.TokenError, IndentationError):
        return


def _offsets(text):
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return lambda row, col: starts[row - 1] + col


def repair_sql_apostrophes(path, text):
    r"""Turn SQL-style ``'d''entrée'`` into ``'d\'entrée'``.

    Two plain single-quoted literals glued without any space, both letters
    around the junction, are never an intended concatenation: Python silently
    produces ``dentrée``. Only this unambiguous form is rewritten.
    """
    edits = []
    previous = None
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.STRING:
                previous = None
                continue
            plain = (
                token.string[:1] == "'"
                and not token.string.startswith("'''")
                and len(token.string) >= 3
            )
            if (
                previous is not None
                and previous.end == token.start
                and plain
                and token.string[1].isalpha()
                and previous.string[-2].isalpha()
            ):
                edits.append((previous.end, token.start))
            previous = token if plain else None
    except (tokenize.TokenError, IndentationError):
        return text
    offset = _offsets(text)
    for end, _start in reversed(edits):
        at = offset(*end)
        # previous literal's closing quote + next literal's opening quote
        text = text[: at - 1] + "\\'" + text[at + 1 :]
        logger.info(
            "[quality] Restored apostrophe lost by SQL-style doubled quotes. File %s:%s",
            path,
            end[0],
        )
    return text


_VALID_ESCAPES = set("\n\\'\"abfnrtv01234567xNuU")


def fix_invalid_escapes(path, text):
    r"""Prefix with r strings whose backslashes are all invalid escapes.

    Python 3.12 warns on ``"\."`` and will reject it. When no valid escape is
    present, the raw string has exactly the same value; otherwise only warn.
    """
    edits = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError):
        return text
    for token in tokens:
        if token.type != tokenize.STRING or "\\" not in token.string:
            continue
        prefix = re.match(r"(?i)[rubf]*", token.string)[0]
        if "r" in prefix.lower() or "b" in prefix.lower() or "f" in prefix.lower():
            continue
        body = token.string[len(prefix):]
        following = re.findall(r"\\(.)", body, re.S)
        if all(char in _VALID_ESCAPES for char in following):
            continue
        if any(char in _VALID_ESCAPES for char in following):
            logger.warning(
                "[quality] String mixes valid and invalid backslash escapes "
                "(SyntaxWarning in Python 3.12); escape the invalid ones. File %s:%s",
                path,
                token.start[0],
            )
            continue
        candidate = prefix + "r" + body
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if ast.literal_eval(candidate) != ast.literal_eval(token.string):
                    continue
        except (SyntaxError, ValueError):
            continue
        edits.append((token.start, token.end, candidate))
    offset = _offsets(text)
    for start, end, value in reversed(edits):
        text = text[: offset(*start)] + value + text[offset(*end) :]
        logger.info(
            "[quality] Invalid escape sequence: string made raw. File %s:%s",
            path,
            start[0],
        )
    return text


def check_python(path, text):
    check_adjacent_string_apostrophes(path, text)
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
            if (
                "_name" in declarations
                and "_description" not in declarations
                and not _extends_same_named_model(node)
            ):
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


def migrate_simple_translation_fstrings(path, text):
    """Turn simple translated f-strings into extractable named placeholders.

    Expressions with conversions, format specifications, calls or subscripts are
    deliberately left to the existing INT001 diagnostic: naming those values is
    a business/editorial choice rather than a mechanical migration.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    positions = _Positions(text)

    def source(node):
        return text[
            positions(node.lineno, node.col_offset) :
            positions(node.end_lineno, node.end_col_offset)
        ]

    edits = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and len(node.args) == 1
            and not node.keywords
            and isinstance(node.args[0], ast.JoinedStr)
            and (
                isinstance(node.func, ast.Name) and node.func.id == "_"
                or isinstance(node.func, ast.Attribute) and node.func.attr == "_"
            )
        ):
            continue
        chunks = []
        arguments = []
        names = {}
        used = set()
        safe = True
        for value in node.args[0].values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                chunks.append(value.value.replace("%", "%%"))
                continue
            if not (
                isinstance(value, ast.FormattedValue)
                and value.conversion == -1
                and value.format_spec is None
            ):
                safe = False
                break
            expression = value.value
            cursor = expression
            while isinstance(cursor, ast.Attribute):
                cursor = cursor.value
            if not isinstance(cursor, ast.Name) or not isinstance(
                expression, (ast.Name, ast.Attribute)
            ):
                safe = False
                break
            expression_source = source(expression)
            key = names.get(expression_source)
            if key is None:
                base = expression.id if isinstance(expression, ast.Name) else expression.attr
                key = base
                suffix = 2
                while key in used:
                    key = f"{base}_{suffix}"
                    suffix += 1
                names[expression_source] = key
                used.add(key)
                arguments.append((key, expression_source))
            chunks.append(f"%({key})s")
        if not safe:
            continue
        replacement = f"{source(node.func)}({''.join(chunks)!r}"
        replacement += "".join(f", {key}={value}" for key, value in arguments) + ")"
        edits.append(
            (
                positions(node.lineno, node.col_offset),
                positions(node.end_lineno, node.end_col_offset),
                replacement,
                node.lineno,
            )
        )
    for start, end, replacement, line in reversed(edits):
        text = text[:start] + replacement + text[end:]
        logger.info(
            "[quality] Translation f-string converted to named placeholders. File %s:%s",
            path,
            line,
        )
    return text


def _extends_same_named_model(node):
    """Whether ``_name`` only keeps the identity of an inherited model."""
    declarations = {
        statement.targets[0].id: statement.value
        for statement in node.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    }
    name = declarations.get("_name")
    inherited = declarations.get("_inherit")
    if not (
        isinstance(name, ast.Constant)
        and isinstance(name.value, str)
        and inherited is not None
    ):
        return False
    if isinstance(inherited, ast.Constant) and isinstance(inherited.value, str):
        parents = {inherited.value}
    elif isinstance(inherited, (ast.List, ast.Tuple)):
        parents = {
            item.value
            for item in inherited.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
    else:
        return False
    return name.value in parents


def add_missing_model_descriptions(path, text):
    """Add a stable English description to explicitly named Odoo models."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    lines = text.splitlines(keepends=True)
    inserts = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if _extends_same_named_model(node):
            continue
        declarations = {
            statement.targets[0].id: statement
            for statement in node.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        }
        if "_description" in declarations:
            continue
        statement = declarations.get("_name")
        if not (
            statement
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        description = statement.value.value.replace(".", " ").replace("_", " ").title()
        indent = " " * statement.col_offset
        newline = "\r\n" if lines[statement.end_lineno - 1].endswith("\r\n") else "\n"
        inserts.append(
            (
                statement.end_lineno,
                f"{indent}_description = {description!r}{newline}",
                node.lineno,
            )
        )
    for line_index, value, line in reversed(inserts):
        lines.insert(line_index, value)
        logger.info(
            "[quality] Added model description derived from _name. File %s:%s",
            path,
            line,
        )
    return "".join(lines)


def clean_init_blank_lines(text):
    """Remove empty lines from import-only package initializers.

    A non-import statement may contain meaningful multiline text or deliberate
    spacing, so those files keep the regular leading/trailing cleanup only.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    if not all(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body):
        return text
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


_INTERNAL_HEADER = re.compile(
    r"^#\s*(?:Copyright\b|License\b|@author\b|Part of Odoo\b)", re.I
)


def remove_internal_headers(text):
    """Drop leading legal boilerplate from non-OCA internal modules."""
    lines = text.splitlines(keepends=True)
    index = 0
    matched = False
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
        elif _INTERNAL_HEADER.match(stripped):
            matched = True
            index += 1
        elif re.match(r"^#.*coding[:=]", stripped):
            index += 1
        else:
            break
    return "".join(lines[index:]) if matched else text


def clean_python_spacing(text):
    """Normalize blank space that can remain after Ruff removes an import."""
    text = text.lstrip("\r\n")
    return re.sub(r"\n(?:[ \t]*\n){3,}", "\n\n\n", text)


def finish_module(
    module, cosmetic=True, original_data=(), manifest_layout=False, default_website="",
    default_author="",
):
    from .analysis.models import unimported_python_files

    for path in unimported_python_files(module):
        logger.warning(
            "[quality] Python file/package is not reachable from the addon's "
            "__init__.py and is not loaded by Odoo; import it explicitly or "
            "remove the dead code. File %s:1",
            path,
        )
    manifest = module / "__manifest__.py"
    if manifest.exists():
        text = tools._read_content(manifest)
        # Run this before manifest formatting: formatting sees only the already
        # concatenated runtime value and can no longer recover the token split.
        text = repair_sql_apostrophes(manifest, text)
        check_adjacent_string_apostrophes(manifest, text)
        if cosmetic:
            text = remove_internal_headers(text)
        try:
            data = ast.literal_eval(text)
            from .manifest import inspect_keys

            unknown_keys, concatenated_keys = inspect_keys(text)
            concatenated_set = set(concatenated_keys)
            for key, line in unknown_keys:
                if (key, line) in concatenated_set:
                    continue
                logger.error(
                    "[quality] Unknown manifest key %r; check for a typo or a missing comma. File %s:%s",
                    key, manifest, line,
                )
            for key, line in concatenated_keys:
                logger.error(
                    "[quality] Manifest key %r is made of adjacent string literals; a comma is probably missing. File %s:%s",
                    key, manifest, line,
                )
            if not data.get("author") and not (
                default_author and cosmetic and manifest_layout
            ):
                logger.warning(
                    "[quality] Manifest has no 'author' key; Odoo 20 logs "
                    "\"Missing 'author' key\". File %s:1",
                    manifest,
                )
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
                    from .manifest import rewrite_list

                    # Normalize even when the official converter happened to
                    # append the replacement at the right logical position:
                    # it may still have put the first item directly after ``[``.
                    text = rewrite_list(
                        text, "data", values, normalize_multiline=True
                    )
            if cosmetic and manifest_layout:
                from .manifest import format_manifest

                text = format_manifest(
                    text,
                    default_website,
                    default_author=default_author,
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
        fixed = fix_invalid_escapes(path, repair_sql_apostrophes(path, text))
        fixed = migrate_simple_translation_fstrings(path, fixed)
        if cosmetic and path != manifest:
            fixed = add_missing_model_descriptions(path, fixed)
        if fixed != text:
            tools._write_content(path, fixed)
            text = fixed
        if path != manifest:
            check_python(path, text)
        if cosmetic:
            new = clean_python_spacing(remove_internal_headers(readable_strings(text)))
            if path.name == "__init__.py":
                new = clean_init_blank_lines(new)
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
