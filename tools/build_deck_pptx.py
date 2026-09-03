#!/usr/bin/env python
"""Build the TVS Credit EPIC 8.0 deck as a native .pptx.

Native shapes and text boxes rather than exported images, so every slide stays
editable in PowerPoint — a judge's laptop opens it, and the team can change a
figure without re-rendering anything.

Palette is the ratified TVS ramp from frontend/tailwind.config.ts. Semantic
colours carry meaning: green means a machine computed it, amber means a
committee owes us the number.
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# ---- palette (frontend/tailwind.config.ts) ---------------------------------
BRAND_900 = RGBColor(0x0A, 0x3A, 0x68)
BRAND_700 = RGBColor(0x0D, 0x4A, 0x85)
BRAND_500 = RGBColor(0x21, 0x66, 0xA3)
BRAND_200 = RGBColor(0xAD, 0xC9, 0xE5)
BRAND_100 = RGBColor(0xD6, 0xE4, 0xF2)
BRAND_50 = RGBColor(0xEE, 0xF4, 0xFA)
COMPUTED = RGBColor(0x06, 0x76, 0x47)
COMPUTED_BG = RGBColor(0xE8, 0xF5, 0xEF)
BLOCKED = RGBColor(0xB5, 0x47, 0x08)
BLOCKED_BG = RGBColor(0xFD, 0xF3, 0xEA)
INK = RGBColor(0x10, 0x18, 0x28)
INK2 = RGBColor(0x47, 0x54, 0x67)
INK3 = RGBColor(0x6B, 0x7C, 0x93)
RULE = RGBColor(0xDB, 0xE3, 0xEC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GROUND = RGBColor(0xF7, 0xF9, 0xFB)

DISPLAY = "Georgia"          # serif, present on Windows and macOS
BODY = "Segoe UI"            # falls back gracefully on macOS
MONO = "Consolas"

W, H = Inches(13.333), Inches(7.5)   # 16:9
M = Inches(0.72)                     # side margin


def new_deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    return prs


def blank(prs, bg=WHITE):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    fill = s.background.fill
    fill.solid()
    fill.fore_color.rgb = bg
    return s


def box(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tf


def para(tf, text, *, size=14, color=INK2, bold=False, font=BODY,
         space_after=6, space_before=0, first=False, spacing=1.0,
         align=PP_ALIGN.LEFT, caps_track=None):
    """One paragraph. A "\n" becomes a real line break inside it.

    python-pptx keeps a run's text literal, so an embedded newline is dropped
    on render — "Smart\nLending" arrives as "SmartLending". Splitting into runs
    with explicit breaks keeps the author's line breaks in headlines, which is
    where they carry meaning.
    """
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    lines = text.split("\n")
    p.text = lines[0]
    for extra in lines[1:]:
        run = p.add_run()
        run.text = extra
        run._r.addprevious(run._r.makeelement(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}br", {}))
    p.alignment = align
    p.space_after = Pt(space_after)
    p.space_before = Pt(space_before)
    p.line_spacing = spacing
    for run in p.runs:
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.bold = bold
        run.font.name = font
    return p


def rect(slide, x, y, w, h, fill=None, line=None, line_w=0.75):
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(line_w)
    sh.shadow.inherit = False
    sh.text_frame.word_wrap = True
    return sh


def eyebrow(slide, text, y=Inches(0.5), color=BRAND_500):
    tf = box(slide, M, y, Inches(11.0), Inches(0.3))
    para(tf, text.upper(), size=10.5, color=color, font=MONO, first=True,
         space_after=0)


def heading(slide, text, y=Inches(0.85), size=32, color=BRAND_900,
            width=Inches(11.4)):
    tf = box(slide, M, y, width, Inches(1.0))
    para(tf, text, size=size, color=color, bold=True, font=DISPLAY,
         first=True, space_after=0, spacing=0.95)


def slide_num(slide, n):
    tf = box(slide, Inches(12.4), Inches(0.42), Inches(0.6), Inches(0.25))
    para(tf, n, size=9, color=INK3, font=MONO, first=True, space_after=0,
         align=PP_ALIGN.RIGHT)


def note(slide, x, y, w, h, text, *, kind="info"):
    """A tinted callout with a left accent bar — the deck's one repeated device."""
    bg, bar = BRAND_50, BRAND_500
    if kind == "warn":
        bg, bar = BLOCKED_BG, BLOCKED
    elif kind == "good":
        bg, bar = COMPUTED_BG, COMPUTED
    rect(slide, x, y, w, h, fill=bg)
    rect(slide, x, y, Inches(0.04), h, fill=bar)
    tf = box(slide, x + Inches(0.22), y + Inches(0.13), w - Inches(0.42),
             h - Inches(0.26))
    para(tf, text, size=11.5, color=INK2, first=True, space_after=0,
         spacing=1.18)


def metric(slide, x, y, w, value, label, *, accent=BRAND_700):
    """A figure that IS the point of its slide, with a rule above it."""
    rect(slide, x, y, w, Inches(0.028), fill=accent)
    tf = box(slide, x, y + Inches(0.14), w, Inches(0.55))
    para(tf, value, size=28, color=accent, bold=True, font=DISPLAY,
         first=True, space_after=0)
    tf2 = box(slide, x, y + Inches(0.72), w, Inches(1.15))
    para(tf2, label, size=10, color=INK2, first=True, space_after=0,
         spacing=1.15)


def row(slide, x, y, w, tag, title, sub, *, tag_color=BRAND_700, rule=True):
    """One line of a list: mono tag, title, and a quieter subtitle."""
    tf = box(slide, x, y, Inches(0.85), Inches(0.28))
    para(tf, tag, size=10, color=tag_color, bold=True, font=MONO, first=True,
         space_after=0)
    tf2 = box(slide, x + Inches(0.9), y, w - Inches(0.9), Inches(0.28))
    para(tf2, title, size=12, color=INK, first=True, space_after=0)
    tf3 = box(slide, x + Inches(0.9), y + Inches(0.235), w - Inches(0.9),
              Inches(0.42))
    para(tf3, sub, size=9.5, color=INK3, first=True, space_after=0, spacing=1.1)
    if rule:
        rect(slide, x, y + Inches(0.66), w, Emu(9525), fill=RULE)


# ============================================================ slides =========

def cover(prs):
    s = blank(prs, BRAND_900)
    rect(s, Inches(0), Inches(0), W, H, fill=BRAND_900)
    # A single diagonal accent, the only decorative mark in the deck.
    rect(s, Inches(9.6), Inches(0), Inches(3.8), H, fill=BRAND_700)
    rect(s, Inches(12.2), Inches(0), Inches(1.2), H, fill=BRAND_500)

    tf = box(s, M, Inches(1.0), Inches(8.6), Inches(0.3))
    para(tf, "TVS CREDIT EPIC 8.0  ·  IT CHALLENGE", size=11, color=BRAND_200,
         font=MONO, first=True, space_after=0)

    tf = box(s, M, Inches(1.55), Inches(8.6), Inches(2.2))
    para(tf, "AI-Powered Smart\nLending Decision Hub", size=44, color=WHITE,
         bold=True, font=DISPLAY, first=True, space_after=0, spacing=0.98)

    tf = box(s, M, Inches(3.95), Inches(8.3), Inches(1.5))
    para(tf,
         "An integrated lending platform for agriculture-based customers — "
         "satellite, weather and crop intelligence, AI credit scoring, fraud "
         "detection, a recommendation engine, default prediction, a GenAI "
         "assistant, real-time risk dashboards, and early warning for defaulters.",
         size=13.5, color=BRAND_100, first=True, space_after=0, spacing=1.28)

    rect(s, M, Inches(5.75), Inches(8.3), Emu(9525), fill=BRAND_500)
    facts = [("8 phases", "P0 platform → P7 interfaces"),
             ("23 packages", "63,000 lines, stdlib core"),
             ("2,318 tests", "green, every commit"),
             ("16.8M rows", "real loan performance")]
    for i, (big, small) in enumerate(facts):
        x = M + Inches(2.12) * i
        tf = box(s, x, Inches(6.0), Inches(2.0), Inches(0.3))
        para(tf, big, size=14, color=WHITE, bold=True, first=True, space_after=0)
        tf = box(s, x, Inches(6.32), Inches(2.0), Inches(0.4))
        para(tf, small, size=9, color=BRAND_200, font=MONO, first=True,
             space_after=0, spacing=1.1)


def thesis(prs):
    s = blank(prs)
    slide_num(s, "02")
    eyebrow(s, "The problem behind the problem")
    heading(s, "A lending model is easy to build\nand hard to trust", size=30)

    tf = box(s, M, Inches(2.35), Inches(6.5), Inches(3.9))
    para(tf, "Any team can produce a credit score in a weekend. The score is "
             "not the hard part — knowing whether you are allowed to believe "
             "it is.", size=15, color=INK, first=True, space_after=16,
         spacing=1.3)
    para(tf, "A plausible-looking cutoff that nobody ratified survives code "
             "review, ships, and is still in a report a year later. An agri "
             "model validated on the wrong agro-zone looks identical to one "
             "validated correctly. A default model scored on the window it was "
             "trained on reports excellent numbers and fails in production.",
         size=12, color=INK2, space_after=16, spacing=1.42)
    para(tf, "So this build inverts the usual priority. Every number must trace "
             "to one of three sources, and code that cannot find one refuses to "
             "run rather than guessing.",
         size=12, color=INK2, space_after=0, spacing=1.42)

    x = Inches(7.6)
    tf = box(s, x, Inches(2.35), Inches(5.0), Inches(0.3))
    para(tf, "THE GROUNDING CONTRACT", size=10, color=INK3, font=MONO,
         first=True, space_after=0)
    items = [("[SPEC]", "Written in the specification",
              "A formula, a threshold the document fixes"),
             ("[DATA]", "Computed by a committed script",
              "Rerunnable, versioned, auditable"),
             ("[POLICY]", "Supplied by a named committee",
              "In writing, with an owner")]
    for i, (tag, title, sub) in enumerate(items):
        row(s, x, Inches(2.8) + Inches(0.82) * i, Inches(5.0), tag, title, sub)

    note(s, x, Inches(5.5), Inches(5.0), Inches(1.05),
         "Anything else is a build failure. A grounding check scans 350 files "
         "on every commit and fails the build on an ungrounded value.",
         kind="warn")


def challenges(prs):
    """The problem, from both sides of the counter."""
    s = blank(prs)
    slide_num(s, "03")
    eyebrow(s, "The problem")
    heading(s, "What breaks today, for the farmer\nand for the bank", size=30)

    tf = box(s, M, Inches(2.3), Inches(11.5), Inches(0.4))
    para(tf, "Agricultural lending fails on both sides at once, and the two "
             "failures cause each other: thin files make banks cautious, and "
             "caution pushes farmers to informal credit that leaves no file.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    left = [
        ("No credit file", "Income is seasonal and in cash. A bureau score "
         "either does not exist or describes someone else's risk."),
        ("Weeks to a decision", "Manual field visits and paper appraisal. The "
         "sowing window closes while the file moves."),
        ("No explanation", "A rejection arrives without a reason the borrower "
         "can act on, so nothing improves before the next application."),
        ("Wrong product", "A tenor that ignores the harvest calendar turns a "
         "good borrower into a delinquent one."),
    ]
    right = [
        ("Thin-file underwriting", "Traditional scorecards have little signal, "
         "so good farmers are declined alongside bad ones."),
        ("Unverifiable collateral", "Land records and actual cultivation "
         "disagree, and a field visit costs more than the loan earns."),
        ("Fraud rings", "Shared devices, addresses and accounts across "
         "applications that look independent one at a time."),
        ("Late warning", "Distress is visible in behaviour months before a "
         "missed EMI, and nobody is watching for it."),
    ]

    for col, (title, items, colour) in enumerate([
            ("FOR THE CUSTOMER", left, BRAND_700),
            ("FOR THE BANK", right, BLOCKED)]):
        x = M + Inches(6.1) * col
        tf = box(s, x, Inches(2.95), Inches(5.6), Inches(0.28))
        para(tf, title, size=9.5, color=colour, bold=True, font=MONO,
             first=True, space_after=0)
        for i, (h, body) in enumerate(items):
            yy = Inches(3.38) + Inches(0.97) * i
            rect(s, x, yy + Inches(0.06), Inches(0.03), Inches(0.6), fill=colour)
            tf = box(s, x + Inches(0.2), yy, Inches(5.4), Inches(0.26))
            para(tf, h, size=12.5, color=INK, bold=True, first=True,
                 space_after=0)
            tf = box(s, x + Inches(0.2), yy + Inches(0.27), Inches(5.4),
                     Inches(0.55))
            para(tf, body, size=10.5, color=INK2, first=True, space_after=0,
                 spacing=1.18)


def solution(prs):
    """One row per problem, and the module that answers it."""
    s = blank(prs)
    slide_num(s, "04")
    eyebrow(s, "How the platform answers each one")
    heading(s, "Every problem maps to a module that exists")

    pairs = [
        ("No credit file", "Satellite + weather + crop evidence",
         "M1 · agri", "SPI/SPEI drought indices and vegetation time series make "
         "the land itself the evidence when the bureau has nothing."),
        ("Weeks to a decision", "Scoring in the serving path",
         "M2 · scoring", "A scorecard and a GBM challenger behind one "
         "orchestrator, with SHAP reason codes attached to the decision."),
        ("Fraud rings", "Entity resolution and community detection",
         "M3 · fraud", "Shared phone, device, address and account edges; "
         "Louvain finds the dense cluster that no single application shows."),
        ("Wrong product", "Feasible set before recommendation",
         "M4 · reco", "The bandit may only choose inside what policy already "
         "permits — affordability is a constraint, never a suggestion."),
        ("No explanation", "Templated reasons and a grounded assistant",
         "M6 · assistant", "Answers carry citations or are refused; decision "
         "explanations are selected from approved templates, never composed."),
        ("Late warning", "Change-point detection on behaviour",
         "M8 · ews", "86% of defaults caught a median 365 days early, measured "
         "on 338,210 real account-months."),
    ]

    y = Inches(1.95)
    for problem, answer, mod, detail in pairs:
        rect(s, M, y + Inches(0.05), Inches(0.03), Inches(0.66), fill=COMPUTED)
        tf = box(s, M + Inches(0.2), y, Inches(2.6), Inches(0.28))
        para(tf, problem, size=11.5, color=INK3, first=True, space_after=0)
        # 7.9in of title width keeps every answer on one line, so the detail
        # line below can never be overprinted by a wrap.
        tf = box(s, Inches(3.5), y, Inches(7.9), Inches(0.28))
        para(tf, answer, size=12, color=INK, bold=True, first=True,
             space_after=0)
        tf = box(s, Inches(3.5), y + Inches(0.28), Inches(7.9), Inches(0.44))
        para(tf, detail, size=10, color=INK2, first=True, space_after=0,
             spacing=1.15)
        tf = box(s, Inches(11.6), y, Inches(1.3), Inches(0.28))
        para(tf, mod, size=9.5, color=BRAND_700, font=MONO, first=True,
             space_after=0)
        y += Inches(0.87)


def flow(prs):
    """The path one application takes, end to end."""
    s = blank(prs)
    slide_num(s, "05")
    eyebrow(s, "How it works")
    heading(s, "One application, end to end")

    tf = box(s, M, Inches(1.8), Inches(11.5), Inches(0.4))
    para(tf, "Every step writes to the decision log, and every model-derived "
             "value carries its model id, version and decision-log reference "
             "the whole way to the screen.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    steps = [
        ("1", "APPLY", "Customer app", "KYC, consent, documents. The consent "
         "artifact is logged with the same rigour as the credit decision."),
        ("2", "ENRICH", "agri · bureau", "Plot polygon, drought index, "
         "vegetation series, bureau pull, cash-flow summary."),
        ("3", "SCREEN", "fraud", "Entity resolution across phone, device, "
         "address; velocity and anomaly layers; graph communities."),
        ("4", "SCORE", "scoring", "Scorecard and GBM challenger; SHAP reason "
         "codes; the policy band decides approve, review or decline."),
        ("5", "OFFER", "reco", "Feasible set from ratified caps, ALM pricing, "
         "then the bandit ranks inside what policy permits."),
        ("6", "MONITOR", "portfolio · ews", "PD/LGD/EAD re-estimated monthly; "
         "change-point detection on behaviour raises alerts with an owner."),
    ]

    n = len(steps)
    bw = Inches(1.83)
    gap = Inches(0.16)
    y = Inches(2.55)
    for i, (num, title, mod, body) in enumerate(steps):
        x = M + (bw + gap) * i
        rect(s, x, y, bw, Inches(2.5), fill=None, line=RULE)
        rect(s, x, y, bw, Inches(0.045), fill=BRAND_700)
        tf = box(s, x + Inches(0.16), y + Inches(0.22), bw - Inches(0.3),
                 Inches(0.25))
        para(tf, num, size=11, color=BRAND_500, bold=True, font=MONO,
             first=True, space_after=0)
        tf = box(s, x + Inches(0.16), y + Inches(0.52), bw - Inches(0.3),
                 Inches(0.25))
        para(tf, title, size=12.5, color=BRAND_900, bold=True, font=DISPLAY,
             first=True, space_after=0)
        tf = box(s, x + Inches(0.16), y + Inches(0.82), bw - Inches(0.3),
                 Inches(0.22))
        para(tf, mod, size=8.5, color=INK3, font=MONO, first=True,
             space_after=0)
        tf = box(s, x + Inches(0.16), y + Inches(1.12), bw - Inches(0.3),
                 Inches(1.25))
        para(tf, body, size=9, color=INK2, first=True, space_after=0,
             spacing=1.16)
        if i < n - 1:
            tf = box(s, x + bw + Inches(0.01), y + Inches(1.15),
                     Inches(0.16), Inches(0.3))
            para(tf, "\u203a", size=15, color=BRAND_200, bold=True, first=True,
                 space_after=0, align=PP_ALIGN.CENTER)

    note(s, M, Inches(5.35), Inches(11.9), Inches(0.95),
         "The gateway is the only thing the interfaces talk to — never a model "
         "service directly. A response that renders a score without its model "
         "id and version is rejected by the client rather than displayed, so an "
         "unattributable number cannot reach a screen.")

    note(s, M, Inches(6.45), Inches(11.9), Inches(0.72),
         "Where a step needs a value nobody has ratified, it stops and names "
         "the ticket and its owner. Seventeen of the gateway's twenty-one "
         "routes do exactly that today.", kind="warn")


def scope(prs):
    s = blank(prs)
    slide_num(s, "06")
    eyebrow(s, "Scope")
    heading(s, "Every module in the brief, built")

    tf = box(s, M, Inches(1.85), Inches(11.5), Inches(0.6))
    para(tf, "Eight phases, twenty-three packages. The core is standard-library "
             "Python throughout — every algorithm is a reference port naming the "
             "library it replaces, so a bank swaps in LightGBM or lifelines "
             "behind the same interface without touching a call site.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    cols = [
        ("DECISIONING", [
            ("P1", "Credit scoring", "WoE scorecard + GBM challenger, SHAP reasons, fairness"),
            ("P1", "Fraud detection", "Entity resolution, velocity, anomaly, documents"),
            ("P4", "Recommendations", "Feasible set, ALM pricing, LinUCB bandit, suitability")]),
        ("RISK & AGRICULTURE", [
            ("P2", "Agri intelligence", "SPI/SPEI drought, NDVI/EVI, plot registry, yield"),
            ("P3", "Portfolio brain", "PD/LGD/EAD, Cox & discrete hazard, IFRS 9 staging"),
            ("P4", "Early warning", "Signals, velocity, BOCPD change-point, routing")]),
        ("DELIVERY", [
            ("P5", "GenAI assistant", "Hybrid retrieval, citation contract, validator"),
            ("P6", "Learning loops", "Promotion gate, uplift, off-policy, Louvain"),
            ("P7", "Interfaces", "Officer workbench, collections console, dashboards")]),
    ]
    for c, (title, rows) in enumerate(cols):
        x = M + Inches(4.06) * c
        tf = box(s, x, Inches(2.95), Inches(3.7), Inches(0.28))
        para(tf, title, size=9.5, color=INK3, font=MONO, first=True,
             space_after=0)
        for i, (tag, name, sub) in enumerate(rows):
            row(s, x, Inches(3.42) + Inches(1.26) * i, Inches(3.7), tag, name, sub)


def tracks(prs):
    s = blank(prs)
    slide_num(s, "07")
    eyebrow(s, "The method")
    heading(s, "Three tracks, one interface — and only one counts")

    tf = box(s, M, Inches(1.85), Inches(11.5), Inches(0.6))
    para(tf, "This repository has no bank attached. Pretending otherwise is the "
             "easiest way to produce a number that looks like evidence and is "
             "not. So every figure in every report is stamped with the track "
             "that produced it.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    cards = [
        ("TRACK A", "Local reference", BRAND_700, BRAND_50,
         "Runs on a laptop, stdlib-only, on synthetic fixtures. Proves the code "
         "paths: joins, point-in-time correctness, the serving path, audit "
         "arithmetic."),
        ("TRACK P", "Public reference data", COMPUTED, COMPUTED_BG,
         "Real loans, real applications. Proves the code survives what fixtures "
         "cannot simulate — real missingness, real class imbalance, real key "
         "defects. Real data, but not this bank's."),
        ("TRACK B", "Bank deployment", BLOCKED, BLOCKED_BG,
         "Same interfaces, real backends. The only track that is gate evidence. "
         "A Gini on US consumer loans is a fact about US consumer lending."),
    ]
    for i, (tag, title, col, bg, body) in enumerate(cards):
        x = M + Inches(4.06) * i
        rect(s, x, Inches(2.75), Inches(3.7), Inches(2.75), fill=None, line=RULE)
        rect(s, x, Inches(2.75), Inches(3.7), Inches(0.04), fill=col)
        tf = box(s, x + Inches(0.25), Inches(2.98), Inches(3.2), Inches(0.25))
        para(tf, tag, size=9.5, color=col, bold=True, font=MONO, first=True,
             space_after=0)
        tf = box(s, x + Inches(0.25), Inches(3.3), Inches(3.2), Inches(0.3))
        para(tf, title, size=14, color=INK, bold=True, font=DISPLAY, first=True,
             space_after=0)
        tf = box(s, x + Inches(0.25), Inches(3.72), Inches(3.25), Inches(1.3))
        para(tf, body, size=10.5, color=INK2, first=True, space_after=0,
             spacing=1.22)

    note(s, M, Inches(5.85), Inches(11.9), Inches(1.05),
         "A join rate computed on fixtures is a test of the audit script. A "
         "capture rate on a public mortgage panel is a fact about US mortgages. "
         "Both are useful. Neither is a gate number, and the reports say so on "
         "every line.")


def results(prs):
    s = blank(prs)
    slide_num(s, "08")
    eyebrow(s, "Track P results  ·  real public data")
    heading(s, "What the pipelines actually produce")

    tf = box(s, M, Inches(1.8), Inches(11.5), Inches(0.4))
    para(tf, "Two full pipelines run end to end on real datasets: 150,000 real "
             "credit applications, and a 19-year mortgage panel of 16.8 million "
             "performance rows.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    heads = ["MODEL", "DATASET", "ROWS", "TEST GINI", "TEST AUC"]
    widths = [Inches(3.5), Inches(2.5), Inches(1.8), Inches(2.0), Inches(2.0)]
    y = Inches(2.5)
    x = M
    for h, w in zip(heads, widths):
        tf = box(s, x, y, w, Inches(0.25))
        para(tf, h, size=9, color=INK3, font=MONO, first=True, space_after=0)
        x += w
    rect(s, M, y + Inches(0.3), Inches(11.8), Emu(12700),
         fill=RGBColor(0xB9, 0xC8, 0xD8))

    rows = [
        ("WoE scorecard  (champion)", "Home Credit", "150,000", "46.86", "0.7343"),
        ("GBM  (challenger)", "Home Credit", "150,000", "51.94", "0.7597"),
        ("Discrete-time hazard", "Fannie Mae panel", "338,210", "—", "0.6127"),
        ("Cox proportional hazards", "Fannie Mae panel", "338,210", "c-idx 0.6967", "—"),
    ]
    for r, cells in enumerate(rows):
        yy = y + Inches(0.46) + Inches(0.44) * r
        x = M
        for c, (cell, w) in enumerate(zip(cells, widths)):
            tf = box(s, x, yy, w, Inches(0.3))
            para(tf, cell, size=11.5,
                 color=INK if c >= 2 else INK2,
                 font=MONO if c >= 2 else BODY, first=True, space_after=0)
            x += w
        rect(s, M, yy + Inches(0.34), Inches(11.8), Emu(9525), fill=RULE)

    note(s, M, Inches(4.9), Inches(11.9), Inches(0.95),
         "The GBM's train Gini is 57.79 against a test Gini of 51.94. That gap "
         "is reported rather than tuned away — a challenger whose train and test "
         "numbers match exactly has usually been fitted to its own test set.")

    note(s, M, Inches(6.05), Inches(11.9), Inches(0.75),
         "These are Track P numbers: real loans, real missingness, and not this "
         "bank's book. Evidence about the implementation, not gate evidence.",
         kind="warn")


def ews(prs):
    s = blank(prs)
    slide_num(s, "09")
    eyebrow(s, "Early warning  ·  the question that matters")
    heading(s, "Does deterioration precede default, and by how long?", size=29)

    tf = box(s, M, Inches(2.15), Inches(6.2), Inches(2.6))
    para(tf, "The early-warning system rests on one premise: an account in "
             "trouble shows it before it misses a payment. That premise is "
             "testable, and it was tested — on 338,210 real account-months, "
             "scoring only the 101 defaults the detector could actually have "
             "reached.",
         size=12, color=INK2, first=True, space_after=11, spacing=1.28)
    para(tf, "At the 95th-percentile threshold the detector catches 86% of "
             "reachable defaults with a median lead time of one full year. "
             "Tighten to the 99th and capture collapses to 56% — the curve is "
             "the operating decision, and it belongs to the Collections Head.",
         size=12, color=INK2, space_after=0, spacing=1.28)

    note(s, M, Inches(5.0), Inches(6.2), Inches(1.65),
         "A correction to our own work. The first run reported 11% capture. "
         "726 of 827 defaults fell before the detector's first scoreable "
         "snapshot — the number was measuring the train/test split, not the "
         "detector. Scoring only reachable defaults moved it 8×.",
         kind="good")

    # chart
    cx, cy = Inches(7.4), Inches(2.25)
    cw, ch = Inches(5.2), Inches(3.1)
    tf = box(s, cx, cy - Inches(0.35), cw, Inches(0.25))
    para(tf, "CAPTURE RATE BY ALERT THRESHOLD", size=9, color=INK3, font=MONO,
         first=True, space_after=0)

    base = cy + ch
    bars = [("p90", 0.911, "562d", BRAND_700),
            ("p95", 0.861, "365d", BRAND_500),
            ("p98", 0.822, "183d", RGBColor(0x4A, 0x83, 0xBD)),
            ("p99", 0.564, "153d", BLOCKED)]
    bw = Inches(0.82)
    gap = Inches(1.22)
    for i, (lab, val, lead, col) in enumerate(bars):
        bh = Emu(int(ch * val))
        bx = cx + Inches(0.42) + gap * i
        rect(s, bx, base - bh, bw, bh, fill=col)
        tf = box(s, bx - Inches(0.15), base - bh - Inches(0.3),
                 bw + Inches(0.3), Inches(0.26))
        para(tf, f"{val:.1%}", size=11, color=BRAND_900, bold=True, font=MONO,
             first=True, space_after=0, align=PP_ALIGN.CENTER)
        tf = box(s, bx - Inches(0.15), base + Inches(0.06),
                 bw + Inches(0.3), Inches(0.24))
        para(tf, lab, size=10, color=INK2, font=MONO, first=True, space_after=0,
             align=PP_ALIGN.CENTER)
        tf = box(s, bx - Inches(0.15), base + Inches(0.3),
                 bw + Inches(0.3), Inches(0.24))
        para(tf, lead, size=9, color=INK3, font=MONO, first=True, space_after=0,
             align=PP_ALIGN.CENTER)
    rect(s, cx, base, cw, Emu(12700), fill=RGBColor(0xB9, 0xC8, 0xD8))
    tf = box(s, cx, base + Inches(0.62), cw, Inches(0.24))
    para(tf, "Median lead time to default  ·  Track P  ·  Fannie Mae",
         size=9, color=INK3, font=MONO, first=True, space_after=0)


def refusals(prs):
    s = blank(prs)
    slide_num(s, "10")
    eyebrow(s, "The differentiator")
    heading(s, "The system refuses to invent numbers")

    rect(s, M, Inches(1.85), Inches(0.035), Inches(0.85), fill=BRAND_700)
    tf = box(s, M + Inches(0.3), Inches(1.85), Inches(11.0), Inches(0.9))
    para(tf, "“A plausible-looking invented cutoff is worse than a build "
             "failure, because it survives review.”",
         size=17, color=BRAND_900, font=DISPLAY, first=True, space_after=6,
         spacing=1.18)
    para(tf, "The working agreement, enforced by CI", size=9.5, color=INK3,
         font=MONO, space_after=0)

    tf = box(s, M, Inches(2.95), Inches(11.5), Inches(0.4))
    para(tf, "These are not error states. Each is a place where a default value "
             "would have become the production value, because nobody ever "
             "passed the argument.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    left = [("P2", "expected_income() raises",
             "Without ratified input costs, the sign of the answer on a smallholder plot is unknown"),
            ("P2", "area_hectares raises",
             "A nominal area around a village centroid is not a plot"),
            ("P4", "Reward.blended() raises",
             "A bandit rewarded on take-up alone learns to mis-sell")]
    right = [("P5", "No sentence composed",
              "No code path writes an adverse-action sentence; templates are selected"),
             ("P6", "estimate_uplift() raises",
              "Uplift from an unrandomised log is not a worse estimate — it is a different quantity"),
             ("P7", "No demo data",
              "A fabricated score is indistinguishable from a real one in a screenshot")]
    for i, (tag, title, sub) in enumerate(left):
        row(s, M, Inches(3.68) + Inches(0.82) * i, Inches(5.7), tag, title, sub)
    for i, (tag, title, sub) in enumerate(right):
        row(s, Inches(7.0), Inches(3.68) + Inches(0.82) * i, Inches(5.7),
            tag, title, sub)

    note(s, M, Inches(6.2), Inches(11.9), Inches(0.85),
         "98 blocking tickets are registered, each with a named owner and the "
         "exact decision required. That register is the honest project plan: it "
         "says what a bank must decide before any of this scores a real customer.",
         kind="warn")


def guarantees(prs):
    s = blank(prs)
    slide_num(s, "11")
    eyebrow(s, "Engineering")
    heading(s, "Guarantees held by the type system, not by review")

    tf = box(s, M, Inches(1.85), Inches(11.5), Inches(0.4))
    para(tf, "A rule enforced by a code-review comment is a rule that lapses the "
             "first busy week. These are enforced by constructors, so the "
             "dangerous state cannot be represented at all.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    tiles = [("100%", "Bandit propensity completeness — a decision cannot be "
                      "constructed without one, so off-policy evaluation stays "
                      "possible later", COMPUTED),
             ("0", "Uncited numeric claims — the validated answer is the only "
                   "servable type and strips them before the object exists",
              COMPUTED),
             ("0", "Fabricated values served by the API gateway — every route "
                   "either computes or refuses with a ticket", COMPUTED),
             ("2,318", "Tests green on every commit, alongside grounding and "
                       "schema-compatibility gates", BRAND_700)]
    for i, (val, lab, col) in enumerate(tiles):
        metric(s, M + Inches(3.03) * i, Inches(2.7), Inches(2.75), val, lab,
               accent=col)

    note(s, M, Inches(5.15), Inches(11.9), Inches(0.9),
         "An alert cannot exist without an owner, an SLA and a recommended "
         "action — because an alert missing any of the three is a notification, "
         "and the difference stops being visible once it is in a queue.",
         kind="good")

    note(s, M, Inches(6.25), Inches(11.9), Inches(0.8),
         "The frontend cannot compute an EMI: a build gate fails the project if "
         "any screen does arithmetic on a money figure. Every number on screen "
         "arrives from the backend carrying its model id and version.")


def findings(prs):
    s = blank(prs)
    slide_num(s, "12")
    eyebrow(s, "What building it found")
    heading(s, "82 findings raised against the specification")

    tf = box(s, M, Inches(1.85), Inches(11.5), Inches(0.4))
    para(tf, "Building against a document is the only reliable way to test it. "
             "Each finding is a place where the specification read as complete "
             "until code had to produce a number.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    items = [
        ("P4-F1", "The change-point instruction names a quantity that is "
                  "identically the hazard rate under constant hazard — it detects "
                  "nothing, on any data. The real signal is one index over.",
         "Correction"),
        ("P6-F1", "Uplift from observational logs is unidentifiable, not merely "
                  "unmeasured — more data narrows the interval around a biased "
                  "number, turning visible uncertainty into invisible bias.",
         "Method"),
        ("P7-F1", "The frontend phase cites SRS §11.4–§11.8 and UX-1…UX-9 as "
                  "binding. None exists. The screen inventory it depends on is "
                  "unrecoverable.", "Document defect"),
        ("P5-F2", "Effective dates cannot express partial supersession — two "
                  "circulars in force, one amending the other in part. Both pass "
                  "the filter; the model picks.", "Gap"),
        ("P4-F11", "A correction to our own first result: capture was scored "
                   "against defaults the detector could never have reached, "
                   "measuring the split rather than the model.", "Self-correction"),
    ]
    y = Inches(2.55)
    for tag, text, kind in items:
        tf = box(s, M, y, Inches(0.95), Inches(0.3))
        para(tf, tag, size=10.5, color=BRAND_700, bold=True, font=MONO,
             first=True, space_after=0)
        tf = box(s, M + Inches(1.05), y, Inches(8.3), Inches(0.75))
        para(tf, text, size=11, color=INK2, first=True, space_after=0,
             spacing=1.22)
        tf = box(s, Inches(10.25), y, Inches(2.35), Inches(0.3))
        para(tf, kind, size=10, color=INK3, font=MONO, first=True, space_after=0)
        rect(s, M, y + Inches(0.78), Inches(11.9), Emu(9525), fill=RULE)
        y += Inches(0.92)


def working(prs):
    s = blank(prs)
    slide_num(s, "13")
    eyebrow(s, "It runs")
    heading(s, "A working stack, end to end")

    tf = box(s, M, Inches(1.9), Inches(6.3), Inches(2.6))
    para(tf, "A standard-library HTTP gateway serves the interface surfaces. "
             "Four routes return values computed by the engines; seventeen "
             "return a structured refusal naming the ticket, its owner and the "
             "reason.",
         size=12, color=INK2, first=True, space_after=11, spacing=1.28)
    para(tf, "The frontend is Next.js and TypeScript, and the attribution "
             "triplet is a type: a component cannot be handed a score that does "
             "not carry its model id, model version and decision-log reference. "
             "The client throws rather than render an unattributable number.",
         size=12, color=INK2, space_after=0, spacing=1.28)

    note(s, M, Inches(4.75), Inches(6.3), Inches(1.85),
         "Verified end to end, not asserted: a headless browser loads the "
         "officer queue, the gateway logs the request, and the refusal renders "
         "with its ticket and owner. A computed instalment of ₹11,248.97 travels "
         "client → HTTP → the pricing engine.",
         kind="good")

    x = Inches(7.35)
    tf = box(s, x, Inches(1.9), Inches(5.3), Inches(0.28))
    para(tf, "VERIFICATION PIPELINE", size=9.5, color=INK3, font=MONO,
         first=True, space_after=0)
    cmds = [("make", "check", "grounding + registry + 2,318 tests"),
            ("make", "gate1…gate6", "six evidence packs, generated never written"),
            ("make", "trackp-p1/p3/p4", "full pipelines on real public data"),
            ("make", "demo5 / demo6", "the assistant controls, and the learning loops"),
            ("npm", "run verify", "typecheck · lint · no-client-math · contracts")]
    for i, (tag, name, sub) in enumerate(cmds):
        row(s, x, Inches(2.35) + Inches(0.86) * i, Inches(5.3), tag, name, sub)


def status(prs):
    s = blank(prs)
    slide_num(s, "14")
    eyebrow(s, "Status, stated plainly")
    heading(s, "Zero of thirty-one exit criteria have gate evidence")

    tf = box(s, M, Inches(1.85), Inches(11.5), Inches(0.4))
    para(tf, "This is the slide most decks leave out. Every phase gate reports "
             "Track B evidence: 0 — because Track B is a bank deployment, and "
             "there is no bank attached. Saying so is the point.",
         size=12, color=INK2, first=True, space_after=0, spacing=1.25)

    tiles = [("0 / 8", "Phase 1 · credit scoring & fraud"),
             ("0 / 6", "Phase 2 · agri intelligence"),
             ("0 / 6", "Phase 3 · portfolio risk"),
             ("0 / 5", "Phase 4 · EWS & recommendations")]
    for i, (val, lab) in enumerate(tiles):
        metric(s, M + Inches(3.03) * i, Inches(2.6), Inches(2.75), val, lab,
               accent=BLOCKED)

    tf = box(s, M, Inches(4.1), Inches(5.9), Inches(0.3))
    para(tf, "THREE GATE STATES, NOT TWO", size=9.5, color=INK3, font=MONO,
         first=True, space_after=0)
    states = [("Not measured", "the job has not run — a scheduling problem"),
              ("Not measurable", "no reachable data produces it — a sourcing problem"),
              ("Unidentifiable", "no quantity of data produces it — a design problem")]
    for i, (name, sub) in enumerate(states):
        yy = Inches(4.6) + Inches(0.78) * i
        tf = box(s, M, yy, Inches(1.9), Inches(0.28))
        para(tf, name, size=12, color=INK, bold=True, first=True, space_after=0)
        tf = box(s, M + Inches(1.95), yy + Inches(0.03), Inches(3.9), Inches(0.4))
        para(tf, sub, size=10.5, color=INK2, first=True, space_after=0,
             spacing=1.15)

    note(s, Inches(7.0), Inches(4.1), Inches(5.6), Inches(2.3),
         "What this buys a bank. The boundary is explicit and reviewable. Every "
         "deterministic computation in the programme is built and tested; every "
         "blocked value has a named owner and a ticket. Nothing has to be "
         "unpicked later because someone guessed — the guesses were never made.",
         kind="good")


def closing(prs):
    s = blank(prs, BRAND_900)
    rect(s, Inches(0), Inches(0), W, H, fill=BRAND_900)
    rect(s, Inches(9.6), Inches(0), Inches(3.8), H, fill=BRAND_700)
    rect(s, Inches(12.2), Inches(0), Inches(1.2), H, fill=BRAND_500)

    tf = box(s, M, Inches(1.4), Inches(8.6), Inches(0.3))
    para(tf, "WHY THIS APPROACH", size=11, color=BRAND_200, font=MONO,
         first=True, space_after=0)

    tf = box(s, M, Inches(1.95), Inches(8.5), Inches(1.9))
    para(tf, "A model that cannot say what\nit does not know is a liability",
         size=34, color=WHITE, bold=True, font=DISPLAY, first=True,
         space_after=0, spacing=1.0)

    tf = box(s, M, Inches(4.1), Inches(8.3), Inches(1.4))
    para(tf, "Lending is a regulated activity. A number on a screen becomes a "
             "number in a complaint, a number in an audit, and a number in front "
             "of a regulator. This build is engineered so every one of those "
             "numbers traces to the script that produced it — or does not appear "
             "at all.",
         size=13, color=BRAND_100, first=True, space_after=0, spacing=1.3)

    rect(s, M, Inches(5.7), Inches(8.3), Emu(9525), fill=BRAND_500)
    facts = [("Refuses, not defaults", "Missing policy raises an error"),
             ("Stamped, not asserted", "Every figure names its track"),
             ("Ported, not invented", "Each algorithm cites its paper"),
             ("Registered, not hidden", "98 tickets, each with an owner")]
    for i, (big, small) in enumerate(facts):
        x = M + Inches(2.12) * i
        tf = box(s, x, Inches(5.95), Inches(2.0), Inches(0.3))
        para(tf, big, size=12, color=WHITE, bold=True, first=True, space_after=0)
        tf = box(s, x, Inches(6.28), Inches(2.0), Inches(0.4))
        para(tf, small, size=9, color=BRAND_200, font=MONO, first=True,
             space_after=0, spacing=1.1)


def main() -> None:
    prs = new_deck()
    cover(prs)
    thesis(prs)
    challenges(prs)
    solution(prs)
    flow(prs)
    scope(prs)
    tracks(prs)
    results(prs)
    ews(prs)
    refusals(prs)
    guarantees(prs)
    findings(prs)
    working(prs)
    status(prs)
    closing(prs)

    core = prs.core_properties
    core.title = "AI-Powered Smart Lending Decision Hub"
    core.subject = "TVS Credit EPIC 8.0 IT Challenge"
    core.comments = ("Figures from committed, rerunnable scripts. Track P "
                     "results are on public reference data and are not gate "
                     "evidence for any bank.")

    out = "/home/divanshu/Desktop/AILendingHub/Lending_Hub_EPIC_8.pptx"
    prs.save(out)
    print(f"wrote {out}")
    print(f"slides: {len(prs.slides.__iter__.__self__._sldIdLst)}")


if __name__ == "__main__":
    main()
