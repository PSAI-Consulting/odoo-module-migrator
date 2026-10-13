from odoo_module_migrate.oca_generator import generate_oca_file_list


def test_manifest_is_never_executed_when_generating_oca_list(tmp_path):
    module = tmp_path / "malicious"
    module.mkdir()
    marker = tmp_path / "executed"
    (module / "__manifest__.py").write_text(
        "__import__('pathlib').Path(%r).write_text('bad') or "
        "{'author': 'Odoo Community Association (OCA)'}" % str(marker),
        encoding="utf-8",
    )

    generate_oca_file_list(tmp_path)

    assert not marker.exists()
