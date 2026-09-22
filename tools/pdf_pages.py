"""Render every page of a PDF to PNG so the layout can be checked by eye.

    python tools/pdf_pages.py docs/doomsat-report.pdf out/pdfpages [scale]
"""
import os
import sys

import pypdfium2 as pdfium

pdf, out = sys.argv[1], sys.argv[2]
scale = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6
os.makedirs(out, exist_ok=True)
doc = pdfium.PdfDocument(pdf)
for i in range(len(doc)):
    page = doc[i]
    img = page.render(scale=scale).to_pil()
    img.save(os.path.join(out, f"page-{i + 1:02d}.png"))
print(len(doc), "pages ->", out)
