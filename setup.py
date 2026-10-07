# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import re

import setuptools

VERSION = re.search(
    r'__version__ = "([^"]+)"', open("odoo_module_migrate/__init__.py", encoding="utf-8").read()
).group(1)

setuptools.setup(
    name="odoo-module-migrator",
    version=VERSION,
    author="GRAP, Groupement Régional Alimentaire de Proximité",
    author_email="informatique@grap.coop",
    maintainer="PSAI Consulting",
    description="Migrate the source code of Odoo modules from a version to another (8.0 -> 20.0)",
    long_description=open("README.md", encoding='utf-8').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/PSAI-Consulting/odoo-module-migrator",
    # tools/ and tests/ are development tools: not shipped in the package
    packages=setuptools.find_packages(include=["odoo_module_migrate", "odoo_module_migrate.*"]),
    include_package_data=True,
    python_requires=">=3.12",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Framework :: Odoo",
        "Topic :: Software Development :: Code Generators",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Environment :: Console",
    ],
    install_requires=open("requirements.txt").read().splitlines(),
    entry_points=dict(
        console_scripts=[
            "odoo-module-migrate=odoo_module_migrate.__main__:main",
        ]
    ),
    keywords=[
        "Odoo Community Association (OCA)",
        "Odoo",
        "Migration",
        "Upgrade",
        "Module",
    ],
)
