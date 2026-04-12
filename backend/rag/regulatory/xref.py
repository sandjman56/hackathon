"""Cross-reference extraction for chunk metadata.

Pulls every legal-citation-style reference out of a chunk's body so the
retriever can later prioritize related sections (a query about §1501.7
naturally elevates §§1502.4, 1508.25, etc., which are referenced from
within the §1501.7 text).

Patterns supported:

* CFR sections: ``§1501.3``, ``§ 1501.3(a)(2)(i)``, ``§§1501.7(b)(2)``
  (the closing paren depth is ignored — we keep just the section number).
* US Code citations: ``42 USC §4332``, ``5 U.S.C. § 5313``, ``42 USC § 4346a``.
* "Section NNN" of NEPA itself: ``section 102``, ``section 102(2)(C)``.

Self-references (the chunk's own citation) are excluded so the retriever
doesn't waste a slot pointing back at the same chunk.
"""
from __future__ import annotations

import re

# §NNNN.NN with optional repeated paren depth: §1501.7(b)(2)(i)
_RE_CFR_REF = re.compile(
    r"\u00a7{1,2}\s*(\d{4}\.\d+)(?:\([a-z0-9]+\))*"
)
# 42 USC § 4332 / 42 U.S.C. § 4332
_RE_USC_REF = re.compile(
    r"(\d{1,2})\s*U\.?\s*S\.?\s*C\.?\s*\u00a7?\s*(\d{3,5}[a-z]?)",
    re.IGNORECASE,
)
# "section 102" / "Section 102(2)(C)" — refers to NEPA statute sections
# (only digits 1-3 to avoid false positives on years and other numbers).
_RE_BARE_SECTION = re.compile(
    r"\b[Ss]ection\s+(\d{1,3})(?:\([a-z0-9]+\))*"
)

# PA Code: ``25 Pa. Code § 105.14`` / ``§ 105.14(b)`` (2-3 digit.digit+)
_RE_PA_CODE_REF = re.compile(
    r"(?:25\s*Pa\.?\s*Code\s+)?\u00a7{1,2}\s*(\d{2,3}\.\d+[a-z]?)(?:\([a-z0-9]+\))*"
)

# PA Statutes: ``32 P.S. §§ 693.1`` / ``35 P.S. § 691.1``
_RE_PA_STATUTE_REF = re.compile(
    r"(\d{1,2})\s*P\.?\s*S\.?\s*\u00a7{1,2}\s*([\d.]+)"
)


def extract_cross_references(text: str, self_citation: str | None = None) -> list[str]:
    """Find every legal cross-reference in ``text``.

    Args:
        text: Chunk body text (no breadcrumb).
        self_citation: The chunk's own citation, e.g. ``"40 CFR §1501.3"``.
            Excluded from the returned list.

    Returns:
        Deduped, ordered list of normalized citation strings (first
        occurrence wins). Examples: ``"40 CFR §1501.7"``, ``"42 USC §4332"``,
        ``"NEPA §102"``.
    """
    seen: list[str] = []

    def _add(c: str) -> None:
        if c == self_citation:
            return
        if c not in seen:
            seen.append(c)

    for m in _RE_CFR_REF.finditer(text):
        _add(f"40 CFR \u00a7{m.group(1)}")
    for m in _RE_USC_REF.finditer(text):
        title = m.group(1)
        section = m.group(2)
        _add(f"{title} USC \u00a7{section}")
    for m in _RE_BARE_SECTION.finditer(text):
        _add(f"NEPA \u00a7{m.group(1)}")

    for m in _RE_PA_CODE_REF.finditer(text):
        section = m.group(1)
        # Only treat as PA Code ref if section starts with 2-3 digit part
        # (avoids colliding with 4-digit CFR refs like §1501.3)
        if len(section.split(".")[0]) <= 3:
            _add(f"25 Pa. Code \u00a7 {section}")
    for m in _RE_PA_STATUTE_REF.finditer(text):
        title = m.group(1)
        section = m.group(2)
        _add(f"{title} P.S. \u00a7 {section}")

    return seen
