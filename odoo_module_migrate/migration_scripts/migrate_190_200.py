# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import ast
import csv
import io
import logging
import re
import tokenize
from typing import Any, List

from lxml import etree

from odoo_module_migrate.base_migration_script import BaseMigrationScript
from odoo_module_migrate.manifest import rewrite_list

# Odoo 20 replaces ir.model.access (CSV) and ir.rule (XML) by a single model,
# ir.access, loaded from security/ir.access.csv:
#   id,name,model_id/id,group_id/id,operation,domain
# - a row with a group is a *permission* (the group may do `operation` on the
#   records matching `domain`, all records when the domain is empty);
# - a row without group is a *restriction* (former global rule).
# The conversion below follows what Odoo did on its own modules:
# - ACL without group rule        -> permission without domain
# - ACL + group rule (same group) -> permission with the rule domain
# - global rule                   -> restriction
# - ACL without group (everyone)  -> permission for base.group_everyone
# - ACL with no permission        -> dropped

ACCESS_HEADER = ["id", "name", "model_id/id", "group_id/id", "operation", "domain"]
OPERATIONS = (("c", "perm_create"), ("r", "perm_read"), ("u", "perm_write"), ("d", "perm_unlink"))
RE_REF = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
RE_RULE_RECORD = re.compile(r"[ \t]*<record\b[^>]*\bmodel=['\"]ir\.rule['\"][^>]*>.*?</record>[ \t]*\n?", re.S)
TRUE_VALUES = {"1", "true", "True"}


def _one_line_expression(value: str) -> str:
    """Collapse Python expression layout without changing string literals."""
    tokens = tokenize.generate_tokens(io.StringIO(value).readline)
    kept = [
        (token.type, token.string)
        for token in tokens
        if token.type
        not in {
            tokenize.ENCODING,
            tokenize.ENDMARKER,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.NEWLINE,
            tokenize.NL,
        }
    ]
    return tokenize.untokenize(kept).strip()


def _qualify(xmlid: str, module_name: str) -> str:
    xmlid = (xmlid or "").strip()
    return xmlid if not xmlid or "." in xmlid else f"{module_name}.{xmlid}"


def _ops_string(ops: set) -> str:
    return "".join(letter for letter, _perm in OPERATIONS if letter in ops)


def _read_acl(acl_file, module_name: str) -> list:
    rows = []
    reader = csv.DictReader(io.StringIO(acl_file.read_text(encoding="utf-8-sig")))
    for row in reader:
        row = {k.strip().replace(":id", "/id"): (v or "").strip() for k, v in row.items() if k}
        ops = {letter for letter, perm in OPERATIONS if row.get(perm, "0") in TRUE_VALUES}
        rows.append({
            "id": row["id"],
            "name": row.get("name") or row["id"],
            "model": _qualify(row.get("model_id/id", ""), module_name),
            "group": _qualify(row.get("group_id/id", ""), module_name),
            "ops": ops,
        })
    return rows


def _rewrite_manifest_access_entries(manifest_path, module_path, removed, replacement=None):
    """Remove old ACL files and optionally insert their Odoo 20 replacement."""
    manifest = manifest_path.read_text(encoding="utf-8")
    data = list(ast.literal_eval(manifest).get("data", []))
    old_entries = {
        path.relative_to(module_path).as_posix() for path in removed
    }
    rewritten = []
    inserted = False
    for value in data:
        if value in old_entries:
            if replacement and not inserted and replacement not in rewritten:
                rewritten.append(replacement)
                inserted = True
            continue
        if value == replacement:
            inserted = True
        rewritten.append(value)
    if replacement and not inserted:
        rewritten.insert(0, replacement)
    if rewritten != data:
        tools_text = rewrite_list(manifest, "data", rewritten)
        manifest_path.write_text(tools_text, encoding="utf-8")


def _sanitize_acl_files(acl_files, module_path, module_name, manifest_path, logger):
    """Drop ACL updates whose XML ID belongs to another module.

    A dotted ID in the first CSV column updates an existing external record.
    Carrying that row to ir.access would silently alter an Odoo/OCA module's
    standard permissions. Empty source files are removed from the manifest so
    the official converter cannot leave a stale entry behind.
    """
    kept_files = []
    for path in acl_files:
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames or []
        rows = list(reader)
        local = []
        for line, row in enumerate(rows, 2):
            xmlid = (row.get("id") or "").strip()
            owner = xmlid.split(".", 1)[0] if "." in xmlid else module_name
            if owner != module_name:
                logger.error(
                    "[ir.access] ACL %s belongs to external module %s and was not "
                    "converted; overriding another module's Odoo 20 access is unsafe. "
                    "File %s:%s",
                    xmlid,
                    owner,
                    path,
                    line,
                )
                continue
            local.append(row)
        if local:
            if len(local) != len(rows):
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(local)
                path.write_text(buffer.getvalue(), encoding="utf-8")
            kept_files.append(path)
            continue
        path.unlink()
        _rewrite_manifest_access_entries(
            manifest_path, module_path, [path], replacement=None
        )
        logger.info("[ir.access] Removed empty ACL file from the manifest: %s", path)
    return kept_files


def _read_rules(xml_files, module_name: str, logger: logging.Logger) -> list:
    rules = []
    for xml_file in xml_files:
        try:
            tree = etree.parse(str(xml_file))
        except etree.XMLSyntaxError:
            continue
        for record in tree.iter("record"):
            if record.get("model") != "ir.rule":
                continue
            fields = {f.get("name"): f for f in record.iter("field")}
            model_field = fields.get("model_id")
            domain_field = fields.get("domain_force")
            groups_field = fields.get("groups")
            ops = set()
            for letter, perm in OPERATIONS:
                field = fields.get(perm)
                value = (field.get("eval") or field.text or "True").strip() if field is not None else "True"
                if value in TRUE_VALUES:
                    ops.add(letter)
            domain = ""
            if domain_field is not None:
                domain = _one_line_expression(
                    (domain_field.get("eval") or domain_field.text or "").strip()
                )
            if domain.replace(" ", "") in ("[(1,'=',1)]", '[(1,"=",1)]', "[]"):
                domain = ""
            groups = []
            if groups_field is not None:
                groups = [_qualify(g, module_name) for g in RE_REF.findall(groups_field.get("eval") or "")]
            name_field = fields.get("name")
            rules.append({
                "id": record.get("id"),
                "name": (name_field.text or "").strip() if name_field is not None else record.get("id"),
                "model": _qualify(model_field.get("ref") if model_field is not None else "", module_name),
                "groups": groups,
                "ops": ops,
                "domain": domain,
                "file": xml_file,
            })
            if fields.get("active") is not None:
                logger.warning(f"[ir.access] Rule {record.get('id')} has an 'active' field: check it by hand ({xml_file})")
    return rules


def convert_access_to_ir_access(
    logger: logging.Logger, module_path: Any, module_name: str, manifest_path: Any, migration_steps: List[Any], tools: Any
) -> None:
    """Convert ir.model.access.csv + ir.rule records into security/ir.access.csv

    Fallback only: when the Odoo sources are given (--odoo-root), Odoo's
    official 19.4-00-ir-access.py does it, taking the group hierarchy
    (implied_ids) into account, which this function does not.
    """
    acl_files = [f for f in tools.get_files(module_path, (".csv",)) if f.name == "ir.model.access.csv"]
    acl_files = _sanitize_acl_files(
        acl_files, module_path, module_name, manifest_path, logger
    )
    if tools.RUN_CONTEXT.get("upgrade_code"):
        return
    logger.warning(
        "[ir.access] Fallback conversion (implied groups are ignored): give "
        "--odoo-root to use Odoo's official 19.4-00-ir-access.py instead"
    )
    xml_files = tools.get_files(module_path, (".xml",))
    rules = _read_rules(xml_files, module_name, logger)
    if not acl_files and not rules:
        return

    acls = []
    for acl_file in acl_files:
        acls += _read_acl(acl_file, module_name)

    access_rows = []
    covered = {}  # (model, group) -> operations already granted through a rule
    acl_ops = {}
    for acl in acls:
        acl_ops.setdefault((acl["model"], acl["group"]), set()).update(acl["ops"])

    for rule in rules:
        if not rule["ops"]:
            continue
        if not rule["groups"]:
            access_rows.append([rule["id"], rule["name"], rule["model"], "", _ops_string(rule["ops"]), rule["domain"]])
            continue
        for index, group in enumerate(rule["groups"]):
            ops = set(rule["ops"])
            if (rule["model"], group) in acl_ops:
                ops &= acl_ops[(rule["model"], group)]
            else:
                logger.warning(
                    f"[ir.access] Rule {rule['id']}: no ACL for group {group} on {rule['model']} in this module "
                    f"(implied group or ACL defined elsewhere): check the operations by hand"
                )
            if not ops:
                continue
            row_id = rule["id"] if len(rule["groups"]) == 1 else f"{rule['id']}_{index + 1}"
            access_rows.append([row_id, rule["name"], rule["model"], group, _ops_string(ops), rule["domain"]])
            covered.setdefault((rule["model"], group), set()).update(rule["ops"])

    for acl in acls:
        if not acl["group"]:
            # an empty group no longer means "everyone" (it means restriction)
            acl["group"] = "base.group_everyone"
            if acl["ops"]:
                logger.warning(f"[ir.access] ACL {acl['id']} had no group: converted to base.group_everyone")
        remaining = acl["ops"] - covered.get((acl["model"], acl["group"]), set())
        if remaining:
            access_rows.append([acl["id"], acl["name"], acl["model"], acl["group"], _ops_string(remaining), ""])

    security_dir = module_path / "security"
    security_dir.mkdir(exist_ok=True)
    target = security_dir / "ir.access.csv"
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(ACCESS_HEADER)
    writer.writerows(access_rows)
    tools._write_content(target, buffer.getvalue())
    logger.info(f"[ir.access] {len(access_rows)} access rows written in {target}")

    replacement = "security/ir.access.csv"
    _rewrite_manifest_access_entries(
        manifest_path, module_path, acl_files, replacement=replacement
    )
    for acl_file in acl_files:
        acl_file.unlink()

    # XML: drop the converted ir.rule records
    for xml_file in {rule["file"] for rule in rules}:
        content = tools._read_content(xml_file)
        new_content = RE_RULE_RECORD.sub("", content)
        if new_content != content:
            tools._write_content(xml_file, new_content)
            logger.info(f"[ir.access] ir.rule records removed from {xml_file}")


class MigrationScript(BaseMigrationScript):
    _GLOBAL_FUNCTIONS = [
        convert_access_to_ir_access,
    ]
    _DROPPED_RECORD_FIELDS = {
        # odoo 80e1a4464f75 '[REM] core,*: remove report_file field from
        # ir.actions.report': "no longer used by the QWeb reporting engine",
        # the <field name="report_file"> lines were deleted from the reports
        # of Odoo (45 files) without replacement
        ("ir.actions.report", "report_file"): "unused, odoo 80e1a4464f75",
    }
