# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import codecs
import os
import pathlib
import re
import shlex
import subprocess
import tempfile

from .config import _AVAILABLE_MIGRATION_STEPS
from .log import logger


def _get_available_init_version_names():
    return [x["init_version_name"] for x in _AVAILABLE_MIGRATION_STEPS]


def _get_available_target_version_names():
    return [x["target_version_name"] for x in _AVAILABLE_MIGRATION_STEPS]


def _get_latest_version_name():
    return _AVAILABLE_MIGRATION_STEPS[-1]["target_version_name"]


def _get_latest_version_code():
    return _AVAILABLE_MIGRATION_STEPS[-1]["target_version_code"]


def _run(args, path=None, check=True):
    """Run a command given as a list of arguments, without a shell.

    Returns the standard output (bytes). Portable on Windows and POSIX.
    """
    cwd = str(pathlib.Path(path).resolve()) if path else None
    logger.debug("Execute: %s (cwd=%s)", " ".join(map(str, args)), cwd)
    result = subprocess.run(
        [str(a) for a in args], cwd=cwd, capture_output=True, check=False
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args, result.stdout, result.stderr
        )
    return result.stdout


def _execute_shell(shell_command, path=None, raise_error=True):
    """Legacy helper kept for compatibility: runs a command line.

    The command is split into arguments (no shell), so it behaves the same
    under cmd.exe, PowerShell and POSIX shells. Chained commands (&&, |) are
    not supported anymore: use several calls instead.
    """
    args = shlex.split(shell_command, posix=os.name != "nt")
    args = [a.strip('"') for a in args]
    if raise_error:
        return _run(args, path=path, check=True)
    try:
        return _run(args, path=path, check=False)
    except FileNotFoundError:
        logger.debug("Command not found: %s", args[0])
        return b""


# ---------------------------------------------------------------------------
# File I/O preserving the original format (encoding, BOM, line endings)
# ---------------------------------------------------------------------------

# Options of the current run readable by the migration scripts, e.g.
# RUN_CONTEXT["upgrade_code"]: Odoo's official scripts will run afterwards
RUN_CONTEXT = {}

# path -> (encoding, bom, newline) of the file as it was first read
_FILE_FORMATS = {}
# absolute paths of the files written during the run (for the report)
_CHANGED_FILES = set()


def _detect_format(raw):
    bom = raw.startswith(codecs.BOM_UTF8)
    if bom:
        raw = raw[len(codecs.BOM_UTF8):]
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        # Legacy Windows files: keep their encoding when writing them back
        text = raw.decode("cp1252", errors="replace")
        encoding = "cp1252"
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    newline = "\r\n" if crlf > lf else "\n"
    return text, encoding, bom, newline


def _read_content(file_path):
    """Return the text of the file, with '\\n' line endings."""
    file_path = pathlib.Path(file_path)
    raw = file_path.read_bytes()
    text, encoding, bom, newline = _detect_format(raw)
    _FILE_FORMATS[str(file_path.resolve())] = (encoding, bom, newline)
    return text.replace("\r\n", "\n")


def _write_content(file_path, content):
    """Write the file atomically, in the format it had when it was read.

    Nothing is written if the content did not change.
    """
    file_path = pathlib.Path(file_path)
    key = str(file_path.resolve())
    if key in _FILE_FORMATS:
        encoding, bom, newline = _FILE_FORMATS[key]
    elif file_path.exists():
        _, encoding, bom, newline = _detect_format(file_path.read_bytes())
    else:
        encoding, bom, newline = "utf-8", False, "\n"

    content = content.replace("\r\n", "\n")
    if newline != "\n":
        content = content.replace("\n", newline)
    data = content.encode(encoding, errors="strict" if encoding == "utf-8" else "replace")
    if bom:
        data = codecs.BOM_UTF8 + data

    if file_path.exists() and file_path.read_bytes() == data:
        return
    _atomic_write_bytes(file_path, data)
    _FILE_FORMATS[key] = (encoding, bom, newline)
    _CHANGED_FILES.add(key)


def _atomic_write_bytes(file_path, data):
    file_path = pathlib.Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=str(file_path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, file_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


_TEXT_EXTENSIONS = (
    ".py", ".xml", ".js", ".csv", ".scss", ".css", ".po", ".pot", ".rst", ".md",
    ".txt", ".yml", ".yaml", ".json", ".html",
)


def snapshot_formats(module_path):
    """Return {path: (encoding, bom, newline)} for the text files of a module."""
    result = {}
    for path in pathlib.Path(module_path).rglob("*"):
        if path.is_file() and path.suffix in _TEXT_EXTENSIONS:
            _, encoding, bom, newline = _detect_format(path.read_bytes())
            result[str(path.resolve())] = (encoding, bom, newline)
    return result


def restore_formats(snapshot):
    """Give back their original BOM / line endings to the files of `snapshot`.

    Some scripts write files directly (lxml, open()): this guarantees that a
    CRLF file stays CRLF and that a BOM is never added nor lost.
    """
    for key, (encoding, bom, newline) in snapshot.items():
        path = pathlib.Path(key)
        if not path.exists():
            continue
        raw = path.read_bytes()
        text, cur_encoding, cur_bom, cur_newline = _detect_format(raw)
        if (cur_bom, cur_newline) == (bom, newline) or cur_encoding != "utf-8":
            continue
        _FILE_FORMATS[key] = (cur_encoding, bom, newline)
        _write_content(path, text)


def hash_tree(module_path):
    """{relative path: sha1} of the files of a module (for the report)."""
    import hashlib

    root = pathlib.Path(module_path)
    return {
        p.relative_to(root).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts
    }


def changed_files(before, after, ignore=()):
    """Sorted 'path (added|modified|deleted)' between two hash_tree()."""
    result = []
    for path in sorted(set(before) | set(after)):
        if path in ignore:
            continue
        if path not in before:
            result.append(f"{path} (ajouté)")
        elif path not in after:
            result.append(f"{path} (supprimé)")
        elif before[path] != after[path]:
            result.append(path)
    return result


def _rename_path(module_path, old_file_path, new_file_path, use_git=False):
    """Rename a file, with 'git mv' when possible to keep the history."""
    module_path = pathlib.Path(module_path)
    logger.info(
        "Renaming file: '%s' by '%s'"
        % (
            str(old_file_path).replace(str(module_path.resolve()), ""),
            str(new_file_path).replace(str(module_path.resolve()), ""),
        )
    )
    if use_git:
        try:
            _run(["git", "mv", old_file_path, new_file_path], path=module_path)
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("'git mv' failed, falling back to a plain rename")
    os.replace(old_file_path, new_file_path)
    key = str(pathlib.Path(old_file_path).resolve())
    if key in _FILE_FORMATS:
        _FILE_FORMATS[str(pathlib.Path(new_file_path).resolve())] = _FILE_FORMATS.pop(key)
    _CHANGED_FILES.add(str(pathlib.Path(new_file_path).resolve()))


def _replace_in_file(file_path, replaces, log_message=None):
    current_text = _read_content(file_path)
    new_text = current_text

    for old_term, new_term in replaces.items():
        new_text = re.sub(old_term, new_term or "", new_text)

    if new_text != current_text:
        if not log_message:
            log_message = f"Changing content of file: {pathlib.Path(file_path).name}"
        logger.info(log_message)
        _write_content(file_path, new_text)
    return new_text


def get_files(module_path, extensions):
    """Returns files with specified extensions in module_path."""
    module_dir = pathlib.Path(module_path)
    if not module_dir.is_dir():
        raise ValueError(f"'{module_path}' is not a valid directory")

    file_paths = []
    for ext in extensions:
        file_paths.extend(module_dir.rglob(f"*{ext}"))
    return [p for p in file_paths if not {".git", "__pycache__", "node_modules"}.intersection(p.relative_to(module_dir).parts)
            and not p.relative_to(module_dir).as_posix().startswith(("static/lib/", "static/libs/"))]
