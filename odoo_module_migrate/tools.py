# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import subprocess
import re
import pathlib
import os

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


def _execute_shell(shell_command, path=None, raise_error=True):
    if path:
        path_str = str(path.resolve())
        if os.name == 'nt':
            shell_command = f'cd /d "{path_str}" && {shell_command}'
        else:
            shell_command = f"cd '{path_str}' && {shell_command}"
    logger.debug(f"Execute Shell:\n{shell_command}")
    if raise_error:
        return subprocess.check_output(shell_command, shell=True)
    else:
        return subprocess.run(shell_command, shell=True)


def _read_content(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def _write_content(file_path, content):
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def _replace_in_file(file_path, replaces, log_message=None):
    current_text = _read_content(file_path)
    new_text = current_text

    for old_term, new_term in replaces.items():
        new_text = re.sub(old_term, new_term or "", new_text)

    if new_text != current_text:
        if not log_message:
            log_message = f"Changing content of file: {file_path.name}"
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
    return file_paths
