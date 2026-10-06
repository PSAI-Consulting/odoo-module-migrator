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
from . import manifest, tools
from .analysis import fields as analysis_fields

# Models whose XML / CSV records are converted by Odoo's official upgrade_code
# scripts (19.4-00-ir-access.py) or by the migrator fallback: not reported in
# data files by the rules, the records left are reported after the conversion
CONVERTED_BY_UPGRADE_CODE = {"ir.model.access", "ir.rule"}


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
    # {(model, field): source} removed fields whose values in <record> are
    # dropped, as Odoo did in its own data files (handle_fields)
    _DROPPED_RECORD_FIELDS: Dict[Tuple[str, str], str] = {}
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
            # sorted: same order on every OS (curated.yaml before generated.yaml)
            for filename in sorted(glob.glob(file_pattern)):
                with open(filename, encoding='utf-8') as f:
                    new_rules = yaml.safe_load(f)
                    if not new_rules:  # empty or comments only
                        continue
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
                try:
                    function(
                        logger=logger,
                        module_path=module_path,
                        module_name=module_name,
                        manifest_path=manifest_path,
                        migration_steps=migration_steps,
                        tools=tools,
                    )
                except Exception as e:  # noqa: BLE001 - one rule must not stop the migration
                    logger.error(
                        "Migration step %s.%s failed, it was skipped (%s: %s): check by hand."
                        " File %s" % (
                            os.path.basename(inspect.getfile(self.__class__)),
                            function.__name__, type(e).__name__, e, module_path / "__manifest__.py",
                        )
                    )
                    logger.debug(traceback.format_exc())

        # After the dedicated transformations (e.g. res.groups privileges):
        # only what is left is renamed / reported
        self.handle_fields(module_path)

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

        rules = self._file_rules(extension)
        new_text = _replace_in_file(
            absolute_file_path, rules["replaces"], "Change file content of %s" % filename
        )

        # Report obsolete patterns still present, with their first line
        for level, patterns in (("error", rules["errors"]), ("warning", rules["warnings"])):
            for pattern, message in patterns.items():
                match = re.search(pattern, new_text)
                if match:
                    line = new_text.count("\n", 0, match.start()) + 1
                    getattr(logger, level)(
                        "%s. File %s:%s" % (message.rstrip(". "), absolute_file_path, line)
                    )

    def _file_rules(self, extension: str) -> Dict[str, Dict[str, str]]:
        """Replaces / errors / warnings for a file extension (computed once).

        Fields are not here: see handle_fields(), which knows the models.
        """
        cache = self.__dict__.setdefault("_rules_cache", {})
        if extension not in cache:
            renamed_models = self.handle_renamed_models(self._RENAMED_MODELS)
            removed = self._REMOVED_MODELS
            if extension in (".xml", ".csv"):
                # records converted afterwards by Odoo's official scripts (or
                # by the fallback of migrate_190_200): the ones left are
                # reported once converted (Migration._check_access_records_left)
                removed = [r for r in removed if r[0] not in CONVERTED_BY_UPGRADE_CODE]
            removed_models = self.handle_removed_models(removed)
            result = {}
            for kind, own in (
                ("replaces", self._TEXT_REPLACES),
                ("errors", self._TEXT_ERRORS),
                ("warnings", self._TEXT_WARNINGS),
            ):
                # Always work on copies: the rule dicts are shared between files
                rules = dict(own.get("*", {}))
                rules.update(own.get(extension, {}))
                rules.update(renamed_models.get(kind, {}))
                rules.update(removed_models.get(kind, {}))
                result[kind] = rules
            cache[extension] = result
        return cache[extension]

    def handle_fields(self, module_path: pathlib.Path) -> None:
        """Renamed fields are renamed and removed fields reported, only where
        the model is known (see analysis/fields.py): no false positive."""
        # First rule wins: curated.yaml (hand verified) is loaded before
        # generated.yaml (alphabetical order of the rule files)
        renames = {}
        for r in self._RENAMED_FIELDS:
            if len(r) > 2 and re.fullmatch(r"[A-Za-z_]\w*", str(r[2] or "")):
                renames.setdefault((r[0], r[1]), r[2])
        sources = {(r[0], r[1]): (r[-1] if len(r) > 3 else "") for r in self._RENAMED_FIELDS}
        # a renamed field is not removed (e.g. curated.yaml vs generated.yaml)
        removed = {}
        for r in self._REMOVED_FIELDS:
            if (r[0], r[1]) not in renames:
                removed.setdefault((r[0], r[1]), r[2] if len(r) > 2 else "")
        if not renames and not removed:
            return
        renames = analysis_fields.with_delegation(renames)
        removed = {
            k: v for k, v in analysis_fields.with_delegation(removed).items() if k not in renames
        }
        files = [
            p for p in tools.get_files(module_path, (".py", ".xml"))
            if not self._is_skipped_folder(module_path, str(p.parent))
        ]
        # Fields defined by the module itself on a model are its own
        defined = set()
        # comodels of the relational fields of the module: their sub-views
        # in the XML views can be checked
        comodels = {}
        for path in files:
            if path.suffix == ".py":
                comodels.update(analysis_fields.python_comodels(_read_content(path)))
        parsed = {}
        for path in files:
            text = _read_content(path)
            if path.suffix == ".py":
                usages, fields_by_model = analysis_fields.python_usages(text)
                defined.update((m, f) for m, fs in fields_by_model.items() for f in fs)
            else:
                usages = analysis_fields.xml_usages(text, comodels)
            parsed[path] = (text, usages)

        for path, (text, usages) in parsed.items():
            usages = [u for u in usages if (u.model, u.field) not in defined]
            new_text, count = analysis_fields.apply_renames(text, usages, renames)
            if count:
                _write_content(path, new_text)
                done = sorted({(u.model, u.field) for u in usages if (u.model, u.field) in renames})
                logger.info(
                    "Renamed fields %s in %s (%d place(s))" % (
                        ", ".join("%s.%s -> %s" % (m, f, renames[(m, f)]) for m, f in done),
                        path, count,
                    )
                )
            if path.suffix == ".xml" and removed:
                if count:  # positions changed with the renames
                    text = new_text
                    usages = [
                        u for u in analysis_fields.xml_usages(text, comodels)
                        if (u.model, u.field) not in defined
                    ]
                # displayed fields that do not exist anymore: removed from views
                text_after, dropped = analysis_fields.remove_displayed_fields(
                    text, usages, removed
                )
                if dropped:
                    _write_content(path, text_after)
                    for usage in dropped:
                        logger.warning(
                            "Field %s.%s was removed: its display was removed from the view,"
                            " check what replaces it%s. File %s:%s" % (
                                usage.model, usage.field,
                                " - %s" % removed[(usage.model, usage.field)]
                                if removed[(usage.model, usage.field)] else "",
                                path, usage.line,
                            )
                        )
                    # positions changed
                    usages = [
                        u for u in analysis_fields.xml_usages(text_after, comodels)
                        if (u.model, u.field) not in defined
                    ]
                # values of removed fields that Odoo dropped from its own data
                text_after, dropped = analysis_fields.remove_record_fields(
                    text_after, usages, self._DROPPED_RECORD_FIELDS
                )
                if dropped:
                    _write_content(path, text_after)
                    for usage in dropped:
                        logger.info(
                            "Value of the removed field %s.%s dropped (%s). File %s:%s" % (
                                usage.model, usage.field,
                                self._DROPPED_RECORD_FIELDS[(usage.model, usage.field)],
                                path, usage.line,
                            )
                        )
                    usages = [u for u in usages if u not in dropped]
            for usage in usages:
                key = (usage.model, usage.field)
                if key in removed:
                    level = "error" if path.suffix == ".xml" else "warning"
                    getattr(logger, level)(
                        "Field %s.%s was removed (%s)%s. File %s:%s" % (
                            usage.model, usage.field, usage.context,
                            " - %s" % removed[key] if removed[key] else "", path, usage.line,
                        )
                    )
                elif key in sources and key not in renames:
                    logger.warning(
                        "Field %s.%s was renamed to %s: update it by hand (%s). File %s:%s" % (
                            usage.model, usage.field,
                            [r[2] for r in self._RENAMED_FIELDS if (r[0], r[1]) == key][0],
                            usage.context, path, usage.line,
                        )
                    )

    def handle_deprecated_modules(self, manifest_path: pathlib.Path, deprecated_modules: List[Any]) -> None:
        """Rewrite the 'depends' of the manifest for removed / renamed /
        merged modules (rules of deprecated_modules/migrate_XXX_YYY/*.yaml)."""
        if not deprecated_modules or not manifest_path or not manifest_path.exists():
            return
        text = _read_content(manifest_path)
        try:
            depends = manifest.get_depends(text)
            new_depends, messages = manifest.apply_module_rules(depends, deprecated_modules)
            if new_depends != depends:
                text = manifest.rewrite_depends(text, new_depends)
        except manifest.ManifestError as e:
            logger.error("%s: dependencies not checked (%s)", manifest_path, e)
            return
        for level, message in messages:
            getattr(logger, level)("%s. File %s" % (message, manifest_path))
        _write_content(manifest_path, text)

    def handle_renamed_models(self, renamed_models: List[Tuple]) -> Dict[str, Any]:
        """Returns dictionary of all replaces / warnings / errors produced by a model renamed."""
        res = {"replaces": {}, "warnings": {}, "errors": {}}
        # first rule wins (curated.yaml is loaded before generated.yaml)
        for old_model_name, new_model_name, more_info in reversed(renamed_models):
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
        # first rule wins (curated.yaml is loaded before generated.yaml)
        for model_name, more_info in reversed(removed_models):
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
