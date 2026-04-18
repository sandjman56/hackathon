"""Build EIA Agent System presentation following the 24-880 template theme."""
import io
import os
import shutil
import zipfile

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt, Emu

# ── Template colors ──────────────────────────────────────────────────────────
BG        = RGBColor(0x1F, 0x28, 0x33)   # dark slate background
ORANGE    = RGBColor(0xF9, 0x73, 0x16)   # primary accent
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
GRAY_LT   = RGBColor(0xE5, 0xE7, 0xEB)   # body text
RED       = RGBColor(0xEF, 0x44, 0x44)
YELLOW    = RGBColor(0xEA, 0xB3, 0x08)
GREEN     = RGBColor(0x22, 0xC5, 0x5E)
CYAN      = RGBColor(0x06, 0xB6, 0xD3)
BLUE      = RGBColor(0x3B, 0x82, 0xF6)
DARK_CARD = RGBColor(0x2D, 0x37, 0x48)   # slightly lighter than BG for cards

W  = Inches(13.33)   # widescreen width
H  = Inches(7.5)     # widescreen height


# ── Helpers ──────────────────────────────────────────────────────────────────

def convert_potx_to_pptx(potx_path: str) -> Presentation:
    """Read a .potx template and repackage it as a .pptx in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(potx_path, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == '[Content_Types].xml':
                    data = data.replace(
                        b'presentationml.template.main+xml',
                        b'presentationml.presentation.main+xml',
                    )
                zout.writestr(item, data)
    buf.seek(0)
    return Presentation(buf)


def solid_fill(shape, color: RGBColor):
    """Fill a shape with a solid color."""
    fill = shape.fill
    fill.solid()
    fill.fore_color.rgb = color


def set_slide_bg(slide, color: RGBColor):
    """Set a slide background to a solid color."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_textbox(slide, text, left, top, width, height,
                font_size=18, bold=False, color=WHITE,
                align=PP_ALIGN.LEFT, wrap=True, italic=False) -> object:
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return txBox


def add_bullet_slide(prs, title_text: str, bullets: list[tuple]) -> object:
    """
    Add a standard content slide.
    bullets: list of (text, indent_level, color) — indent 0 = main, 1 = sub
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    set_slide_bg(slide, BG)

    # Orange top bar
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)

    # Title
    add_textbox(slide, title_text,
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)

    # Divider line
    line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(line, RGBColor(0x3D, 0x4A, 0x5C))

    # Bullet content
    txBox = slide.shapes.add_textbox(Inches(0.6), Inches(1.15), Inches(12.1), Inches(6.0))
    tf = txBox.text_frame
    tf.word_wrap = True

    first = True
    for text, level, color in bullets:
        if first:
            p = tf.paragraphs[0]
            first = False
        else:
            p = tf.add_paragraph()
        p.level = level
        p.space_before = Pt(4 if level == 0 else 2)
        indent_prefix = "    " * level
        bullet_char = "▸ " if level == 0 else "· "
        run = p.add_run()
        run.text = indent_prefix + bullet_char + text
        run.font.size = Pt(17 if level == 0 else 14)
        run.font.bold = (level == 0)
        run.font.color.rgb = color

    return slide


def add_two_col_slide(prs, title_text: str,
                      left_title: str, left_items: list[tuple],
                      right_title: str, right_items: list[tuple]) -> object:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, title_text,
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(line, RGBColor(0x3D, 0x4A, 0x5C))

    col_w = Inches(5.8)
    for col_x, col_title, items in [
        (Inches(0.6), left_title, left_items),
        (Inches(7.0), right_title, right_items),
    ]:
        # Column header
        hdr = slide.shapes.add_shape(1, col_x, Inches(1.1), col_w, Inches(0.4))
        solid_fill(hdr, DARK_CARD)
        add_textbox(slide, col_title, col_x + Inches(0.1), Inches(1.12),
                    col_w - Inches(0.2), Inches(0.36),
                    font_size=13, bold=True, color=ORANGE)

        txBox = slide.shapes.add_textbox(col_x, Inches(1.6), col_w, Inches(5.5))
        tf = txBox.text_frame
        tf.word_wrap = True
        first = True
        for text, level, color in items:
            if first:
                p = tf.paragraphs[0]
                first = False
            else:
                p = tf.add_paragraph()
            p.level = level
            p.space_before = Pt(3 if level == 0 else 1)
            prefix = ("▸ " if level == 0 else "  · ")
            run = p.add_run()
            run.text = prefix + text
            run.font.size = Pt(15 if level == 0 else 13)
            run.font.bold = (level == 0)
            run.font.color.rgb = color

    return slide


def add_image_placeholder(slide, label, left, top, width, height):
    """Add a dashed-border placeholder box for a screenshot."""
    box = slide.shapes.add_shape(1, left, top, width, height)
    fill = box.fill
    fill.solid()
    fill.fore_color.rgb = DARK_CARD
    box.line.color.rgb = ORANGE
    box.line.width = Pt(1.5)
    # Label
    add_textbox(slide, f"[ IMAGE PLACEHOLDER: {label} ]",
                left + Inches(0.1), top + height / 2 - Pt(20),
                width - Inches(0.2), Inches(0.5),
                font_size=11, color=ORANGE, align=PP_ALIGN.CENTER, italic=True)


# ── Build slides ─────────────────────────────────────────────────────────────

def build(potx_path: str, output_path: str):
    prs = convert_potx_to_pptx(potx_path)

    # Remove all existing slides from the template
    xml_slides = prs.slides._sldIdLst
    for sld_id in list(xml_slides):
        xml_slides.remove(sld_id)

    # ── SLIDE 1: Title ───────────────────────────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)

    # Full-width orange top strip
    top = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(1.6))
    solid_fill(top, ORANGE)

    # Title text on the strip
    add_textbox(slide, "EIA AGENT SYSTEM",
                Inches(0.7), Inches(0.2), Inches(11.5), Inches(1.0),
                font_size=40, bold=True, color=WHITE, align=PP_ALIGN.LEFT)

    add_textbox(slide, "Automated Environmental Impact Assessment via Multi-Agent AI Pipeline",
                Inches(0.7), Inches(1.8), Inches(11.5), Inches(0.9),
                font_size=22, bold=False, color=GRAY_LT, align=PP_ALIGN.LEFT)

    add_textbox(slide, "24-880 AI Agents for Engineers",
                Inches(0.7), Inches(2.9), Inches(11.5), Inches(0.5),
                font_size=18, bold=False, color=ORANGE)

    add_textbox(slide, "[ Group Member Name(s) ]",
                Inches(0.7), Inches(3.6), Inches(11.5), Inches(0.4),
                font_size=16, color=GRAY_LT)

    add_textbox(slide, "[ Presentation Date ]",
                Inches(0.7), Inches(4.1), Inches(11.5), Inches(0.4),
                font_size=16, color=GRAY_LT)

    # Bottom decorative bar
    bot = slide.shapes.add_shape(1, Inches(0), H - Inches(0.15), W, Inches(0.15))
    solid_fill(bot, ORANGE)

    # ── SLIDE 2: Problem Statement ───────────────────────────────────────────
    add_bullet_slide(prs, "Problem Statement", [
        ("Environmental reviews are a bottleneck for infrastructure", 0, WHITE),
        ("NEPA requires screening-level EA before major federal actions", 1, GRAY_LT),
        ("Involves querying 5+ federal databases, screening 100s of regulations, writing reports", 1, GRAY_LT),
        ("Typically takes weeks of expert analyst time per project", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Existing tools don't explain their reasoning", 0, WHITE),
        ("Black-box outputs are unusable in regulatory contexts", 1, GRAY_LT),
        ("Agencies require traceable citations and data-backed determinations", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Goal: automate EIA screening with explainable, confidence-aware AI", 0, ORANGE),
        ("Reduce time from weeks to minutes while preserving regulatory traceability", 1, GRAY_LT),
        ("Flag low-confidence cells for human review — keeps experts in the loop", 1, GRAY_LT),
    ])

    # ── SLIDE 3: System Architecture ─────────────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "System Architecture",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    # Architecture description
    arch_text = [
        ("React Frontend (Vite) — real-time SSE streaming UI", 0, WHITE),
        ("POST /api/run → FastAPI backend", 1, GRAY_LT),
        ("LangGraph orchestrates sequential 5-agent pipeline", 0, WHITE),
        ("Streaming events: agent_start, agent_step, agent_complete, cost", 1, GRAY_LT),
        ("Each agent output stored in PostgreSQL (JSONB) with cost metadata", 1, GRAY_LT),
        ("Switchable LLM providers: OpenAI, Anthropic, Ollama — no code changes", 0, WHITE),
        ("pgvector for regulatory RAG and EIS evaluation similarity search", 0, WHITE),
        ("Deployed on Render (backend + frontend + managed PostgreSQL)", 0, WHITE),
    ]
    txBox = slide.shapes.add_textbox(Inches(0.6), Inches(1.15), Inches(5.6), Inches(6.0))
    tf = txBox.text_frame
    tf.word_wrap = True
    first = True
    for text, level, color in arch_text:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_before = Pt(4 if level == 0 else 2)
        run = p.add_run()
        run.text = ("    " * level) + ("▸ " if level == 0 else "· ") + text
        run.font.size = Pt(15 if level == 0 else 13)
        run.font.bold = (level == 0)
        run.font.color.rgb = color

    add_image_placeholder(slide, "System architecture diagram / pipeline screenshot",
                          Inches(6.5), Inches(1.1), Inches(6.4), Inches(5.8))

    # ── SLIDE 4: The 5-Agent Pipeline ────────────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "The 5-Agent Pipeline",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    agents = [
        ("1  PROJECT PARSER", "Extracts structured metadata from natural language.\nOutputs: project_type, scale, location, actions", BLUE),
        ("2  ENVIRONMENTAL DATA", "Queries 5 federal REST APIs by GPS coordinates.\nUSFWS species · NWI wetlands · FEMA flood · USDA farmland · EJScreen\nNo LLM — pure API orchestration", CYAN),
        ("3  REGULATORY SCREENING", "RAG over NEPA guidance docs + CFR parts.\nProject-scoped: only regulations assigned to this project.\nOutputs: name, jurisdiction, citation, why triggered", GREEN),
        ("4  IMPACT ANALYSIS", "Cross-references actions × categories × regulations.\nLLM produces significance + confidence + mitigation per cell.\nFlags cells with confidence < 0.6 for human review", ORANGE),
        ("5  REPORT SYNTHESIS", "Generates 10-section NEPA EA narrative.\nSections 1–7 via LLM; Sections 8–10 templated.\nFull DOCX-ready output with inline citations", YELLOW),
    ]

    box_w = Inches(2.3)
    box_h = Inches(5.4)
    gap   = Inches(0.22)
    start_x = Inches(0.5)
    for i, (name, desc, color) in enumerate(agents):
        bx = start_x + i * (box_w + gap)
        box = slide.shapes.add_shape(1, bx, Inches(1.12), box_w, box_h)
        solid_fill(box, DARK_CARD)
        box.line.color.rgb = color
        box.line.width = Pt(1.5)

        # Agent number/name header
        hdr = slide.shapes.add_shape(1, bx, Inches(1.12), box_w, Inches(0.45))
        solid_fill(hdr, color)
        add_textbox(slide, name, bx + Inches(0.08), Inches(1.14),
                    box_w - Inches(0.16), Inches(0.4),
                    font_size=10, bold=True, color=WHITE)

        add_textbox(slide, desc,
                    bx + Inches(0.12), Inches(1.65),
                    box_w - Inches(0.24), Inches(4.6),
                    font_size=11, color=GRAY_LT, wrap=True)

    # Arrow labels between boxes
    add_textbox(slide, "sequential →", Inches(4.5), Inches(7.1), Inches(4), Inches(0.3),
                font_size=10, color=RGBColor(0x6B, 0x72, 0x80), italic=True)

    # ── SLIDE 5: Regulatory Screening — RAG Deep Dive ────────────────────────
    add_two_col_slide(prs, "Regulatory Screening — RAG Architecture",
        "Ingestion Pipeline", [
            ("PDF uploads via /api/regulations/sources", 0, WHITE),
            ("Federal CFR/statute PDFs, Pennsylvania Code", 1, GRAY_LT),
            ("eCFR live XML via /api/regulations/sources/ecfr", 0, WHITE),
            ("Versioner API pulls any CFR part by title+part+date", 1, GRAY_LT),
            ("Parsed → chunked → embedded → pgvector (HNSW index)", 0, WHITE),
            ("HNSW cosine index for sub-millisecond ANN retrieval", 1, GRAY_LT),
            ("Regulatory source assigned to specific project", 0, WHITE),
            ("Agent only retrieves chunks from that project's sources", 1, GRAY_LT),
        ],
        "Retrieval at Runtime", [
            ("RegulatoryScreeningAgent receives project_id", 0, WHITE),
            ("Falls back to all sources if none assigned", 1, GRAY_LT),
            ("Top-K similarity search scoped to project sources", 0, WHITE),
            ("LLM reasons over retrieved chunks to identify regulations", 0, WHITE),
            ("Outputs: name, citation, jurisdiction, why triggered", 1, GRAY_LT),
            ("Result feeds directly into Impact Analysis prompt", 0, WHITE),
            ("Explicit regulatory traceability in every cell", 1, GRAY_LT),
        ]
    )

    # ── SLIDE 6: Impact Matrix ────────────────────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "Impact Matrix",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    add_textbox(slide,
        "2D matrix: project actions (columns) × environmental resource categories (rows)\n"
        "One cell per (action × category × applicable regulation)",
        Inches(0.6), Inches(1.1), Inches(8), Inches(0.7),
        font_size=14, color=GRAY_LT)

    # Matrix structure diagram
    matrix_labels = [
        ("Category", "Site Prep", "Construction", "Operation"),
        ("Wetlands", "moderate", "significant", "minimal"),
        ("Endangered Spp.", "none", "significant", "none"),
        ("Floodplain", "moderate", "moderate", "none"),
        ("Air Quality", "minimal", "moderate", "minimal"),
        ("Env. Justice", "none", "moderate", "minimal"),
    ]
    cell_w = Inches(2.1)
    cell_h = Inches(0.48)
    mx = Inches(0.6)
    my = Inches(1.9)
    sig_colors = {
        "Category": ORANGE, "Site Prep": ORANGE, "Construction": ORANGE, "Operation": ORANGE,
        "significant": RED, "moderate": YELLOW, "minimal": GREEN, "none": CYAN,
    }
    for r, row in enumerate(matrix_labels):
        for c, val in enumerate(row):
            cx = mx + c * cell_w
            cy = my + r * cell_h
            cell_box = slide.shapes.add_shape(1, cx, cy, cell_w - Inches(0.04), cell_h - Inches(0.03))
            is_header = r == 0 or c == 0
            solid_fill(cell_box, DARK_CARD if not is_header else RGBColor(0x1A, 0x20, 0x2C))
            cell_box.line.color.rgb = RGBColor(0x3D, 0x4A, 0x5C)
            cell_box.line.width = Pt(0.75)
            txt_color = sig_colors.get(val, WHITE)
            add_textbox(slide, val, cx + Inches(0.08), cy + Inches(0.06),
                        cell_w - Inches(0.2), cell_h - Inches(0.1),
                        font_size=11, bold=is_header, color=txt_color)

    add_image_placeholder(slide, "Live impact matrix from agent run",
                          Inches(8.6), Inches(1.85), Inches(4.4), Inches(3.5))

    # Legend
    legend_items = [("significant", RED), ("moderate", YELLOW), ("minimal", GREEN), ("none", CYAN)]
    lx = Inches(0.6)
    ly = Inches(5.1)
    add_textbox(slide, "Significance scale:", lx, ly, Inches(1.8), Inches(0.3),
                font_size=11, bold=True, color=WHITE)
    for i, (label, color) in enumerate(legend_items):
        dot = slide.shapes.add_shape(1, lx + Inches(1.9) + i * Inches(1.55),
                                     ly + Inches(0.04), Inches(0.18), Inches(0.18))
        solid_fill(dot, color)
        add_textbox(slide, label,
                    lx + Inches(2.15) + i * Inches(1.55), ly,
                    Inches(1.3), Inches(0.3),
                    font_size=11, color=color)

    # Each cell also carries fields
    add_textbox(slide,
        "Each cell contains: significance · confidence (0–1) · reasoning (1–2 sentences) · mitigation types · needs_review flag",
        Inches(0.6), Inches(5.6), Inches(12.5), Inches(0.5),
        font_size=12, color=GRAY_LT, italic=True)

    # ── SLIDE 7: Confidence Score Calculation ─────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "Confidence Score Calculation",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    add_textbox(slide,
        "The LLM assigns a confidence score (0.0–1.0) to each impact cell based on data quality and regulatory specificity.",
        Inches(0.6), Inches(1.05), Inches(12.1), Inches(0.45),
        font_size=14, color=GRAY_LT)

    # Confidence tiers table
    tiers = [
        ("0.85 – 1.0",  "HIGH",     "API returned specific quantified data AND regulation includes explicit numeric thresholds",      GREEN),
        ("0.65 – 0.84", "GOOD",     "Data available from APIs but regulatory threshold is a judgment call (no explicit numeric threshold)", CYAN),
        ("0.45 – 0.64", "MODERATE", "Only partial data (some APIs errored / returned empty) or regulation is tangentially related",   YELLOW),
        ("0.25 – 0.44", "LOW",      "No direct data — determination relies on general domain knowledge about this project type",      ORANGE),
        ("0.00 – 0.24", "VERY LOW", "Pure extrapolation — no supporting data or regulatory context available",                        RED),
    ]
    row_h = Inches(0.72)
    ty = Inches(1.6)

    # Header
    hdr_box = slide.shapes.add_shape(1, Inches(0.6), ty, Inches(12.1), Inches(0.38))
    solid_fill(hdr_box, RGBColor(0x1A, 0x20, 0x2C))
    for x, w, label in [(Inches(0.6), Inches(1.4), "SCORE RANGE"),
                        (Inches(2.1), Inches(1.3), "TIER"),
                        (Inches(3.5), Inches(9.2), "WHAT IT MEANS")]:
        add_textbox(slide, label, x + Inches(0.08), ty + Inches(0.06),
                    w, Inches(0.3), font_size=11, bold=True, color=ORANGE)

    for i, (rng, tier, desc, color) in enumerate(tiers):
        ry = ty + Inches(0.38) + i * row_h
        row_bg = slide.shapes.add_shape(1, Inches(0.6), ry, Inches(12.1), row_h - Inches(0.04))
        solid_fill(row_bg, DARK_CARD)
        row_bg.line.color.rgb = RGBColor(0x3D, 0x4A, 0x5C)
        row_bg.line.width = Pt(0.5)

        add_textbox(slide, rng,   Inches(0.72), ry + Inches(0.08), Inches(1.3), Inches(0.5),
                    font_size=14, bold=True, color=color)
        add_textbox(slide, tier,  Inches(2.1),  ry + Inches(0.08), Inches(1.2), Inches(0.5),
                    font_size=12, bold=True, color=color)
        add_textbox(slide, desc,  Inches(3.5),  ry + Inches(0.05), Inches(9.0), Inches(0.6),
                    font_size=12, color=GRAY_LT, wrap=True)

    # Needs-review flag note
    flag_box = slide.shapes.add_shape(1, Inches(0.6), Inches(6.8), Inches(12.1), Inches(0.45))
    solid_fill(flag_box, RGBColor(0x3B, 0x1A, 0x1A))
    flag_box.line.color.rgb = RED
    flag_box.line.width = Pt(1)
    add_textbox(slide,
        "⚑  needs_review = True  when  confidence < 0.60  — cell is flagged in the UI for human expert review",
        Inches(0.75), Inches(6.83), Inches(11.8), Inches(0.38),
        font_size=13, bold=True, color=RED)

    # ── SLIDE 8: EIS Evaluation System ───────────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "EIS Evaluation System",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    add_textbox(slide,
        "How do we know the agent is correct? Upload a real EIS document and score the pipeline output against it.",
        Inches(0.6), Inches(1.05), Inches(12.1), Inches(0.45),
        font_size=14, color=GRAY_LT)

    # Pipeline steps
    steps = [
        ("UPLOAD",    "User uploads real EIS PDF linked to a project",              BLUE),
        ("PARSE",     "PDF parsed into sections, chunked, embedded into pgvector",   CYAN),
        ("EXTRACT",   "LLM reads EIS chunks → extracts ground truth categories\n(significance + evidence). Cached — runs once per document.", GREEN),
        ("SCORE",     "Agent outputs compared to ground truth.\n3 metrics computed and stored in evaluation_scores.", ORANGE),
        ("REVIEW",    "Per-category breakdown: TP/FP/FN labels, agent vs GT\nsignificance, matched EIS category name",  YELLOW),
    ]
    step_w = Inches(2.3)
    step_h = Inches(4.2)
    step_gap = Inches(0.22)
    sx = Inches(0.5)
    sy = Inches(1.65)
    for i, (label, desc, color) in enumerate(steps):
        bx = sx + i * (step_w + step_gap)
        sbox = slide.shapes.add_shape(1, bx, sy, step_w, step_h)
        solid_fill(sbox, DARK_CARD)
        sbox.line.color.rgb = color
        sbox.line.width = Pt(1.5)
        # Step header
        hdr = slide.shapes.add_shape(1, bx, sy, step_w, Inches(0.42))
        solid_fill(hdr, color)
        add_textbox(slide, f"STEP {i+1}: {label}", bx + Inches(0.08), sy + Inches(0.06),
                    step_w - Inches(0.16), Inches(0.34),
                    font_size=11, bold=True, color=WHITE)
        add_textbox(slide, desc, bx + Inches(0.12), sy + Inches(0.5),
                    step_w - Inches(0.24), step_h - Inches(0.6),
                    font_size=12, color=GRAY_LT, wrap=True)

    add_image_placeholder(slide, "EIS upload + status screenshot",
                          Inches(0.6), Inches(6.0), Inches(5.8), Inches(1.2))
    add_image_placeholder(slide, "Evaluation scores panel screenshot",
                          Inches(6.9), Inches(6.0), Inches(6.1), Inches(1.2))

    # ── SLIDE 9: Evaluation Metrics Deep Dive ────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "Evaluation Metrics — How Scores Are Calculated",
                Inches(0.6), Inches(0.18), Inches(12.5), Inches(0.7),
                font_size=26, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    metrics = [
        ("CATEGORY F1   ×0.40", BLUE,
         "8 agent-designed categories: wetlands · air_quality · noise · traffic\n"
         "environmental_justice · endangered_species · floodplain · prime_farmland\n\n"
         "TP: agent flagged AND EIS confirms impact\n"
         "FP: agent flagged BUT EIS says no impact\n"
         "FN: EIS has impact BUT agent did not flag it\n\n"
         "Precision = TP/(TP+FP)   Recall = TP/(TP+FN)\n"
         "F1 = 2·P·R / (P+R)\n\n"
         "EIS categories outside the 8 agent-designed ones are NOT counted against F1"),
        ("SIGNIFICANCE ACCURACY   ×0.40", GREEN,
         "For each matched category, compare agent significance\nto ground truth on an ordinal scale:\n\n"
         "significant=3 · moderate=2 · minimal=1 · none=0\n\n"
         "Exact match → 1.0 (full credit)\n"
         "Off by 1 level → 0.5 (partial credit)\n"
         "Off by 2+ levels → 0.0\n\n"
         "Score averaged across all matched categories"),
        ("SEMANTIC COVERAGE   ×0.20", YELLOW,
         "Up to 10 agent reasoning snippets embedded\nand compared against stored EIS chunks\nusing cosine similarity\n\n"
         "Average max-similarity measures how well\nthe agent's reasoning aligns with the\nactual EIS document text\n\n"
         "No LLM used — pure vector math on\nexisting embeddings (fast, cheap)"),
    ]
    col_w = Inches(3.9)
    col_gap = Inches(0.22)
    cx0 = Inches(0.6)
    cy = Inches(1.1)
    for i, (title, color, desc) in enumerate(metrics):
        bx = cx0 + i * (col_w + col_gap)
        mbox = slide.shapes.add_shape(1, bx, cy, col_w, Inches(5.5))
        solid_fill(mbox, DARK_CARD)
        mbox.line.color.rgb = color
        mbox.line.width = Pt(2)
        hdr = slide.shapes.add_shape(1, bx, cy, col_w, Inches(0.5))
        solid_fill(hdr, color)
        add_textbox(slide, title, bx + Inches(0.1), cy + Inches(0.07),
                    col_w - Inches(0.2), Inches(0.38),
                    font_size=11, bold=True, color=WHITE)
        add_textbox(slide, desc, bx + Inches(0.15), cy + Inches(0.58),
                    col_w - Inches(0.3), Inches(4.7),
                    font_size=12, color=GRAY_LT, wrap=True)

    # Overall score formula
    add_textbox(slide,
        "OVERALL SCORE  =  (Category F1 × 0.40)  +  (Significance Accuracy × 0.40)  +  (Semantic Coverage × 0.20)",
        Inches(0.6), Inches(6.85), Inches(12.1), Inches(0.45),
        font_size=13, bold=True, color=ORANGE, align=PP_ALIGN.CENTER)

    # ── SLIDE 10: Evaluation Risks & Future Improvements ────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "Evaluation Risks & Shortcomings",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    add_textbox(slide,
        "Our current metrics (F1, Significance Accuracy, Semantic Coverage) are a starting point — "
        "not a complete picture of agent quality.",
        Inches(0.6), Inches(1.05), Inches(12.1), Inches(0.45),
        font_size=13, color=GRAY_LT, italic=True)

    # Two columns: Risks (left) | Future Improvements (right)
    col_w = Inches(5.8)

    # LEFT — Shortcomings
    lhdr = slide.shapes.add_shape(1, Inches(0.6), Inches(1.6), col_w, Inches(0.4))
    solid_fill(lhdr, DARK_CARD)
    add_textbox(slide, "CURRENT SHORTCOMINGS", Inches(0.7), Inches(1.63),
                col_w - Inches(0.2), Inches(0.34),
                font_size=12, bold=True, color=RED)

    risks = [
        ("Ground truth is LLM-extracted — not human-annotated", 0, WHITE),
        ("LLM misreads the EIS → corrupted GT → misleadingly good scores", 1, GRAY_LT),
        ("Only 8 hardcoded categories are evaluated", 0, WHITE),
        ("Project-specific impacts (e.g. cultural resources, noise) are invisible to F1", 1, GRAY_LT),
        ("F1 is binary — partial detection gets no credit", 0, WHITE),
        ("Agent may identify the right concern under a different label (FP + FN)", 1, GRAY_LT),
        ("Significance accuracy uses a coarse ordinal scale", 0, WHITE),
        ("'Significant' in EIS context is project- and jurisdiction-specific", 1, GRAY_LT),
        ("Semantic coverage ≠ factual correctness", 0, WHITE),
        ("High cosine similarity can reflect style match, not accurate impact reasoning", 1, GRAY_LT),
        ("Non-determinism: same run may score differently across LLM calls", 0, WHITE),
    ]

    ltx = slide.shapes.add_textbox(Inches(0.6), Inches(2.1), col_w, Inches(5.0))
    tf = ltx.text_frame
    tf.word_wrap = True
    first = True
    for text, level, color in risks:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_before = Pt(3 if level == 0 else 1)
        prefix = "▸ " if level == 0 else "  · "
        run = p.add_run()
        run.text = prefix + text
        run.font.size = Pt(13 if level == 0 else 11)
        run.font.bold = (level == 0)
        run.font.color.rgb = color

    # RIGHT — Future Improvements
    rhdr = slide.shapes.add_shape(1, Inches(7.0), Inches(1.6), col_w, Inches(0.4))
    solid_fill(rhdr, DARK_CARD)
    add_textbox(slide, "WHERE TO IMPROVE", Inches(7.1), Inches(1.63),
                col_w - Inches(0.2), Inches(0.34),
                font_size=12, bold=True, color=GREEN)

    improvements = [
        ("Human-in-the-loop ground truth annotation", 0, WHITE),
        ("Domain experts review LLM extraction → verified GT corpus", 1, GRAY_LT),
        ("Expand category set per project type", 0, WHITE),
        ("Move from 8 fixed categories to dynamic, project-driven taxonomy", 1, GRAY_LT),
        ("LLM-as-Judge for reasoning quality", 0, WHITE),
        ("Separate evaluator LLM scores reasoning chains, not just category hits", 1, GRAY_LT),
        ("Multi-document ensembling", 0, WHITE),
        ("Average GT across multiple EIS docs for the same project type", 1, GRAY_LT),
        ("Confidence calibration curves", 0, WHITE),
        ("Track whether high-confidence cells are actually more accurate over time", 1, GRAY_LT),
        ("Section-level citation verification", 0, WHITE),
        ("Verify that cited regulations actually contain the claimed thresholds", 1, GRAY_LT),
        ("Run-level repeatability score", 0, WHITE),
        ("Multi-run variance tracking to quantify LLM non-determinism", 1, GRAY_LT),
    ]

    rtx = slide.shapes.add_textbox(Inches(7.0), Inches(2.1), col_w, Inches(5.0))
    tf = rtx.text_frame
    tf.word_wrap = True
    first = True
    for text, level, color in improvements:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_before = Pt(3 if level == 0 else 1)
        prefix = "▸ " if level == 0 else "  · "
        run = p.add_run()
        run.text = prefix + text
        run.font.size = Pt(13 if level == 0 else 11)
        run.font.bold = (level == 0)
        run.font.color.rgb = color

    # ── SLIDE 11: Results ────────────────────────────────────────────────────
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, "Results",
                Inches(0.6), Inches(0.18), Inches(12), Inches(0.7),
                font_size=28, bold=True, color=ORANGE)
    divider = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(divider, RGBColor(0x3D, 0x4A, 0x5C))

    add_image_placeholder(slide, "Full pipeline run — Brain Scanner log + agent status",
                          Inches(0.6), Inches(1.1), Inches(7.8), Inches(2.8))
    add_image_placeholder(slide, "Impact matrix output (color-coded by significance)",
                          Inches(8.6), Inches(1.1), Inches(4.4), Inches(2.8))
    add_image_placeholder(slide, "Evaluation scores panel (Overall %, F1, Precision, Recall bars)",
                          Inches(0.6), Inches(4.1), Inches(5.8), Inches(3.1))
    add_image_placeholder(slide, "Per-category breakdown table (TP/FP/FN, agent sig vs GT sig)",
                          Inches(6.6), Inches(4.1), Inches(6.4), Inches(3.1))

    # ── SLIDE 11: Technical Stack ────────────────────────────────────────────
    add_two_col_slide(prs, "Technical Stack",
        "Backend", [
            ("FastAPI + Uvicorn (Python)", 0, WHITE),
            ("ASGI with streaming response support for SSE", 1, GRAY_LT),
            ("LangGraph for agent orchestration", 0, WHITE),
            ("Directed graph with typed EIAPipelineState", 1, GRAY_LT),
            ("psycopg2 — raw SQL, no ORM", 0, WHITE),
            ("Repository pattern for new DB access code", 1, GRAY_LT),
            ("LlamaIndex + pgvector (HNSW) for RAG", 0, WHITE),
            ("OpenAI / Anthropic / Ollama — switchable via env vars", 0, WHITE),
            ("No code changes needed to swap providers", 1, GRAY_LT),
        ],
        "Frontend + Infrastructure", [
            ("React 18 + Vite (widescreen, inline CSS)", 0, WHITE),
            ("Real-time SSE streaming via EventSource", 1, GRAY_LT),
            ("Agent status dots, cost tracking, Brain Scanner log", 1, GRAY_LT),
            ("PostgreSQL + pgvector on Render", 0, WHITE),
            ("HNSW cosine index for sub-ms ANN search", 1, GRAY_LT),
            ("pipeline_runs table: one saved run per project", 1, GRAY_LT),
            ("SAVE RESULTS — explicit save with overwrite guard", 0, WHITE),
            ("EIS evaluation scoring auto-populates on load", 0, WHITE),
        ]
    )

    # ── SLIDE 12: Conclusion ─────────────────────────────────────────────────
    add_bullet_slide(prs, "Conclusion", [
        ("Automated NEPA screening from weeks to minutes", 0, ORANGE),
        ("5-agent pipeline covers data gathering, regulatory RAG, impact analysis, and report writing", 1, GRAY_LT),
        ("Full traceability: every impact cell cites the regulation and data that drove it", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Confidence-aware — not a black box", 0, ORANGE),
        ("5-tier scoring model anchored to data quality and regulatory specificity", 1, GRAY_LT),
        ("Cells below 0.6 confidence are flagged for human review automatically", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Quantitative evaluation against real EIS documents", 0, ORANGE),
        ("Category F1, Significance Accuracy, Semantic Coverage scores", 1, GRAY_LT),
        ("Ground truth extraction cached — re-scoring is fast and cheap", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Future Work", 0, WHITE),
        ("Populate run_id on evaluation scores for run↔score traceability", 1, GRAY_LT),
        ("Multi-project comparison dashboard", 1, GRAY_LT),
        ("Automated report filing / agency submission integration", 1, GRAY_LT),
        ("Expand to full EIS (beyond screening-level EA)", 1, GRAY_LT),
    ])

    prs.save(output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    potx = "/Users/sanderschulman/Developer/aiagentsproject/24-880 Presentation Template (1).potx"
    out  = "/Users/sanderschulman/Developer/aiagentsproject/EIA_Agent_System_Presentation.pptx"
    build(potx, out)
