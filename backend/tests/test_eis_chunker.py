from rag.evaluation.chunker import (
    EisChunk,
    MAX_TOKENS,
    MIN_TOKENS,
    chunk_eis_sections,
    make_chunk_label,
)
from rag.evaluation.parser import RawEisSection


def _mk(section_number, body, pages=(1, 1), title="X",
        chapter=None, breadcrumb="X"):
    return RawEisSection(
        chapter=chapter or (section_number.split(".")[0] if section_number else None),
        section_number=section_number,
        section_title=title,
        breadcrumb=breadcrumb,
        body=body,
        page_start=pages[0],
        page_end=pages[1],
    )


def test_short_section_stays_whole():
    s = _mk("4.1", "Short body paragraph.")
    chunks = chunk_eis_sections([s])
    assert len(chunks) == 1
    assert chunks[0].total_chunks_in_section == 1
    assert chunks[0].chunk_index == 0


def test_long_section_splits():
    big_body = ("Paragraph line. " * 800)  # >> MAX_TOKENS (~2400 tokens)
    s = _mk("4.2", big_body)
    chunks = chunk_eis_sections([s])
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.total_chunks_in_section == len(chunks)


def test_paragraph_boundary_preferred_over_token_split():
    # Each paragraph ~800 tokens, total ~1600 — forces a split, and
    # paragraph boundary should be picked over token slicing.
    body = ("first para " * 400) + "\n\n" + ("second para " * 400)
    s = _mk("5.1", body)
    chunks = chunk_eis_sections([s])
    assert len(chunks) >= 2
    assert "first" in chunks[0].body
    assert "second" not in chunks[0].body


def test_has_table_hint_propagates():
    s = _mk("6.1", "body | col1 | col2 |\n| a | b |\n")
    s.has_table_hint = True
    chunks = chunk_eis_sections([s])
    assert chunks[0].has_table is True


def test_make_chunk_label_format():
    s = _mk("4.2.3", "body", pages=(142, 143), title="Groundwater")
    label = make_chunk_label(
        filename="ch-4-environmental-resources.pdf",
        section=s, chunk_index=1, total=5,
    )
    assert label == "ch-4-environmental-resources §4.2.3 [p.142-143] (2/5)"


def test_make_chunk_label_no_section_number():
    s = RawEisSection(
        chapter=None, section_number=None, section_title="Front matter",
        breadcrumb="Front matter", body="body", page_start=1, page_end=2,
    )
    label = make_chunk_label(filename="intro.pdf", section=s, chunk_index=0, total=1)
    assert "§intro" in label


def test_eis_chunk_citation_alias():
    s = _mk("4.1", "body")
    c = EisChunk(source=s, body="body")
    assert c.citation == "4.1"
    assert c.sources == [s]
