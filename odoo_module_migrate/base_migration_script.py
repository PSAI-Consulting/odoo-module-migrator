import os
import re
import pathlib
import traceback
import inspect
import glob
import yaml
import importlib
import copy
from typing import Dict, List, Any, Tuple

from .config import _ALLOWED_EXTENSIONS
from .tools import _rename_path, _replace_in_file, _read_content, _write_content
from .log import logger
from . import tools


class BaseMigrationScript:
    _TEXT_REPLACES: Dict[str, Any] = {}
    _TEXT_ERRORS: Dict[str, Any] = {}
    _TEXT_WARNINGS: Dict[str, Any] = {}
    _DEPRECATED_MODULES: List[Any] = []
    _FILE_RENAMES: Dict[str, str] = {}
    _REMOVED_FIELDS: List[Tuple] = []
    _RENAMED_FIELDS: List[Tuple] = []
    _RENAMED_MODELS: List[Tuple] = []
    _REMOVED_MODELS: List[Tuple] = []
    _GLOBAL_FUNCTIONS: List[Any] = []  # [function_object]
    # Folders never migrated (third-party code), matched on path components
    _SKIP_FOLDERS: List[str] = ["static/lib", "static/libs", "node_modules", "__pycache__", ".git"]
    _module_path: str = ""

    def __init__(self):
        # Deepcopy to ensure isolation and preserve subclass data defined in class attributes
        self._TEXT_REPLACES = copy.deepcopy(getattr(self, '_TEXT_REPLACES', {}))
        self._TEXT_ERRORS = copy.deepcopy(getattr(self, '_TEXT_ERRORS', {}))
        self._TEXT_WARNINGS = copy.deepcopy(getattr(self, '_TEXT_WARNINGS', {}))
        self._DEPRECATED_MODULES = copy.deepcopy(getattr(self, '_DEPRECATED_MODULES', []))
        self._FILE_RENAMES = copy.deepcopy(getattr(self, '_FILE_RENAMES', {}))
        self._REMOVED_FIELDS = copy.deepcopy(getattr(self, '_REMOVED_FIELDS', []))
        self._RENAMED_FIELDS = copy.deepcopy(getattr(self, '_RENAMED_FIELDS', []))
        self._RENAMED_MODELS = copy.deepcopy(getattr(self, '_RENAMED_MODELS', []))
        self._REMOVED_MODELS = copy.deepcopy(getattr(self, '_REMOVED_MODELS', []))
        self._GLOBAL_FUNCTIONS = copy.deepcopy(getattr(self, '_GLOBAL_FUNCTIONS', []))
        self._module_path = ""
        self._rules_parsed = False

    def parse_rules(self) -> None:
        # Rules are loaded once per script instance: run() is called once per
        # module, and parsing again would duplicate rules and functions.
        if self._rules_parsed:
            return
        self._rules_parsed = True
        script_file = inspect.getfile(self.__class__)
        migrate_from_to = os.path.basename(script_file).split(".")[0]
        migration_scripts_dir = os.path.dirname(script_file)

        TYPE_ARRAY = "TYPE_ARRAY"
        TYPE_DICT = "TYPE_DICT"
        TYPE_DICT_OF_DICT = "TYPE_DICT_OF_DICT"
        rules = {
            # {filetype: {regex: replacement}}
            "_TEXT_REPLACES": {
                "type": TYPE_DICT_OF_DICT,
                "doc": {},
            },
            # {filetype: {regex: message}}
            "_TEXT_ERRORS": {
                "type": TYPE_DICT_OF_DICT,
                "doc": {},
            },
            # {filetype: {regex: message}}
            "_TEXT_WARNINGS": {
                "type": TYPE_DICT_OF_DICT,
                "doc": {},
            },
            # [(module, why, ...)]
            "_DEPRECATED_MODULES": {
                "type": TYPE_ARRAY,
                "doc": [],
            },
            # {old_name: new_name}
            "_FILE_RENAMES": {
                "type": TYPE_DICT,
                "doc": {},
            },
            # [(model_name, field_name, more_info), ...)]
            "_REMOVED_FIELDS": {
                "type": TYPE_ARRAY,
                "doc": [],
            },
            # [(model_name, old_field_name, new_field_name, more_info), ...)]
            "_RENAMED_FIELDS": {
                "type": TYPE_ARRAY,
                "doc": [],
            },
            # [(old.model.name, new.model.name, more_info)]
            "_RENAMED_MODELS": {
                "type": TYPE_ARRAY,
                "doc": [],
            },
            # [(old.model.name, more_info)]
            "_REMOVED_MODELS": {
                "type": TYPE_ARRAY,
                "doc": [],
            },
        }
        # read
        for rule_name, rule_data in rules.items():
            rule_folder = rule_name[1:].lower()
            file_pattern = os.path.join(migration_scripts_dir, rule_folder, migrate_from_to, "*.yaml")
            for filename in glob.glob(file_pattern):
                with open(filename, encoding='utf-8') as f:
                    new_rules = yaml.safe_load(f)
                    if rule_data["type"] == TYPE_DICT_OF_DICT:
                        for f_type, data in new_rules.items():
                            if f_type not in rule_data["doc"]:
                                rule_data["doc"][f_type] = {}
                            rule_data["doc"][f_type].update(data)
                    elif rule_data["type"] == TYPE_DICT:
                        rule_data["doc"].update(new_rules)
                    elif rule_data["type"] == TYPE_ARRAY:
                        rule_data["doc"].extend(new_rules)
        # extend
        for rule_name, data in rules.items():
            rtype = data["type"]
            doc = data.get("doc")
            if not doc:
                continue

            rvalues = getattr(self, rule_name)
            if rtype == TYPE_ARRAY:
                rvalues.extend(doc)
            elif rtype == TYPE_DICT:
                rvalues.update(doc)
            else:
                # TYPE_DICT_OF_DICT
                for filetype, values in doc.items():
                    rvalues.setdefault(filetype, {})
                    rvalues[filetype].update(values or {})

        file_pattern = os.path.join(migration_scripts_dir, "python_scripts", migrate_from_to, "*.py")
        for path in glob.glob(file_pattern):
            module_name = os.path.basename(path).split(".")[0]
            module_name = ".".join(
                [
                    "odoo_module_migrate.migration_scripts.python_scripts",
                    migrate_from_to,
                    module_name,
                ]
            )
            module = importlib.import_module(module_name)
            for name, value in inspect.getmembers(module, inspect.isfunction):
                if not name.startswith("_"):
                    self._GLOBAL_FUNCTIONS.append(value)

    def run(
        self,
        module_path: pathlib.Path,
        manifest_path: pathlib.Path,
        module_name: str,
        migration_steps: List[Any],
        directory_path: pathlib.Path,
        commit_enabled: bool,
    ) -> None:
        logger.debug(
            "Running %s script" % os.path.basename(inspect.getfile(self.__class__))
        )
        self.parse_rules()
        manifest_path = self._get_correct_manifest_path(
            manifest_path, self._FILE_RENAMES
        )
        for root, directories, filenames in os.walk(module_path.resolve()):
            directories[:] = [
                d for d in directories
                if not self._is_skipped_folder(module_path, os.path.join(root, d))
            ]

            for filename in filenames:
                extension = os.path.splitext(filename)[1]
                if extension not in _ALLOWED_EXTENSIONS:
                    continue
                self.process_file(
                    root,
                    filename,
                    extension,
                    self._FILE_RENAMES,
                    directory_path,
                    commit_enabled,
                )

        self.handle_deprecated_modules(manifest_path, self._DEPRECATED_MODULES)

        if self._GLOBAL_FUNCTIONS:
            for function in self._GLOBAL_FUNCTIONS:
                function(
                    logger=logger,
                    module_path=module_path,
                    module_name=module_name,
                    manifest_path=manifest_path,
                    migration_steps=migration_steps,
                    tools=tools,
                )

    def process_file(
        self, 
        root: str, 
        filename: str, 
        extension: str, 
        file_renames: Dict[str, str], 
        directory_path: pathlib.Path, 
        commit_enabled: bool
    ) -> None:
        absolute_file_path = os.path.join(root, filename)
        logger.debug("Migrate '%s' file" % absolute_file_path)

        # Rename file, if required
        new_name = file_renames.get(filename)
        if new_name:
            self._rename_file(
                directory_path,
                absolute_file_path,
                os.path.join(root, new_name),
                commit_enabled,
            )
            # Update path after rename
            absolute_file_path = os.path.join(root, new_name)
            filename = new_name # ensure filename is updated for subsequent checks

        removed_fields = self.handle_removed_fields(self._REMOVED_FIELDS)
        renamed_fields = self.handle_renamed_fields(self._RENAMED_FIELDS)
        renamed_models = self.handle_renamed_models(self._RENAMED_MODELS)
        removed_models = self.handle_removed_models(self._REMOVED_MODELS)

        # Operate changes in the file (replacements, removals)
        # Always work on copies: the rule dicts are shared between files
        replaces = dict(self._TEXT_REPLACES.get("*", {}))
        replaces.update(self._TEXT_REPLACES.get(extension, {}))
        replaces.update(renamed_models.get("replaces", {}))
        replaces.update(removed_models.get("replaces", {}))

        new_text = _replace_in_file(
            absolute_file_path, replaces, "Change file content of %s" % filename
        )

        # Display errors if the new content contains some obsolete pattern
        errors = dict(self._TEXT_ERRORS.get("*", {}))
        errors.update(self._TEXT_ERRORS.get(extension, {}))
        errors.update(renamed_models.get("errors", {}))
        errors.update(removed_models.get("errors", {}))
        for pattern, error_message in errors.items():
            if re.findall(pattern, new_text):
                logger.error(error_message + "\nFile " + os.path.join(root, filename))

        warnings = dict(self._TEXT_WARNINGS.get("*", {}))
        warnings.update(self._TEXT_WARNINGS.get(extension, {}))
        warnings.update(removed_fields.get("warnings", {}))
        warnings.update(renamed_fields.get("warnings", {}))
        warnings.update(renamed_models.get("warnings", {}))
        warnings.update(removed_models.get("warnings", {}))
        for pattern, warning_message in warnings.items():
            if re.findall(pattern, new_text):
                logger.warning(warning_message + ". File " + root + os.sep + filename)

    def handle_removed_fields(self, removed_fields: List[Tuple]) -> Dict[str, Any]:
        """Give warnings if field_name is found on the code."""
        res = {}
        for model_name, field_name, more_info in removed_fields:
            msg = "On the model %s, the field %s was deprecated.%s" % (
                model_name,
                field_name,
                " %s" % more_info if more_info else "",
            )
            res[r"""(['"]{0}['"]|\.{0}[\s,=])""".format(field_name)] = msg
        return {"warnings": res}

    def handle_renamed_fields(self, removed_fields: List[Tuple]) -> Dict[str, Any]:
        """Give warnings if old_field_name is found on the code."""
        res = {}
        for model_name, old_field_name, new_field_name, more_info in removed_fields:
            msg = "On the model %s, the field %s was renamed to %s.%s" % (
                model_name,
                old_field_name,
                new_field_name,
                " %s" % more_info if more_info else "",
            )
            res[r"""(['"]{0}['"]|\.{0}[\s,=])""".format(old_field_name)] = msg
        return {"warnings": res}

    def handle_deprecated_modules(self, manifest_path: pathlib.Path, deprecated_modules: List[Any]) -> None:
        current_manifest_text = _read_content(manifest_path)
        new_manifest_text = current_manifest_text
        for items in deprecated_modules:
            old_module = items[0]
            action = items[1]
            new_module = items[2] if len(items) > 2 else None
            
            old_module_pattern = r"('|\"){0}('|\")".format(old_module)
            replace_pattern = ""
            if new_module:
                new_module_pattern = r"('|\"){0}('|\")".format(new_module)
                replace_pattern = r"\1{0}\2".format(new_module)

            if not re.findall(old_module_pattern, new_manifest_text):
                continue

            if action == "removed":
                logger.error("Depends on removed module '%s'" % (old_module))

            elif action == "renamed" and new_module:
                new_manifest_text = re.sub(
                    old_module_pattern, replace_pattern, new_manifest_text
                )
                logger.info(
                    "Replaced dependency of '%s' by '%s'." % (old_module, new_module)
                )

            elif action == "oca_moved" and new_module:
                new_manifest_text = re.sub(
                    old_module_pattern, replace_pattern, new_manifest_text
                )
                logger.warning(
                    "Replaced dependency of '%s' by '%s' (%s)\n"
                    "Check that '%s' is available on your system."
                    % (old_module, new_module, items[3] if len(items) > 3 else "moved", new_module)
                )

            elif action == "merged" and new_module:
                if not re.findall(new_module_pattern, new_manifest_text):
                    # adding dependency of the merged module
                    new_manifest_text = re.sub(
                        old_module_pattern, replace_pattern, new_manifest_text
                    )
                    logger.info(
                        "'%s' merged in '%s'. Replacing dependency."
                        % (old_module, new_module)
                    )
                else:
                    logger.error(
                        "'%s' merged in '%s'. You should remove the"
                        " dependency to '%s' manually."
                        % (old_module, new_module, old_module)
                    )
        if current_manifest_text != new_manifest_text:
            _write_content(manifest_path, new_manifest_text)

    def handle_renamed_models(self, renamed_models: List[Tuple]) -> Dict[str, Any]:
        """Returns dictionary of all replaces / warnings / errors produced by a model renamed."""
        res = {"replaces": {}, "warnings": {}, "errors": {}}
        for old_model_name, new_model_name, more_info in renamed_models:
            old_table_name = old_model_name.replace(".", "_")
            new_table_name = new_model_name.replace(".", "_")
            old_name_esc = re.escape(old_model_name)
            res["replaces"].update(
                {
                    r"\"%s\"" % old_name_esc: '"%s"' % new_model_name,
                    r"\'%s\'" % old_name_esc: "'%s'" % new_model_name,
                    r"\"%s\"" % old_table_name: '"%s"' % new_table_name,
                    r"\'%s\'" % old_table_name: "'%s'" % new_table_name,
                    r"model_%s\"" % old_table_name: 'model_%s"' % new_table_name,
                    r"model_%s\'" % old_table_name: "model_%s'" % new_table_name,
                    r"model_%s," % old_table_name: "model_%s," % new_table_name,
                }
            )
            msg = "The model %s has been renamed to %s.%s" % (
                old_model_name,
                new_model_name,
                (" %s" % more_info) or "",
            )
            res["warnings"].update(
                {
                    old_name_esc: msg,
                    old_table_name: msg,
                }
            )
        return res

    def handle_removed_models(self, removed_models: List[Tuple]) -> Dict[str, Any]:
        """Returns dictionary of all replaces / warnings / errors produced by a model removed/deprecated."""
        res = {"replaces": {}, "warnings": {}, "errors": {}}
        for model_name, more_info in removed_models:
            table_name = model_name.replace(".", "_")
            model_name_esc = re.escape(model_name)

            msg = "The model %s has been deprecated.%s" % (
                model_name,
                (" %s" % more_info) or "",
            )

            res["errors"].update(
                {
                    r"\"%s\"" % model_name_esc: msg,
                    r"\'%s\'" % model_name_esc: msg,
                    r"\"%s\"" % table_name: msg,
                    r"\'%s\'" % table_name: msg,
                    r"model_%s\"" % table_name: msg,
                    r"model_%s\'" % table_name: msg,
                    r"model_%s," % table_name: msg,
                }
            )
            res["warnings"].update(
                {
                    model_name_esc: msg,
                    table_name: msg,
                }
            )
        return res

    def _get_correct_manifest_path(self, manifest_path: pathlib.Path, file_renames: Dict[str, str]) -> pathlib.Path:
        current_manifest_file_name = os.path.basename(manifest_path.as_posix())
        if current_manifest_file_name in file_renames:
            new_manifest_file_name = manifest_path.as_posix().replace(
                current_manifest_file_name, file_renames[current_manifest_file_name]
            )
            manifest_path = pathlib.Path(new_manifest_file_name)
        return manifest_path

    def _is_skipped_folder(self, module_path, folder_path) -> bool:
        relative = pathlib.PurePath(os.path.relpath(folder_path, module_path)).as_posix()
        return any(
            relative == skip or relative.endswith("/" + skip)
            for skip in self._SKIP_FOLDERS
        )

    def _rename_file(self, module_path: pathlib.Path, old_file_path: str, new_file_path: str, commit_enabled: bool) -> None:
        """Rename a file, with 'git mv' when commits are enabled."""
        try:
            _rename_path(module_path, old_file_path, new_file_path, commit_enabled)
        except OSError:
            logger.error(traceback.format_exc())
