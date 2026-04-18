"""Build EIA Agent System presentation following the 24-880 template theme."""
import io
import zipfile

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

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
    """Read a .potx template, strip its sample slides, repackage as .pptx."""
    import re as _re
    buf = io.BytesIO()
    with zipfile.ZipFile(potx_path, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                # Drop template sample slides — we add our own; keeping them
                # causes duplicate-name conflicts in the ZIP that corrupt the file.
                if item.filename.startswith('ppt/slides/'):
                    continue
                data = zin.read(item.filename)
                if item.filename == '[Content_Types].xml':
                    data = data.replace(
                        b'presentationml.template.main+xml',
                        b'presentationml.presentation.main+xml',
                    )
                    # Remove Override entries for the dropped slide files
                    data = _re.sub(
                        rb'<Override[^>]*/ppt/slides/slide\d+\.xml[^>]*/?>',
                        b'', data,
                    )
                if item.filename == 'ppt/presentation.xml':
                    # Strip <p:sldIdLst> so pptx opens with zero slides
                    data = _re.sub(rb'<p:sldIdLst>.*?</p:sldIdLst>', b'<p:sldIdLst/>', data, flags=_re.DOTALL)
                zout.writestr(item, data)
    buf.seek(0)
    prs = Presentation(buf)
    prs.slide_width  = W
    prs.slide_height = H
    return prs


def solid_fill(shape, color: RGBColor):
    fill = shape.fill
    fill.solid()
    fill.fore_color.rgb = color


def set_slide_bg(slide, color: RGBColor):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_textbox(slide, text, left, top, width, height,
                font_size=18, bold=False, color=WHITE,
                align=PP_ALIGN.LEFT, wrap=True, italic=False):
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


def _add_header(slide, title_text, font_size=28):
    """Orange top bar + title + divider."""
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(0.08))
    solid_fill(bar, ORANGE)
    add_textbox(slide, title_text,
                Inches(0.6), Inches(0.18), Inches(12.5), Inches(0.75),
                font_size=font_size, bold=True, color=ORANGE)
    line = slide.shapes.add_shape(1, Inches(0.6), Inches(1.0), Inches(12.1), Inches(0.02))
    solid_fill(line, RGBColor(0x3D, 0x4A, 0x5C))


def add_bullet_slide(prs, title_text, bullets, font_size=28):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, title_text, font_size)

    txBox = slide.shapes.add_textbox(Inches(0.6), Inches(1.15), Inches(12.1), Inches(6.1))
    tf = txBox.text_frame
    tf.word_wrap = True

    first = True
    for text, level, color in bullets:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_before = Pt(5 if level == 0 else 2)
        indent_prefix = "    " * level
        bullet_char = "▸ " if level == 0 else "· "
        run = p.add_run()
        run.text = indent_prefix + bullet_char + text
        run.font.size = Pt(17 if level == 0 else 14)
        run.font.bold = (level == 0)
        run.font.color.rgb = color

    return slide


def add_two_col_slide(prs, title_text,
                      left_title, left_items,
                      right_title, right_items):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, title_text)

    col_w = Inches(5.8)
    for col_x, col_title, items in [
        (Inches(0.6), left_title, left_items),
        (Inches(7.0), right_title, right_items),
    ]:
        hdr = slide.shapes.add_shape(1, col_x, Inches(1.1), col_w, Inches(0.4))
        solid_fill(hdr, DARK_CARD)
        add_textbox(slide, col_title, col_x + Inches(0.1), Inches(1.12),
                    col_w - Inches(0.2), Inches(0.36),
                    font_size=13, bold=True, color=ORANGE)

        txBox = slide.shapes.add_textbox(col_x, Inches(1.6), col_w, Inches(5.6))
        tf = txBox.text_frame
        tf.word_wrap = True
        first = True
        for text, level, color in items:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.level = level
            p.space_before = Pt(3 if level == 0 else 1)
            prefix = "▸ " if level == 0 else "  · "
            run = p.add_run()
            run.text = prefix + text
            run.font.size = Pt(15 if level == 0 else 13)
            run.font.bold = (level == 0)
            run.font.color.rgb = color

    return slide


def add_image_placeholder(slide, label, left, top, width, height):
    box = slide.shapes.add_shape(1, left, top, width, height)
    fill = box.fill
    fill.solid()
    fill.fore_color.rgb = DARK_CARD
    box.line.color.rgb = ORANGE
    box.line.width = Pt(1.5)
    add_textbox(slide, f"[ FIGURE: {label} ]",
                left + Inches(0.1), top + height / 2 - Pt(20),
                width - Inches(0.2), Inches(0.5),
                font_size=11, color=ORANGE, align=PP_ALIGN.CENTER, italic=True)


def add_agent_slide(prs, agent_num, agent_name, color,
                    what_it_does, inputs, outputs, steps, note=None):
    """Standard per-agent methodology slide."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, f"Methodology — Agent {agent_num}: {agent_name}")

    # Colored accent bar under title
    accent = slide.shapes.add_shape(1, Inches(0.6), Inches(1.04), Inches(12.1), Inches(0.06))
    solid_fill(accent, color)

    # Left column: What it does + Steps
    left_w = Inches(5.5)
    lx = Inches(0.6)
    ly = Inches(1.18)

    add_textbox(slide, "WHAT IT DOES", lx, ly, left_w, Inches(0.3),
                font_size=11, bold=True, color=color)
    add_textbox(slide, what_it_does, lx, ly + Inches(0.32), left_w, Inches(1.5),
                font_size=13, color=GRAY_LT, wrap=True)

    add_textbox(slide, "PROCESSING STEPS", lx, ly + Inches(1.9), left_w, Inches(0.3),
                font_size=11, bold=True, color=color)
    steps_box = slide.shapes.add_textbox(lx, ly + Inches(2.22), left_w, Inches(3.5))
    stf = steps_box.text_frame
    stf.word_wrap = True
    first = True
    for i, step in enumerate(steps):
        p = stf.paragraphs[0] if first else stf.add_paragraph()
        first = False
        p.space_before = Pt(3)
        run = p.add_run()
        run.text = f"  {i+1}.  {step}"
        run.font.size = Pt(13)
        run.font.color.rgb = GRAY_LT

    # Right column: Inputs / Outputs
    rx = Inches(6.5)
    ry = Inches(1.18)
    rw = Inches(6.4)

    # Inputs card
    in_box = slide.shapes.add_shape(1, rx, ry, rw, Inches(2.7))
    solid_fill(in_box, DARK_CARD)
    in_box.line.color.rgb = CYAN
    in_box.line.width = Pt(1)
    add_textbox(slide, "INPUTS", rx + Inches(0.15), ry + Inches(0.1),
                rw - Inches(0.3), Inches(0.28),
                font_size=11, bold=True, color=CYAN)
    in_text = slide.shapes.add_textbox(rx + Inches(0.15), ry + Inches(0.4),
                                       rw - Inches(0.3), Inches(2.2))
    itf = in_text.text_frame
    itf.word_wrap = True
    first = True
    for inp in inputs:
        p = itf.paragraphs[0] if first else itf.add_paragraph()
        first = False
        p.space_before = Pt(2)
        run = p.add_run()
        run.text = "· " + inp
        run.font.size = Pt(12)
        run.font.color.rgb = GRAY_LT

    # Outputs card
    out_y = ry + Inches(2.85)
    out_box = slide.shapes.add_shape(1, rx, out_y, rw, Inches(2.7))
    solid_fill(out_box, DARK_CARD)
    out_box.line.color.rgb = color
    out_box.line.width = Pt(1)
    add_textbox(slide, "OUTPUTS", rx + Inches(0.15), out_y + Inches(0.1),
                rw - Inches(0.3), Inches(0.28),
                font_size=11, bold=True, color=color)
    out_text = slide.shapes.add_textbox(rx + Inches(0.15), out_y + Inches(0.4),
                                        rw - Inches(0.3), Inches(2.2))
    otf = out_text.text_frame
    otf.word_wrap = True
    first = True
    for outp in outputs:
        p = otf.paragraphs[0] if first else otf.add_paragraph()
        first = False
        p.space_before = Pt(2)
        run = p.add_run()
        run.text = "· " + outp
        run.font.size = Pt(12)
        run.font.color.rgb = GRAY_LT

    if note:
        add_textbox(slide, f"⚑  {note}",
                    Inches(0.6), Inches(7.05), Inches(12.1), Inches(0.35),
                    font_size=11, italic=True, color=ORANGE)

    return slide


# ── Build slides ─────────────────────────────────────────────────────────────

def build(potx_path: str, output_path: str):
    prs = convert_potx_to_pptx(potx_path)


    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 1 — Title
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)

    top = slide.shapes.add_shape(1, Inches(0), Inches(0), W, Inches(1.7))
    solid_fill(top, ORANGE)

    add_textbox(slide, "EIA AGENT SYSTEM",
                Inches(0.7), Inches(0.18), Inches(11.5), Inches(1.1),
                font_size=42, bold=True, color=WHITE)

    add_textbox(slide, "Automated Environmental Impact Assessment via Multi-Agent AI Pipeline",
                Inches(0.7), Inches(1.9), Inches(11.5), Inches(0.9),
                font_size=22, color=GRAY_LT)

    add_textbox(slide, "24-880  AI Agents for Engineers  |  Carnegie Mellon University",
                Inches(0.7), Inches(3.0), Inches(11.5), Inches(0.5),
                font_size=17, color=ORANGE)

    add_textbox(slide, "[ Group Member Name(s) ]",
                Inches(0.7), Inches(3.7), Inches(11.5), Inches(0.4),
                font_size=15, color=GRAY_LT)

    add_textbox(slide, "[ Presentation Date ]",
                Inches(0.7), Inches(4.2), Inches(11.5), Inches(0.4),
                font_size=15, color=GRAY_LT)

    bot = slide.shapes.add_shape(1, Inches(0), H - Inches(0.15), W, Inches(0.15))
    solid_fill(bot, ORANGE)

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 2 — Background
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Background")

    add_textbox(slide,
        "Environmental review is a legal prerequisite for major infrastructure projects in the United States.",
        Inches(0.6), Inches(1.1), Inches(12.1), Inches(0.45),
        font_size=14, italic=True, color=GRAY_LT)

    left_bullets = [
        ("National Environmental Policy Act (NEPA)", 0, WHITE),
        ("Signed 1970 — applies to all major federal actions", 1, GRAY_LT),
        ("Requires agencies to evaluate environmental consequences", 1, GRAY_LT),
        ("Two-tier review: Environmental Assessment (EA) + full EIS", 1, GRAY_LT),
        ("Environmental Assessment (EA)", 0, WHITE),
        ("Screening-level review: does this project need a full EIS?", 1, GRAY_LT),
        ("Involves querying federal environmental databases", 1, GRAY_LT),
        ("Applies applicable federal and state regulations", 1, GRAY_LT),
        ("Produces written impact determinations by resource category", 1, GRAY_LT),
        ("Environmental Impact Statement (EIS)", 0, WHITE),
        ("Full-scale analysis required when EA finds significant impacts", 1, GRAY_LT),
        ("Can take 2–5 years and cost millions of dollars", 1, GRAY_LT),
        ("Publicly available — used as ground truth in this project", 1, GRAY_LT),
    ]

    txBox = slide.shapes.add_textbox(Inches(0.6), Inches(1.65), Inches(6.2), Inches(5.6))
    tf = txBox.text_frame
    tf.word_wrap = True
    first = True
    for text, level, color in left_bullets:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_before = Pt(4 if level == 0 else 2)
        run = p.add_run()
        run.text = ("    " * level) + ("▸ " if level == 0 else "· ") + text
        run.font.size = Pt(15 if level == 0 else 13)
        run.font.bold = (level == 0)
        run.font.color.rgb = color

    # Right side: key federal data sources
    rx = Inches(7.1)
    add_textbox(slide, "KEY FEDERAL DATA SOURCES", rx, Inches(1.65), Inches(5.8), Inches(0.35),
                font_size=12, bold=True, color=ORANGE)

    sources = [
        ("USFWS IPaC", "Threatened & endangered species by location", YELLOW),
        ("National Wetlands Inventory", "Wetland presence, type, and acreage", CYAN),
        ("FEMA National Flood Hazard", "100- and 500-year floodplain boundaries", BLUE),
        ("USDA Farmland Layer", "Prime and unique farmland parcels", GREEN),
        ("EPA EJScreen", "Environmental justice + demographic indicators", ORANGE),
    ]
    sy = Inches(2.1)
    for name, desc, color in sources:
        sbox = slide.shapes.add_shape(1, rx, sy, Inches(5.8), Inches(0.85))
        solid_fill(sbox, DARK_CARD)
        sbox.line.color.rgb = color
        sbox.line.width = Pt(1.2)
        add_textbox(slide, name, rx + Inches(0.15), sy + Inches(0.06),
                    Inches(5.5), Inches(0.28), font_size=12, bold=True, color=color)
        add_textbox(slide, desc, rx + Inches(0.15), sy + Inches(0.35),
                    Inches(5.5), Inches(0.4), font_size=11, color=GRAY_LT)
        sy += Inches(0.95)

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 3 — Problem Statement
    # ════════════════════════════════════════════════════════════════════════
    add_bullet_slide(prs, "Problem Statement", [
        ("Environmental reviews are a bottleneck for infrastructure", 0, WHITE),
        ("NEPA EA requires querying 5+ federal databases per project", 1, GRAY_LT),
        ("Analysts must screen hundreds of regulations for applicability", 1, GRAY_LT),
        ("Writing impact determinations with citations takes weeks of expert time", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Existing tools don't explain their reasoning", 0, WHITE),
        ("Black-box outputs cannot be used in regulatory proceedings", 1, GRAY_LT),
        ("Agencies require traceable citations and data-backed determinations", 1, GRAY_LT),
        ("Reviewing agencies need to audit how each conclusion was reached", 1, GRAY_LT),
        ("", 0, WHITE),
        ("There is no objective quality metric for AI-generated EIA outputs", 0, WHITE),
        ("How do we know if the agent identified the right impacts?", 1, GRAY_LT),
        ("No existing benchmark — real EIS documents must serve as ground truth", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Goal: automate EIA screening with explainable, confidence-aware AI", 0, ORANGE),
        ("Reduce time from weeks to minutes; preserve full regulatory traceability", 1, GRAY_LT),
        ("Flag low-confidence cells for human review — keep experts in the loop", 1, GRAY_LT),
        ("Evaluate agent quality against real EIS documents quantitatively", 1, GRAY_LT),
    ])

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 4 — Methodology Overview (System Architecture)
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Methodology — System Architecture")

    add_textbox(slide,
        "A LangGraph sequential pipeline orchestrates 5 specialized agents, each with typed inputs/outputs, "
        "streamed in real-time to a React frontend via Server-Sent Events.",
        Inches(0.6), Inches(1.1), Inches(12.1), Inches(0.6),
        font_size=13, color=GRAY_LT, wrap=True)

    # 5 agent boxes
    agents = [
        ("1  PROJECT\nPARSER",       BLUE),
        ("2  ENVIRONMENTAL\nDATA",   CYAN),
        ("3  REGULATORY\nSCREENING", GREEN),
        ("4  IMPACT\nANALYSIS",      ORANGE),
        ("5  REPORT\nSYNTHESIS",     YELLOW),
    ]
    box_w  = Inches(2.22)
    box_h  = Inches(1.5)
    gap    = Inches(0.22)
    start_x = Inches(0.5)
    ay = Inches(1.85)

    for i, (name, color) in enumerate(agents):
        bx = start_x + i * (box_w + gap)
        box = slide.shapes.add_shape(1, bx, ay, box_w, box_h)
        solid_fill(box, DARK_CARD)
        box.line.color.rgb = color
        box.line.width = Pt(2)
        hdr = slide.shapes.add_shape(1, bx, ay, box_w, Inches(0.45))
        solid_fill(hdr, color)
        add_textbox(slide, name, bx + Inches(0.1), ay + Inches(0.05),
                    box_w - Inches(0.2), Inches(0.9),
                    font_size=10, bold=True, color=WHITE)

    # Arrow
    add_textbox(slide, "─────────────────────────────────────── sequential flow ───────────────────────────────────────",
                Inches(0.5), ay + Inches(1.6), Inches(12.4), Inches(0.3),
                font_size=9, color=RGBColor(0x4B, 0x55, 0x63), align=PP_ALIGN.CENTER)

    # Data flow description boxes
    flow_items = [
        ("React Frontend", "SSE streaming · real-time status dots · cost tracking · Brain Scanner log", BLUE),
        ("FastAPI Backend", "POST /api/run → state machine → SSE generator yields per-agent events", CYAN),
        ("LangGraph", "Typed EIAPipelineState flows through sequential graph nodes", GREEN),
        ("PostgreSQL + pgvector", "Agent outputs stored as JSONB · HNSW index for RAG similarity search", ORANGE),
        ("LLM Providers", "OpenAI · Anthropic · Ollama — switchable via env vars, no code changes", YELLOW),
    ]
    fy = Inches(3.65)
    fw = Inches(12.15)
    fh = Inches(0.52)
    for i, (label, desc, color) in enumerate(flow_items):
        fbox = slide.shapes.add_shape(1, Inches(0.6), fy + i * (fh + Inches(0.06)),
                                      fw, fh)
        solid_fill(fbox, DARK_CARD)
        fbox.line.color.rgb = color
        fbox.line.width = Pt(1)
        add_textbox(slide, label,
                    Inches(0.75), fy + i * (fh + Inches(0.06)) + Inches(0.06),
                    Inches(2.2), Inches(0.38),
                    font_size=12, bold=True, color=color)
        add_textbox(slide, desc,
                    Inches(3.1), fy + i * (fh + Inches(0.06)) + Inches(0.08),
                    Inches(9.5), Inches(0.38),
                    font_size=12, color=GRAY_LT)

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 5 — Agent 1: Project Parser
    # ════════════════════════════════════════════════════════════════════════
    add_agent_slide(
        prs, 1, "Project Parser", BLUE,
        what_it_does=(
            "Parses a natural-language project description and GPS coordinates into a structured "
            "metadata object that all downstream agents consume. Uses an LLM (Gemini 2.5 Flash) "
            "to extract semantic fields from free-form text."
        ),
        inputs=[
            "project_name (string)",
            "coordinates (lat, lon string)",
            "description (free-form natural language)",
        ],
        outputs=[
            "project_type  (e.g. 'highway', 'pipeline', 'solar farm')",
            "scale  (small / medium / large)",
            "location  (city, county, state)",
            "actions  (list of distinct project activities)",
            "duration  (construction + operation timeline)",
            "federal_nexus  (boolean — triggers NEPA applicability)",
        ],
        steps=[
            "parse_description — LLM reads free-form project text",
            "extract_metadata — structured fields extracted via JSON schema",
            "geocode_coordinates — GPS coordinates validated and formatted",
        ],
        note="Output feeds the impact matrix column headers (project actions) and scopes all downstream API queries."
    )

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 6 — Agent 2: Environmental Data Agent
    # ════════════════════════════════════════════════════════════════════════
    add_agent_slide(
        prs, 2, "Environmental Data Agent", CYAN,
        what_it_does=(
            "Queries 5 federal environmental REST APIs using the GPS coordinates from the Project Parser. "
            "This is the only non-LLM agent — pure API orchestration with structured response parsing."
        ),
        inputs=[
            "coordinates (from Project Parser output)",
            "project_type (to determine buffer radii)",
        ],
        outputs=[
            "USFWS IPaC — threatened & endangered species list",
            "NWI — wetland polygons within project footprint",
            "FEMA NFHL — flood zone designations (AE, X, etc.)",
            "USDA — prime farmland and unique farmland presence",
            "EJScreen — demographic percentiles, pollution burden index",
        ],
        steps=[
            "query_usfws — USFWS IPaC API, species by bounding box",
            "query_nwi — National Wetlands Inventory WMS/WFS",
            "query_fema — FEMA National Flood Hazard Layer REST API",
            "query_farmland — USDA Web Soil Survey spatial API",
            "query_ejscreen — EPA EJScreen REST API by census block",
        ],
        note="No LLM used — deterministic API calls. API errors are caught per-source; partial results still flow downstream."
    )

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 7 — Agent 3: Regulatory Screening Agent
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Methodology — Agent 3: Regulatory Screening (RAG)")

    accent = slide.shapes.add_shape(1, Inches(0.6), Inches(1.04), Inches(12.1), Inches(0.06))
    solid_fill(accent, GREEN)

    add_textbox(slide,
        "Retrieves applicable NEPA regulations using Retrieval-Augmented Generation (RAG) "
        "over an indexed corpus of federal CFR parts and state environmental codes.",
        Inches(0.6), Inches(1.18), Inches(12.1), Inches(0.6),
        font_size=13, color=GRAY_LT, wrap=True)

    # Two columns: Ingestion Pipeline | Runtime Retrieval
    col_w = Inches(5.8)
    for col_x, col_title, col_color, items in [
        (Inches(0.6), "INGESTION PIPELINE", CYAN, [
            ("PDF uploads via /api/regulations/sources", WHITE),
            ("Federal CFR/statute PDFs, Pennsylvania Code", GRAY_LT),
            ("eCFR live XML via /api/regulations/sources/ecfr", WHITE),
            ("Versioner API fetches any CFR title+part by date", GRAY_LT),
            ("Parsed → chunked → embedded → pgvector", WHITE),
            ("HNSW cosine index for sub-millisecond ANN retrieval", GRAY_LT),
            ("Sources assigned to specific projects via UI", WHITE),
            ("Agent restricts retrieval to project-assigned sources", GRAY_LT),
        ]),
        (Inches(7.0), "RUNTIME RETRIEVAL", GREEN, [
            ("Project context string embedded by LLM", WHITE),
            ("Top-K similarity search scoped to project sources", WHITE),
            ("Falls back to all sources if none assigned", GRAY_LT),
            ("LLM reasons over chunks → identifies regulations", WHITE),
            ("Outputs name, citation, jurisdiction, why triggered", GRAY_LT),
            ("Result feeds directly into Impact Analysis prompt", WHITE),
            ("Every impact cell carries explicit regulation citation", GRAY_LT),
        ]),
    ]:
        hdr_box = slide.shapes.add_shape(1, col_x, Inches(1.9), col_w, Inches(0.36))
        solid_fill(hdr_box, DARK_CARD)
        add_textbox(slide, col_title, col_x + Inches(0.1), Inches(1.93),
                    col_w, Inches(0.3), font_size=12, bold=True, color=col_color)

        tb = slide.shapes.add_textbox(col_x, Inches(2.32), col_w, Inches(4.8))
        tf = tb.text_frame
        tf.word_wrap = True
        first = True
        bold_toggle = True
        for text, color in items:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.space_before = Pt(3)
            run = p.add_run()
            run.text = "▸ " + text if bold_toggle else "    · " + text
            run.font.size = Pt(14 if bold_toggle else 12)
            run.font.bold = bold_toggle
            run.font.color.rgb = color
            bold_toggle = not bold_toggle

    # Model info footer
    model_box = slide.shapes.add_shape(1, Inches(0.6), Inches(7.05), Inches(12.1), Inches(0.35))
    solid_fill(model_box, DARK_CARD)
    add_textbox(slide, "Model: claude-haiku-4-5  ·  Embedding: text-embedding-3-small  ·  Vector DB: pgvector (HNSW cosine index)",
                Inches(0.75), Inches(7.08), Inches(11.8), Inches(0.28),
                font_size=11, color=GRAY_LT)

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 8 — Agent 4: Impact Analysis
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Methodology — Agent 4: Impact Analysis")

    accent = slide.shapes.add_shape(1, Inches(0.6), Inches(1.04), Inches(12.1), Inches(0.06))
    solid_fill(accent, ORANGE)

    add_textbox(slide,
        "Populates a significance matrix across all (project action × resource category) pairs. "
        "Each cell carries a significance determination, confidence score, reasoning, and mitigation options.",
        Inches(0.6), Inches(1.18), Inches(12.1), Inches(0.6),
        font_size=13, color=GRAY_LT, wrap=True)

    # Matrix sample
    matrix_labels = [
        ("Category",        "Site Prep",   "Construction", "Operation"),
        ("Wetlands",        "moderate",    "significant",  "minimal"),
        ("Endangered Spp.", "none",        "significant",  "none"),
        ("Floodplain",      "moderate",    "moderate",     "none"),
        ("Air Quality",     "minimal",     "moderate",     "minimal"),
        ("Env. Justice",    "none",        "moderate",     "minimal"),
        ("Prime Farmland",  "significant", "moderate",     "none"),
    ]
    sig_colors = {
        "Category": ORANGE, "Site Prep": ORANGE, "Construction": ORANGE, "Operation": ORANGE,
        "significant": RED, "moderate": YELLOW, "minimal": GREEN, "none": CYAN,
    }
    cell_w = Inches(2.1)
    cell_h = Inches(0.46)
    mx = Inches(0.6)
    my = Inches(1.92)
    for r, row in enumerate(matrix_labels):
        for c, val in enumerate(row):
            cx = mx + c * cell_w
            cy = my + r * cell_h
            cell_box = slide.shapes.add_shape(1, cx, cy, cell_w - Inches(0.03), cell_h - Inches(0.02))
            is_header = r == 0 or c == 0
            solid_fill(cell_box, DARK_CARD if not is_header else RGBColor(0x1A, 0x20, 0x2C))
            cell_box.line.color.rgb = RGBColor(0x3D, 0x4A, 0x5C)
            cell_box.line.width = Pt(0.75)
            add_textbox(slide, val, cx + Inches(0.07), cy + Inches(0.06),
                        cell_w - Inches(0.18), cell_h - Inches(0.1),
                        font_size=11, bold=is_header,
                        color=sig_colors.get(val, WHITE))

    # Legend
    legend_items = [("significant", RED), ("moderate", YELLOW), ("minimal", GREEN), ("none", CYAN)]
    lx = Inches(0.6)
    ly = Inches(5.22)
    add_textbox(slide, "Significance:", lx, ly, Inches(1.4), Inches(0.3),
                font_size=11, bold=True, color=WHITE)
    for i, (label, color) in enumerate(legend_items):
        dot = slide.shapes.add_shape(1, lx + Inches(1.5) + i * Inches(1.55),
                                     ly + Inches(0.05), Inches(0.16), Inches(0.16))
        solid_fill(dot, color)
        add_textbox(slide, label, lx + Inches(1.72) + i * Inches(1.55), ly,
                    Inches(1.3), Inches(0.3), font_size=11, color=color)

    # Per-cell fields (right side)
    rx = Inches(9.1)
    ry = Inches(1.92)
    rw = Inches(3.9)

    cell_fields = [
        ("significance", "significant | moderate | minimal | none", ORANGE),
        ("confidence", "0.0 – 1.0  (see confidence tiers)", YELLOW),
        ("reasoning", "1–2 sentence explanation", GRAY_LT),
        ("mitigation", "avoidance | minimization | compensatory", GREEN),
        ("needs_review", "True when confidence < 0.60", RED),
        ("framework", "Governing regulation citation", CYAN),
    ]
    add_textbox(slide, "PER-CELL FIELDS", rx, ry, rw, Inches(0.3),
                font_size=11, bold=True, color=ORANGE)
    ry += Inches(0.38)
    for field, desc, color in cell_fields:
        fb = slide.shapes.add_shape(1, rx, ry, rw, Inches(0.62))
        solid_fill(fb, DARK_CARD)
        fb.line.color.rgb = color
        fb.line.width = Pt(0.8)
        add_textbox(slide, field, rx + Inches(0.1), ry + Inches(0.04),
                    rw - Inches(0.2), Inches(0.28), font_size=11, bold=True, color=color)
        add_textbox(slide, desc, rx + Inches(0.1), ry + Inches(0.32),
                    rw - Inches(0.2), Inches(0.24), font_size=10, color=GRAY_LT)
        ry += Inches(0.68)

    add_textbox(slide,
        "Steps:  build_context (compile upstream data) → evaluate_determinations (LLM) → validate_matrix (flag low-confidence)",
        Inches(0.6), Inches(7.08), Inches(12.1), Inches(0.32),
        font_size=11, italic=True, color=ORANGE)

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 9 — Agent 5: Report Synthesis
    # ════════════════════════════════════════════════════════════════════════
    add_agent_slide(
        prs, 5, "Report Synthesis", YELLOW,
        what_it_does=(
            "Generates a full NEPA Environmental Assessment narrative (10 sections) from all upstream "
            "agent outputs. Sections 1–7 are LLM-generated with inline citations; Sections 8–10 are "
            "templated from the impact matrix."
        ),
        inputs=[
            "parsed_project (from Agent 1)",
            "environmental_data — API results (from Agent 2)",
            "regulations — applicable regulation list (from Agent 3)",
            "impact_matrix — significance × confidence cells (from Agent 4)",
        ],
        outputs=[
            "Section 1: Project Description",
            "Section 2: Purpose and Need",
            "Section 3: Alternatives Analysis",
            "Section 4: Affected Environment (per resource category)",
            "Section 5: Environmental Consequences (per impact cell)",
            "Section 6: Cumulative Impacts",
            "Section 7: Mitigation Measures",
            "Section 8: Regulatory Compliance Summary",
            "Section 9: Agency Coordination",
            "Section 10: References and Data Sources",
        ],
        steps=[
            "compile_findings — aggregate all upstream state fields",
            "generate_report — LLM writes Sections 1–7 with citations",
            "format_output — template Sections 8–10 from impact matrix",
        ],
        note="Full DOCX-ready output. Every impact statement cites the regulation and federal data source that drove it."
    )

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 10 — Methodology: Evaluation Process
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Methodology — Evaluation Process")

    add_textbox(slide,
        "How do we know the agent is correct? Upload a real published EIS document "
        "and score the pipeline's impact matrix against it.",
        Inches(0.6), Inches(1.1), Inches(12.1), Inches(0.5),
        font_size=14, color=GRAY_LT, wrap=True)

    steps = [
        ("UPLOAD",   "User uploads a published EIS PDF linked to a saved project run",           BLUE),
        ("PARSE",    "PDF parsed into numbered sections, chunked, embedded into pgvector\n"
                     "(evaluation_chunks table with HNSW cosine index)",                          CYAN),
        ("EXTRACT",  "LLM reads EIS chunks → extracts ground truth: category name, significance, "
                     "evidence quote.\nCached — runs once per document (not per scoring request)", GREEN),
        ("SCORE",    "Agent impact matrix compared to ground truth.\n"
                     "3 metrics computed: Category F1, Significance Accuracy, Semantic Coverage",  ORANGE),
        ("REVIEW",   "Per-category breakdown: TP/FP/FN labels, agent sig vs. GT sig,\n"
                     "matched EIS category name, GT evidence quote",                               YELLOW),
    ]
    step_w = Inches(2.3)
    step_h = Inches(4.5)
    step_gap = Inches(0.22)
    sx = Inches(0.5)
    sy = Inches(1.78)
    for i, (label, desc, color) in enumerate(steps):
        bx = sx + i * (step_w + step_gap)
        sbox = slide.shapes.add_shape(1, bx, sy, step_w, step_h)
        solid_fill(sbox, DARK_CARD)
        sbox.line.color.rgb = color
        sbox.line.width = Pt(1.5)
        hdr = slide.shapes.add_shape(1, bx, sy, step_w, Inches(0.42))
        solid_fill(hdr, color)
        add_textbox(slide, f"STEP {i+1}: {label}", bx + Inches(0.1), sy + Inches(0.07),
                    step_w - Inches(0.2), Inches(0.34),
                    font_size=10, bold=True, color=WHITE)
        add_textbox(slide, desc, bx + Inches(0.12), sy + Inches(0.52),
                    step_w - Inches(0.24), step_h - Inches(0.62),
                    font_size=11, color=GRAY_LT, wrap=True)

    add_image_placeholder(slide, "EIS upload panel + status pills (PENDING / EMBEDDING / READY)",
                          Inches(0.6), Inches(6.4), Inches(5.8), Inches(0.9))
    add_image_placeholder(slide, "Evaluate panel — score bars + per-category breakdown",
                          Inches(6.9), Inches(6.4), Inches(6.1), Inches(0.9))

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 11 — Results: Agent Outputs
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Results — Agent Outputs")

    add_textbox(slide,
        "Each of the 5 agents produces a typed, structured output stored in PostgreSQL (JSONB) "
        "and rendered in the IMPORT RUN panel with type-aware views.",
        Inches(0.6), Inches(1.1), Inches(12.1), Inches(0.5),
        font_size=13, color=GRAY_LT, wrap=True)

    output_examples = [
        ("PROJECT PARSER", BLUE,
         'project_type: "highway"\nactions: ["grading","paving","drainage"]\nfederal_nexus: true\nscale: "large"'),
        ("ENV. DATA", CYAN,
         'usfws: ["Indiana bat","Northern long-eared bat"]\nnwi: [{"type":"PEM1C","acres":4.2}]\nfema: "Zone AE"\nfarmland: "Prime"\nejs_pctile: 72'),
        ("REG. SCREENING", GREEN,
         'name: "Section 7 ESA"\njurisdiction: "federal"\ncitation: "16 U.S.C. §1536"\nwhy: "Indiana bat present in project area"'),
        ("IMPACT MATRIX", ORANGE,
         'cells[wetlands×grading]:\n  significance: "significant"\n  confidence: 0.82\n  needs_review: false\n  framework: "Clean Water Act §404"'),
        ("REPORT SYNTHESIS", YELLOW,
         'Section 4 — Affected Environment:\n"The project corridor intersects 4.2 acres of\npalustrine emergent wetland (PEM1C) within\nthe 100-year floodplain (Zone AE)..."'),
    ]

    bw = Inches(2.3)
    bh = Inches(4.9)
    bgap = Inches(0.22)
    bx0 = Inches(0.5)
    by = Inches(1.75)
    for i, (label, color, sample) in enumerate(output_examples):
        bx = bx0 + i * (bw + bgap)
        bbox = slide.shapes.add_shape(1, bx, by, bw, bh)
        solid_fill(bbox, DARK_CARD)
        bbox.line.color.rgb = color
        bbox.line.width = Pt(1.5)
        hdr2 = slide.shapes.add_shape(1, bx, by, bw, Inches(0.38))
        solid_fill(hdr2, color)
        add_textbox(slide, label, bx + Inches(0.08), by + Inches(0.06),
                    bw - Inches(0.16), Inches(0.3),
                    font_size=9, bold=True, color=WHITE)
        add_textbox(slide, sample,
                    bx + Inches(0.12), by + Inches(0.46),
                    bw - Inches(0.24), bh - Inches(0.56),
                    font_size=10, color=GRAY_LT, wrap=True)

    add_image_placeholder(slide, "IMPORT RUN panel showing all 5 agent output sections",
                          Inches(0.6), Inches(6.8), Inches(12.1), Inches(0.5))

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 12 — Results: Evaluation Outputs
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Results — Evaluation Outputs")

    add_textbox(slide,
        "After running EVALUATE, the system returns six labeled scores and a per-category "
        "breakdown table. Results are persisted in evaluation_scores and auto-loaded on next visit.",
        Inches(0.6), Inches(1.1), Inches(12.1), Inches(0.5),
        font_size=13, color=GRAY_LT, wrap=True)

    # Score bars mockup
    score_items = [
        ("Overall Score",           "78%",  0.78,  ORANGE),
        ("Category F1",             "0.75", 0.75,  BLUE),
        ("Precision",               "0.83", 0.83,  CYAN),
        ("Recall",                  "0.67", 0.67,  GREEN),
        ("Significance Accuracy",   "0.81", 0.81,  YELLOW),
        ("Semantic Coverage",       "0.72", 0.72,  RGBColor(0xA7, 0x8B, 0xFA)),
    ]
    bar_x = Inches(0.6)
    bar_y = Inches(1.75)
    bar_max_w = Inches(5.5)
    bar_h = Inches(0.54)
    bar_gap = Inches(0.12)
    for i, (label, val_str, val, color) in enumerate(score_items):
        by2 = bar_y + i * (bar_h + bar_gap)
        # Label
        add_textbox(slide, label, bar_x, by2 + Inches(0.1), Inches(2.4), Inches(0.35),
                    font_size=12, color=WHITE)
        # Background track
        track = slide.shapes.add_shape(1, bar_x + Inches(2.5), by2 + Inches(0.12),
                                       bar_max_w, bar_h - Inches(0.24))
        solid_fill(track, RGBColor(0x1A, 0x20, 0x2C))
        # Filled bar
        filled_w = max(Inches(0.1), bar_max_w * val)
        fbar = slide.shapes.add_shape(1, bar_x + Inches(2.5), by2 + Inches(0.12),
                                      filled_w, bar_h - Inches(0.24))
        solid_fill(fbar, color)
        # Value label
        add_textbox(slide, val_str, bar_x + Inches(8.15), by2 + Inches(0.08),
                    Inches(0.8), Inches(0.35), font_size=13, bold=True, color=color)

    # Per-category breakdown table
    add_textbox(slide, "PER-CATEGORY BREAKDOWN", Inches(0.6), Inches(6.04),
                Inches(12.1), Inches(0.3), font_size=12, bold=True, color=ORANGE)
    table_headers = ["Category", "Label", "Agent Sig.", "GT Sig.", "Matched EIS Category"]
    col_widths = [Inches(2.1), Inches(1.0), Inches(1.3), Inches(1.1), Inches(6.4)]
    sample_rows = [
        ("wetlands",             "TP", "significant", "significant", "Wetlands and Waterways (§4.2.1)"),
        ("floodplain",           "TP", "moderate",    "moderate",    "Floodplain Management (§4.3)"),
        ("endangered_species",   "FP", "significant", "none",        "— (no EIS category matched)"),
        ("prime_farmland",       "FN", "none",        "moderate",    "Agricultural Resources (§4.5.2)"),
        ("environmental_justice","TP", "moderate",    "moderate",    "Environmental Justice (§4.8)"),
    ]
    label_colors = {"TP": GREEN, "FP": RED, "FN": YELLOW, "TN": CYAN}

    th_y = Inches(6.4)
    row_h2 = Inches(0.14)
    hdr_box = slide.shapes.add_shape(1, Inches(0.6), th_y, Inches(12.1), Inches(0.28))
    solid_fill(hdr_box, RGBColor(0x1A, 0x20, 0x2C))
    tx = Inches(0.6)
    for j, (hdr, cw) in enumerate(zip(table_headers, col_widths)):
        add_textbox(slide, hdr, tx, th_y + Inches(0.04), cw - Inches(0.05), Inches(0.22),
                    font_size=10, bold=True, color=ORANGE)
        tx += cw

    for ri, row_data in enumerate(sample_rows):
        ry2 = th_y + Inches(0.28) + ri * Inches(0.17)
        rbox = slide.shapes.add_shape(1, Inches(0.6), ry2, Inches(12.1), Inches(0.16))
        solid_fill(rbox, DARK_CARD if ri % 2 == 0 else BG)
        tx = Inches(0.6)
        for j, (cell_val, cw) in enumerate(zip(row_data, col_widths)):
            c = label_colors.get(cell_val, GRAY_LT) if j == 1 else (WHITE if j == 0 else GRAY_LT)
            add_textbox(slide, cell_val, tx, ry2 + Inches(0.01), cw - Inches(0.05), Inches(0.14),
                        font_size=9, bold=(j == 1), color=c)
            tx += cw

    add_image_placeholder(slide, "Actual evaluation scores panel screenshot from the app",
                          Inches(9.2), Inches(1.75), Inches(3.9), Inches(4.1))

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 13 — Results: Metric Calculations
    # ════════════════════════════════════════════════════════════════════════
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG)
    _add_header(slide, "Results — How Each Metric Is Calculated", font_size=26)

    metrics = [
        ("CATEGORY F1  ×0.40", BLUE,
         "8 agent-designed categories:\nwetlands · air_quality · noise · traffic\n"
         "environmental_justice · endangered_species\nfloodplain · prime_farmland\n\n"
         "TP: agent flagged AND EIS confirms impact\n"
         "FP: agent flagged BUT EIS has no impact\n"
         "FN: EIS has impact, agent did not flag\n\n"
         "Precision = TP / (TP+FP)\n"
         "Recall    = TP / (TP+FN)\n"
         "F1 = 2·P·R / (P+R)\n\n"
         "EIS categories outside the 8 agent categories are NOT counted against F1."),
        ("SIGNIFICANCE ACCURACY  ×0.40", GREEN,
         "Ordinal scale:\n  significant = 3\n  moderate    = 2\n  minimal     = 1\n  none        = 0\n\n"
         "For each matched (agent, GT) pair:\n"
         "  |diff| = 0  →  1.0 (exact)\n"
         "  |diff| = 1  →  0.5 (off by one level)\n"
         "  |diff| ≥ 2  →  0.0\n\n"
         "Score = mean across all matched pairs\n\n"
         "Partial credit for near-miss significance\ncalls avoids all-or-nothing binary scoring."),
        ("SEMANTIC COVERAGE  ×0.20", YELLOW,
         "Up to 10 agent reasoning snippets\nare embedded and compared against\nstored EIS chunks via cosine similarity.\n\n"
         "max_sim = argmax cosine(snippet, chunk)\nover all EIS chunks for that evaluation\n\n"
         "Score = mean max_sim over all snippets\n\n"
         "Measures: does the agent's written\nreasoning actually align with what\nthe real EIS document says?\n\n"
         "No LLM used — pure vector math on\nexisting stored embeddings (fast)."),
    ]

    col_w = Inches(3.9)
    col_gap = Inches(0.22)
    cx0 = Inches(0.6)
    cy = Inches(1.1)
    for i, (title, color, desc) in enumerate(metrics):
        bx = cx0 + i * (col_w + col_gap)
        mbox = slide.shapes.add_shape(1, bx, cy, col_w, Inches(5.65))
        solid_fill(mbox, DARK_CARD)
        mbox.line.color.rgb = color
        mbox.line.width = Pt(2)
        hdr3 = slide.shapes.add_shape(1, bx, cy, col_w, Inches(0.48))
        solid_fill(hdr3, color)
        add_textbox(slide, title, bx + Inches(0.1), cy + Inches(0.07),
                    col_w - Inches(0.2), Inches(0.38),
                    font_size=11, bold=True, color=WHITE)
        add_textbox(slide, desc, bx + Inches(0.15), cy + Inches(0.56),
                    col_w - Inches(0.3), Inches(4.85),
                    font_size=11, color=GRAY_LT, wrap=True)

    add_textbox(slide,
        "OVERALL  =  (Category F1 × 0.40)  +  (Significance Accuracy × 0.40)  +  (Semantic Coverage × 0.20)",
        Inches(0.6), Inches(6.9), Inches(12.1), Inches(0.42),
        font_size=13, bold=True, color=ORANGE, align=PP_ALIGN.CENTER)

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 14 — Discussion
    # ════════════════════════════════════════════════════════════════════════
    add_two_col_slide(prs, "Discussion",
        "CURRENT SHORTCOMINGS", [
            ("Ground truth is LLM-extracted, not human-annotated", 0, WHITE),
            ("LLM misread of EIS → corrupted GT → inflated scores", 1, GRAY_LT),
            ("Only 8 hardcoded categories evaluated (F1 scope)", 0, WHITE),
            ("Project-specific impacts (cultural resources, noise) invisible", 1, GRAY_LT),
            ("F1 is binary — partial detection gets no credit", 0, WHITE),
            ("Same concern under a different label = FP + FN", 1, GRAY_LT),
            ("Significance accuracy uses coarse ordinal scale", 0, WHITE),
            ("'Significant' is jurisdiction- and project-specific in practice", 1, GRAY_LT),
            ("Semantic coverage ≠ factual correctness", 0, WHITE),
            ("Style match can produce high cosine similarity without accurate reasoning", 1, GRAY_LT),
            ("LLM non-determinism: same run may score differently", 0, WHITE),
            ("No run-level repeatability metric currently", 1, GRAY_LT),
        ],
        "FUTURE IMPROVEMENTS", [
            ("Human-in-the-loop ground truth annotation", 0, WHITE),
            ("Domain experts verify LLM extractions → validated GT corpus", 1, GRAY_LT),
            ("Dynamic category set per project type", 0, WHITE),
            ("Replace 8 fixed categories with project-driven taxonomy", 1, GRAY_LT),
            ("LLM-as-Judge for reasoning quality", 0, WHITE),
            ("Separate evaluator LLM scores reasoning chains, not just hits", 1, GRAY_LT),
            ("Multi-document ensembling", 0, WHITE),
            ("Average GT across multiple EIS docs for same project type", 1, GRAY_LT),
            ("Confidence calibration curves", 0, WHITE),
            ("Track whether high-confidence cells are more accurate over time", 1, GRAY_LT),
            ("Citation verification", 0, WHITE),
            ("Verify cited regulations actually contain the claimed thresholds", 1, GRAY_LT),
            ("Run-level repeatability score", 0, WHITE),
            ("Multi-run variance tracking to quantify LLM non-determinism", 1, GRAY_LT),
        ]
    )

    # ════════════════════════════════════════════════════════════════════════
    # SLIDE 15 — Conclusion
    # ════════════════════════════════════════════════════════════════════════
    add_bullet_slide(prs, "Conclusion", [
        ("Automated NEPA screening from weeks to minutes", 0, ORANGE),
        ("5-agent pipeline covers data gathering, regulatory RAG, impact analysis, and report writing", 1, GRAY_LT),
        ("Full traceability: every impact cell cites the regulation and data that drove it", 1, GRAY_LT),
        ("Switchable LLM providers (OpenAI, Anthropic, Ollama) with no code changes", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Confidence-aware — not a black box", 0, ORANGE),
        ("5-tier confidence model anchored to data quality and regulatory specificity", 1, GRAY_LT),
        ("Cells below 0.6 confidence are automatically flagged for human expert review", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Quantitative evaluation against real EIS documents", 0, ORANGE),
        ("3-metric scoring: Category F1, Significance Accuracy, Semantic Coverage", 1, GRAY_LT),
        ("Ground truth extraction cached — re-scoring is fast and low-cost", 1, GRAY_LT),
        ("Per-category TP/FP/FN breakdown supports targeted agent improvement", 1, GRAY_LT),
        ("", 0, WHITE),
        ("Future Work", 0, WHITE),
        ("Human-annotated GT corpus · dynamic category taxonomy · LLM-as-Judge", 1, GRAY_LT),
        ("Multi-project comparison dashboard · automated agency submission integration", 1, GRAY_LT),
        ("Expand from screening-level EA to full EIS generation", 1, GRAY_LT),
    ])

    prs.save(output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    potx = "/Users/sanderschulman/Developer/aiagentsproject/24-880 Presentation Template (1).potx"
    out  = "/Users/sanderschulman/Developer/aiagentsproject/EIA_Agent_System_Presentation.pptx"
    build(potx, out)
