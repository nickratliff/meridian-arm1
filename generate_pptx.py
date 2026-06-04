"""
Meridian — PPTX Generator
Injects property/agent/seller data into the PLACE Selling Experience template.

Strategy:
  - Template shapes are Google Shapes (not native pptx placeholders).
  - We use text find-and-replace tokens AND insert a custom Property Overview slide.
  - Slide 3 (WELCOME) is personalized with the seller's name.
  - A new slide 2 is inserted with agent contact info + property details.

Usage:
  python3 generate_pptx.py <output_path>
  Data is received as JSON via stdin.

Expected JSON fields:
  agentName, agentEmail, agentPhone, agentTitle
  sellerName, address, city, state, zip
  listPrice, bedrooms, bathrooms, totalSqft, yearBuilt, lotSize
  subdivision, county, assessedValue, lastSalePrice, lastSaleDate
  commission (float, e.g. 0.06)
  closingCosts (float, e.g. 0.01)
  netSheet (dict with fields)
"""

import sys
import os
import json
import shutil
import copy
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

# ─── Brand Colors ────────────────────────────────────────────────────────────
MERIDIAN_NAVY = RGBColor(0x0D, 0x1F, 0x3C)
MERIDIAN_GOLD = RGBColor(0xB8, 0x96, 0x2E)
WHITE         = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY    = RGBColor(0xF5, 0xF5, 0xF5)
DARK_GRAY     = RGBColor(0x33, 0x33, 0x33)

TEMPLATE_PATH = Path(__file__).parent / 'template.pptx'


def format_currency(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value) if value else 'N/A'


def format_percent(value) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value) if value else 'N/A'


def replace_text_in_shape(shape, old: str, new: str):
    """Replace text in a shape while preserving formatting where possible."""
    if not shape.has_text_frame:
        return
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            if old in run.text:
                run.text = run.text.replace(old, new)


def replace_tokens_in_slide(slide, tokens: dict):
    """Replace all {{TOKEN}} placeholders in a slide."""
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                for token, value in tokens.items():
                    placeholder = f"{{{{{token}}}}}"
                    if placeholder in run.text:
                        run.text = run.text.replace(placeholder, str(value))


def add_text_box(slide, text, left, top, width, height,
                 font_size=18, bold=False, color=DARK_GRAY,
                 bg_color=None, align=PP_ALIGN.LEFT, italic=False):
    """Add a styled text box to a slide."""
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = txBox.text_frame
    tf.word_wrap = True

    if bg_color:
        fill = txBox.fill
        fill.solid()
        fill.fore_color.rgb = bg_color

    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return txBox


def add_property_overview_slide(prs: Presentation, data: dict):
    """
    Insert a custom Property Overview slide as slide 2.
    Contains: agent info, property address, key stats, preliminary net sheet.
    """
    # Use a blank layout (last layout that has no content placeholders)
    blank_layout = prs.slide_layouts[6]  # BLANK layout
    slide = prs.slides.add_slide(blank_layout)

    slide_w = prs.slide_width.inches
    slide_h = prs.slide_height.inches

    # ── Navy header bar ───────────────────────────────────────────────────────
    from pptx.util import Inches as I, Pt as P
    header = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(0), Inches(0), prs.slide_width, Inches(1.4)
    )
    header.fill.solid()
    header.fill.fore_color.rgb = MERIDIAN_NAVY
    header.line.fill.background()

    # ── MERIDIAN wordmark ─────────────────────────────────────────────────────
    add_text_box(slide, 'MERIDIAN', 0.3, 0.1, 4, 0.6,
                 font_size=28, bold=True, color=MERIDIAN_GOLD, align=PP_ALIGN.LEFT)

    add_text_box(slide, 'Listing Intelligence  |  Nick Ratliff Realty Team', 0.3, 0.72, 6, 0.45,
                 font_size=11, color=WHITE, align=PP_ALIGN.LEFT)

    # ── Property address (large) ──────────────────────────────────────────────
    address_line = f"{data.get('address', '')}, {data.get('city', '')}, {data.get('state','KY')} {data.get('zip','')}"
    add_text_box(slide, address_line, 0.3, 1.55, slide_w - 0.6, 0.55,
                 font_size=20, bold=True, color=MERIDIAN_NAVY, align=PP_ALIGN.LEFT)

    # ── Divider line ──────────────────────────────────────────────────────────
    from pptx.util import Emu
    line = slide.shapes.add_shape(1, Inches(0.3), Inches(2.18), Inches(slide_w - 0.6), Emu(36000))
    line.fill.solid()
    line.fill.fore_color.rgb = MERIDIAN_GOLD
    line.line.fill.background()

    # ── Property Stats row ───────────────────────────────────────────────────
    stats = [
        ('BEDS',        data.get('bedrooms', '—')),
        ('BATHS',       data.get('bathrooms', '—')),
        ('SQ FT',       f"{int(data['totalSqft']):,}" if data.get('totalSqft') else '—'),
        ('YEAR BUILT',  data.get('yearBuilt', '—')),
        ('LOT SIZE',    data.get('lotSize', '—')),
        ('COUNTY',      data.get('county', '—')),
    ]

    col_w = (slide_w - 0.6) / len(stats)
    for i, (label, value) in enumerate(stats):
        x = 0.3 + i * col_w
        # Value
        add_text_box(slide, str(value), x, 2.3, col_w, 0.42,
                     font_size=18, bold=True, color=MERIDIAN_NAVY, align=PP_ALIGN.CENTER)
        # Label
        add_text_box(slide, label, x, 2.72, col_w, 0.28,
                     font_size=8, color=RGBColor(0x88, 0x88, 0x88), align=PP_ALIGN.CENTER)

    # ── Divider ───────────────────────────────────────────────────────────────
    line2 = slide.shapes.add_shape(1, Inches(0.3), Inches(3.05), Inches(slide_w - 0.6), Emu(18000))
    line2.fill.solid()
    line2.fill.fore_color.rgb = RGBColor(0xE0, 0xE0, 0xE0)
    line2.line.fill.background()

    # ── Net Sheet section ─────────────────────────────────────────────────────
    add_text_box(slide, 'PRELIMINARY NET SHEET', 0.3, 3.12, 4, 0.3,
                 font_size=9, bold=True, color=MERIDIAN_GOLD)

    list_price = float(data.get('listPrice', 0) or 0)
    commission_rate = float(data.get('commission', 0.06) or 0.06)
    closing_cost_rate = float(data.get('closingCosts', 0.01) or 0.01)

    commission_amt    = list_price * commission_rate
    closing_costs_amt = list_price * closing_cost_rate
    net_estimate      = list_price - commission_amt - closing_costs_amt

    net_rows = [
        ('List Price',               format_currency(list_price)),
        (f'Commission ({format_percent(commission_rate)})', f'– {format_currency(commission_amt)}'),
        (f'Closing Costs (~{format_percent(closing_cost_rate)})',  f'– {format_currency(closing_costs_amt)}'),
        ('Estimated Net Proceeds',   format_currency(net_estimate)),
    ]

    for i, (label, value) in enumerate(net_rows):
        y = 3.48 + i * 0.36
        is_total = (i == len(net_rows) - 1)
        bg = MERIDIAN_NAVY if is_total else None
        text_color = WHITE if is_total else DARK_GRAY
        weight = True if is_total else False

        row_bg = slide.shapes.add_shape(
            1, Inches(0.3), Inches(y), Inches(4.0), Inches(0.33)
        )
        row_bg.fill.solid()
        row_bg.fill.fore_color.rgb = MERIDIAN_NAVY if is_total else (LIGHT_GRAY if i % 2 == 0 else WHITE)
        row_bg.line.fill.background()

        add_text_box(slide, label, 0.35, y + 0.03, 2.8, 0.28,
                     font_size=9, bold=weight, color=text_color)
        add_text_box(slide, value, 3.0, y + 0.03, 1.25, 0.28,
                     font_size=9, bold=weight, color=text_color, align=PP_ALIGN.RIGHT)

    add_text_box(slide, '* Estimate only. Does not include mortgage payoff, repairs, or seller concessions.',
                 0.3, 5.0, 4.5, 0.3, font_size=7, color=RGBColor(0xAA, 0xAA, 0xAA), italic=True)

    # ── Agent card (right side) ───────────────────────────────────────────────
    agent_card = slide.shapes.add_shape(
        1, Inches(5.2), Inches(3.12), Inches(slide_w - 5.5), Inches(2.3)
    )
    agent_card.fill.solid()
    agent_card.fill.fore_color.rgb = MERIDIAN_NAVY
    agent_card.line.fill.background()

    card_x = 5.35
    add_text_box(slide, 'YOUR AGENT', card_x, 3.18, 3.5, 0.3,
                 font_size=8, bold=True, color=MERIDIAN_GOLD)
    add_text_box(slide, data.get('agentName', 'Nick Ratliff'), card_x, 3.5, 3.5, 0.42,
                 font_size=16, bold=True, color=WHITE)
    add_text_box(slide, data.get('agentTitle', 'Team Lead | REAL Broker'), card_x, 3.93, 3.5, 0.3,
                 font_size=9, color=LIGHT_GRAY)
    add_text_box(slide, data.get('agentPhone', ''), card_x, 4.28, 3.5, 0.28,
                 font_size=10, color=WHITE)
    add_text_box(slide, data.get('agentEmail', 'nick@nrrt.com'), card_x, 4.56, 3.5, 0.28,
                 font_size=10, color=MERIDIAN_GOLD)
    add_text_box(slide, 'meridian.nrrt.com', card_x, 4.85, 3.5, 0.28,
                 font_size=9, color=LIGHT_GRAY, italic=True)

    # ── Move this new slide to position index 1 (after the title slide) ──────
    xml_slides = prs.slides._sldIdLst
    last_entry = xml_slides[-1]
    xml_slides.remove(last_entry)
    xml_slides.insert(1, last_entry)

    return slide


def personalize_welcome_slide(prs: Presentation, seller_name: str):
    """
    Slide index 2 (0-based) is the WELCOME slide after our insertion.
    Find the body text shape and prepend seller's name.
    """
    # After insertion, original slide 3 (WELCOME) is now at index 3
    try:
        welcome_slide = prs.slides[3]
        for shape in welcome_slide.shapes:
            if shape.has_text_frame and 'entrusting' in shape.text_frame.text:
                tf = shape.text_frame
                # Prepend seller name to first paragraph
                first_para = tf.paragraphs[0]
                if first_para.runs:
                    original = first_para.runs[0].text
                    first_para.runs[0].text = f"Dear {seller_name},\n\n{original}"
                break
    except (IndexError, AttributeError):
        pass  # Non-fatal — welcome slide personalization is optional


def generate(data: dict, output_path: str):
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Template not found at {TEMPLATE_PATH}. "
            "Copy 'Copy of PLACE Selling Experience (correct).pptx' to 'template.pptx' in the same folder."
        )

    # Work on a copy
    shutil.copy2(TEMPLATE_PATH, output_path)
    prs = Presentation(output_path)

    # 1. Insert property overview slide as slide 2
    add_property_overview_slide(prs, data)

    # 2. Personalize the welcome slide
    seller_name = data.get('sellerName', 'Valued Client')
    personalize_welcome_slide(prs, seller_name)

    # 3. Save
    prs.save(output_path)
    print(f"Saved: {output_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_pptx.py <output_path>", file=sys.stderr)
        sys.exit(1)

    output_path = sys.argv[1]

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    generate(data, output_path)


if __name__ == '__main__':
    main()
