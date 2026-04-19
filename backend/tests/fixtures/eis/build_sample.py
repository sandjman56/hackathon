"""Builds a synthetic EIS-style PDF in memory for parser tests.

The PDF mirrors the font-hierarchy conventions of a real FEIS chapter:
- Chapter heading: bold, 18pt, "Chapter 4: Environmental Resources"
- Section heading: bold, 14pt, "4.1 Water Resources"
- Subsection heading: bold, 12pt, "4.1.1 Surface Water"
- Body text: regular, 11pt
- Page footer: regular, 9pt, centered (parser must ignore)
"""
from __future__ import annotations

import pymupdf


BODY_FONT = "helv"
BOLD_FONT = "hebo"


def build_sample_eis_bytes() -> bytes:
    """Return raw bytes of a 3-chapter synthetic EIS PDF."""
    doc = pymupdf.open()

    def add_page(items: list[tuple[str, float, bool]]) -> None:
        page = doc.new_page(width=612, height=792)
        y = 72
        for text, size, bold in items:
            font = BOLD_FONT if bold else BODY_FONT
            page.insert_text((72, y), text, fontsize=size, fontname=font)
            y += size + 8
        page.insert_text((300, 770), f"Page {doc.page_count}",
                         fontsize=9, fontname=BODY_FONT)

    # --- Chapter 1
    add_page([
        ("Chapter 1: Purpose and Need", 18, True),
        ("1.1 Project Overview", 14, True),
        ("The proposed action would construct a new highway corridor "
         "across the eastern valley.", 11, False),
        ("The corridor is approximately 12 miles long.", 11, False),
        ("1.2 Need for the Project", 14, True),
        ("Traffic volumes have grown 34% over the last decade.",
         11, False),
    ])

    # --- Chapter 4
    add_page([
        ("Chapter 4: Environmental Resources", 18, True),
        ("4.1 Water Resources", 14, True),
        ("The project area includes three named streams and six "
         "jurisdictional wetland areas.", 11, False),
        ("4.1.1 Surface Water", 12, True),
        ("Streams in the project area are classified as warm-water "
         "fisheries under state regulation.", 11, False),
    ])
    add_page([
        ("4.1.2 Groundwater", 12, True),
        ("Primary aquifers beneath the corridor are confined "
         "sandstone units with recharge from surface infiltration.",
         11, False),
        ("4.2 Air Quality", 14, True),
        ("The project area is in attainment for all criteria "
         "pollutants.", 11, False),
    ])

    # --- Chapter 7
    add_page([
        ("Chapter 7: Effects", 18, True),
        ("7.1 Direct Effects", 14, True),
        ("Construction would permanently convert 240 acres of "
         "undeveloped land.", 11, False),
    ])

    buf = doc.write()
    doc.close()
    return bytes(buf)
