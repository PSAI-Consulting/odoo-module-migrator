#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Build the PDF of a Markdown document of docs/ (default: docs/COMMANDES.md).

    python tools/docs_pdf.py [docs/COMMANDES.md]

Markdown -> HTML (python-markdown, ``pip install markdown``) -> PDF printed by
a headless Chrome / Edge. The PDF is written next to the Markdown file.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

import markdown

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1f2328; }
h1 { font-size: 20pt; color: #714b67; border-bottom: 3px solid #714b67; padding-bottom: 4px; }
h2 { font-size: 14pt; color: #714b67; margin-top: 22px; border-bottom: 1px solid #d0d7de; padding-bottom: 2px;
     page-break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 16px; page-break-after: avoid; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f3f0f2; padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-left: 4px solid #714b67; border-radius: 4px;
      padding: 8px 10px; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; page-break-inside: avoid; font-size: 9.5pt; }
th { background: #714b67; color: white; text-align: left; }
th, td { border: 1px solid #d0d7de; padding: 4px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #faf8f9; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 18px 0; }
a { color: #0969da; text-decoration: none; }
"""

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "msedge",
]


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs/COMMANDES.md").resolve()
    body = markdown.markdown(source.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "toc"])
    html = (f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{source.stem}</title>'
            f"<style>{CSS}</style></head><body>{body}</body></html>")
    browser = next((b for b in BROWSERS if pathlib.Path(b).is_file() or shutil.which(b)), None)
    if not browser:
        raise SystemExit("Chrome or Edge is needed to print the PDF")
    target = source.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--user-data-dir={tmp}/profile", f"--print-to-pdf={target}", page.as_uri()],
            capture_output=True, timeout=120,
        )
    if not target.is_file():
        raise SystemExit("PDF not written: " + proc.stderr.decode("utf-8", "replace")[-2000:])
    print(target)


if __name__ == "__main__":
    main()
