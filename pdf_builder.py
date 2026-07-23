from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Mapping, Any

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "form_templates"
LOGO_PATH = BASE_DIR / "public" / "img" / "spnhs_logo.png"

PAGE_W, PAGE_H = letter  # 612 x 792 points
PX_TO_PT = 612.0 / 1275.0  # Uploaded PDFs were rendered at 150 dpi: 1275 x 1650 px.


def _x(px: float) -> float:
    return px * PX_TO_PT


def _y(py: float) -> float:
    return PAGE_H - py * PX_TO_PT


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _format_form6_header_value(key: str, value: Any) -> str:
    """Format Form 6 header values to match the official sample."""
    text = _clean(value)
    if not text:
        return ""

    if key == "date_filing":
        # Accept YYYY-MM-DD or MM/DD/YYYY and print MM/DD/YY.
        from datetime import datetime
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(text, fmt).strftime("%m/%d/%y")
            except ValueError:
                pass

    if key == "salary":
        # Print salary like 36,283.00 while tolerating commas/currency symbols.
        cleaned = text.replace(",", "").replace("₱", "").replace("PHP", "").strip()
        try:
            return f"{float(cleaned):,.2f}"
        except ValueError:
            pass

    return text.upper()


def _draw_text_fit(c: canvas.Canvas, value: Any, x: float, y: float, max_width: float,
                   size: float = 8.5, min_size: float = 5.5, font: str = "Helvetica") -> None:
    text = _clean(value)
    if not text:
        return
    current = size
    while current > min_size and c.stringWidth(text, font, current) > max_width:
        current -= 0.25
    if c.stringWidth(text, font, current) <= max_width:
        c.setFont(font, current)
        c.drawString(x, y, text)
        return

    # Last-resort truncation avoids printing over the next field.
    suffix = "..."
    while text and c.stringWidth(text + suffix, font, current) > max_width:
        text = text[:-1]
    c.setFont(font, current)
    c.drawString(x, y, text + suffix)



def _draw_centered_bold_fit(
    c: canvas.Canvas,
    value: Any,
    center_x: float,
    baseline_y: float,
    max_width: float,
    max_size: float = 10.5,
    min_size: float = 7.0,
) -> None:
    """Draw a bold uppercase value centered in its Form 6 field.

    The value keeps the requested font size whenever it fits. Longer names
    and positions are reduced gradually, but never spill into the next field.
    """
    text = _clean(value).upper()
    if not text:
        return

    font = "Helvetica-Bold"
    size = max_size
    while size > min_size and c.stringWidth(text, font, size) > max_width:
        size -= 0.25

    # Keep a small margin at both ends of the field. If an exceptionally
    # long value still does not fit at the minimum font size, compress only
    # its width so it remains centered and never overlaps another field.
    usable_width = max_width * 0.94
    natural_width = c.stringWidth(text, font, size)
    hscale = 100.0
    if natural_width > usable_width and natural_width > 0:
        hscale = (usable_width / natural_width) * 100.0

    effective_width = natural_width * hscale / 100.0
    draw_x = center_x - (effective_width / 2.0)

    text_object = c.beginText()
    text_object.setTextOrigin(draw_x, baseline_y)
    text_object.setFont(font, size)
    text_object.setHorizScale(hscale)
    text_object.textOut(text)
    c.drawText(text_object)


def _draw_multiline_fit(c: canvas.Canvas, value: Any, x: float, y: float, max_width: float,
                        max_lines: int = 2, size: float = 7.5, leading: float = 8.5) -> None:
    text = _clean(value)
    if not text:
        return
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if c.stringWidth(trial, "Helvetica", size) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    consumed = " ".join(lines)
    if len(consumed) < len(text) and lines:
        while lines[-1] and c.stringWidth(lines[-1] + "...", "Helvetica", size) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "..."
    c.setFont("Helvetica", size)
    for index, line in enumerate(lines[:max_lines]):
        c.drawString(x, y - index * leading, line)


def _draw_x(c: canvas.Canvas, px: float, py: float, size: float = 9.0) -> None:
    """Draw a centered X inside the target checkbox area.

    The coordinate values are measured from the 1275 x 1650 reference render.
    A small horizontal inset keeps the glyph visually centered instead of
    touching the checkbox's left border.
    """
    c.setFont("Helvetica-Bold", size)
    c.drawString(_x(px + 4), _y(py) - 3.2, "X")


def _draw_logo(c: canvas.Canvas, family: str) -> None:
    if not LOGO_PATH.exists():
        return
    try:
        with Image.open(LOGO_PATH) as im:
            width, height = im.size
        ratio = width / height if height else 1
        box_w = 78 if family == "regular" else 72
        box_h = 50 if family == "regular" else 45
        draw_w = min(box_w, box_h * ratio)
        draw_h = draw_w / ratio
        if family == "regular":
            x0, y0 = _x(897), _y(132)
        else:
            x0, y0 = _x(730), _y(128)
        c.drawImage(
            ImageReader(str(LOGO_PATH)),
            x0 + (box_w - draw_w) / 2,
            y0 + (box_h - draw_h) / 2,
            draw_w,
            draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        # A missing logo should never prevent the request form from being generated.
        return


REGULAR = {
    "name_last": (470, 270, 190),
    "name_first": (690, 270, 190),
    "name_middle": (895, 270, 180),
    "date_filing": (267, 313, 110),
    "position": (544, 313, 229),
    "salary": (878, 313, 118),
    "leave_boxes_y": [412, 439, 466, 493, 520, 547, 574, 601, 628, 655, 682, 709, 736, 763],
    "leave_box_x": 134,
    "others": (132, 813, 230),
    "within": (735, 447, 170),
    "abroad": (735, 474, 170),
    "hospital": (713, 579, 335),
    "outpatient": (713, 579, 335),
    "women": (713, 657, 335),
    "study_x": 690,
    "study_ys": [703, 730],
    "other_x": 690,
    "other_ys": [778, 805],
    "working_days": (145, 871, 235),
    "inclusive_dates": (145, 923, 235),
    "comm_x": 690,
    "comm_ys": [870, 898],
    "credits_asof": (205, 1036, 165),
    "credit_vac_x": 315,
    "credit_sick_x": 455,
    "credit_ys": [1082, 1105, 1128],
    "recommend_x": 690,
    "recommend_ys": [1035, 1063],
    "recommend_reason": (713, 1084, 340),
    "approved_x": 170,
    "approved_ys": [1245, 1264, 1283],
    "disapproved": (713, 1248, 390),
    "approval_date": None,
}

VARIANT = {
    "name_last": (540, 285, 145),
    "name_first": (750, 285, 115),
    "name_middle": (900, 285, 100),
    "date_filing": (320, 333, 80),
    "position": (590, 333, 120),
    "salary": (930, 333, 75),
    "leave_boxes_y": [433, 459, 485, 512, 538, 565, 591, 618, 644, 671, 697, 724, 750],
    "leave_box_x": 177,
    "others": (169, 811, 225),
    "within": (731, 460, 176),
    "abroad": (731, 486, 176),
    "hospital": (713, 590, 320),
    "outpatient": (713, 590, 320),
    "women": (713, 669, 320),
    "study_x": 694,
    "study_ys": [723, 750],
    "other_x": 694,
    "other_ys": [804, 830],
    "working_days": (188, 891, 235),
    "inclusive_dates": (188, 944, 235),
    "comm_x": 694,
    "comm_ys": [888, 916],
    "credits_asof": (248, 1061, 165),
    "credit_vac_x": 358,
    "credit_sick_x": 498,
    "credit_ys": [1120, 1142, 1164],
    "recommend_x": 694,
    "recommend_ys": [1058, 1085],
    "recommend_reason": (718, 1109, 340),
    "approved_x": 212,
    "approved_ys": [1297, 1316, 1335],
    "disapproved": (713, 1302, 335),
    "approval_date": (215, 1389, 120),
}


# Header values are positioned by the visual center of each blank field.
# Coordinates were measured from the 1275 x 1650 reference render.
HEADER_REGULAR = {
    "name_last": (579, 274, 158),
    "name_first": (739, 274, 145),
    "name_middle": (880, 274, 145),
    "date_filing": (322, 316, 108),
    "position": (658, 316, 225),
    "salary": (937, 316, 116),
}

# Monetization and terminal-leave templates.
HEADER_COMPACT = {
    "name_last": (578, 289, 140),
    "name_first": (750, 289, 135),
    "name_middle": (900, 289, 125),
    "date_filing": (369, 336, 106),
    "position": (705, 336, 220),
    "salary": (980, 336, 100),
}

# More-than-60-days template.
HEADER_MORE60 = {
    "name_last": (566, 274, 158),
    "name_first": (726, 274, 145),
    "name_middle": (867, 274, 145),
    "date_filing": (309, 316, 108),
    "position": (645, 316, 225),
    "salary": (924, 316, 116),
}


LEAVE_INDEX = {
    "Vacation Leave": 0,
    "Mandatory/Forced Leave": 1,
    "Sick Leave": 2,
    "Maternity Leave": 3,
    "Paternity Leave": 4,
    "Special Privilege Leave": 5,
    "Solo Parent Leave": 6,
    "Study Leave": 7,
    "10-Day VAWC Leave": 8,
    "Rehabilitation Privilege": 9,
    "Special Leave Benefits for Women": 10,
    "Special Emergency (Calamity) Leave": 11,
    "Adoption Leave": 12,
    "Wellness Leave": 13,
}


def _template_for(data: Mapping[str, Any]) -> tuple[Path, str]:
    variant = _clean(data.get("form_variant")).lower()
    if variant == "monetization":
        return TEMPLATE_DIR / "form6_monetization.pdf", "variant"
    if variant == "terminal":
        return TEMPLATE_DIR / "form6_terminal.pdf", "variant"
    if variant == "more_than_60_days":
        return TEMPLATE_DIR / "form6_more_than_60_days.pdf", "more60"
    return TEMPLATE_DIR / "form6_front.pdf", "regular"


def build_form6_pdf(data: Mapping[str, Any], include_back: bool = True) -> bytes:
    template_path, family = _template_for(data)
    # Preserve the established body coordinates while using dedicated header
    # coordinates for each uploaded Form 6 layout.
    coords = REGULAR if family == "regular" else VARIANT
    if family == "regular":
        header_coords = HEADER_REGULAR
    elif family == "more60":
        header_coords = HEADER_MORE60
    else:
        header_coords = HEADER_COMPACT

    overlay_stream = BytesIO()
    c = canvas.Canvas(overlay_stream, pagesize=letter)
    c.setFillColorRGB(0, 0, 0)
    _draw_logo(c, family)
    if family == "variant":
        _draw_text_fit(c, "SPNHS - SHS", _x(180), _y(285), _x(220), size=8.0, font="Helvetica-Bold")
    elif family == "more60":
        _draw_text_fit(c, "SPNHS - SHS", _x(120), _y(270), _x(220), size=8.0, font="Helvetica-Bold")

    def field(key: str, value: Any, size: float = 8.3, font: str = "Helvetica") -> None:
        px, py, width_px = coords[key]
        _draw_text_fit(c, value, _x(px), _y(py), _x(width_px), size=size, font=font)

    # Form 6 header values are bold, uppercase and horizontally centered in
    # the exact blank/underline allotted to each field.  The second row uses
    # a larger preferred font so the date, position and salary are as visible
    # as the names. Long entries are reduced only as much as necessary.
    header_values = (
        ("name_last", data.get("surname"), 13.0, 10.0),
        ("name_first", data.get("first_name"), 13.0, 10.0),
        ("name_middle", data.get("middle_name"), 13.0, 10.0),
        ("date_filing", data.get("date_filing"), 13.0, 9.0),
        ("position", data.get("position"), 13.0, 11.5),
        ("salary", data.get("salary"), 13.0, 9.0),
    )
    for key, value, preferred_size, minimum_size in header_values:
        center_px, baseline_py, width_px = header_coords[key]
        formatted_value = _format_form6_header_value(key, value)
        _draw_centered_bold_fit(
            c,
            formatted_value,
            center_x=_x(center_px),
            baseline_y=_y(baseline_py),
            max_width=_x(width_px),
            max_size=preferred_size,
            min_size=minimum_size,
        )

    leave_type = _clean(data.get("leave_type"))
    index = LEAVE_INDEX.get(leave_type)
    if index is not None and index < len(coords["leave_boxes_y"]):
        _draw_x(c, coords["leave_box_x"], coords["leave_boxes_y"][index])
    if leave_type == "Others":
        field("others", data.get("other_leave_type"), size=7.5)

    detail_mode = _clean(data.get("leave_detail_mode"))
    if detail_mode == "Within the Philippines":
        _draw_x(c, 690 if family == "regular" else 694, 444 if family == "regular" else 458, size=8)
        field("within", data.get("leave_detail_text"), size=7.2)
    elif detail_mode == "Abroad":
        _draw_x(c, 690 if family == "regular" else 694, 471 if family == "regular" else 484, size=8)
        field("abroad", data.get("leave_detail_text"), size=7.2)
    elif detail_mode == "In Hospital":
        _draw_x(c, 690 if family == "regular" else 694, 523 if family == "regular" else 536, size=8)
        field("hospital", data.get("leave_detail_text"), size=6.8)
    elif detail_mode == "Out Patient":
        _draw_x(c, 690 if family == "regular" else 694, 550 if family == "regular" else 563, size=8)
        field("outpatient", data.get("leave_detail_text"), size=6.8)
    elif detail_mode == "Special Leave Benefits for Women":
        field("women", data.get("leave_detail_text"), size=6.8)

    study_purpose = _clean(data.get("study_purpose"))
    if study_purpose == "Completion of Master's Degree":
        _draw_x(c, coords["study_x"], coords["study_ys"][0], size=8)
    elif study_purpose == "BAR/Board Examination Review":
        _draw_x(c, coords["study_x"], coords["study_ys"][1], size=8)

    other_purpose = _clean(data.get("other_purpose"))
    # Variant templates already contain a filled box for their purpose.
    if family == "regular":
        if other_purpose == "Monetization of Leave Credits":
            _draw_x(c, coords["other_x"], coords["other_ys"][0], size=8)
        elif other_purpose == "Terminal Leave":
            _draw_x(c, coords["other_x"], coords["other_ys"][1], size=8)

    field("working_days", data.get("working_days"), size=8.0)
    field("inclusive_dates", data.get("inclusive_dates"), size=7.5)

    commutation = _clean(data.get("commutation"))
    if commutation == "Requested":
        _draw_x(c, coords["comm_x"], coords["comm_ys"][1], size=8)
    else:
        _draw_x(c, coords["comm_x"], coords["comm_ys"][0], size=8)

    # Section 7 - completed by the records/approving office.
    if _clean(data.get("credits_as_of")):
        field("credits_asof", data.get("credits_as_of"), size=7.0)
    for key, x_px, y_px in (
        ("vacation_total", coords["credit_vac_x"], coords["credit_ys"][0]),
        ("sick_total", coords["credit_sick_x"], coords["credit_ys"][0]),
        ("vacation_less", coords["credit_vac_x"], coords["credit_ys"][1]),
        ("sick_less", coords["credit_sick_x"], coords["credit_ys"][1]),
        ("vacation_balance", coords["credit_vac_x"], coords["credit_ys"][2]),
        ("sick_balance", coords["credit_sick_x"], coords["credit_ys"][2]),
    ):
        _draw_text_fit(c, data.get(key), _x(x_px), _y(y_px), _x(75), size=7.0)

    recommendation = _clean(data.get("recommendation"))
    if recommendation == "For approval":
        _draw_x(c, coords["recommend_x"], coords["recommend_ys"][0], size=8)
    elif recommendation == "For disapproval":
        _draw_x(c, coords["recommend_x"], coords["recommend_ys"][1], size=8)
        px, py, width_px = coords["recommend_reason"]
        _draw_multiline_fit(
            c, data.get("recommendation_reason"), _x(px), _y(py), _x(width_px),
            max_lines=3, size=6.8, leading=8.8
        )

    for key, py in zip(
        ["approved_with_pay", "approved_without_pay", "approved_others"],
        coords["approved_ys"],
    ):
        _draw_text_fit(c, data.get(key), _x(coords["approved_x"]), _y(py), _x(48), size=7.5)

    if _clean(data.get("disapproved_reason")):
        px, py, width_px = coords["disapproved"]
        _draw_multiline_fit(c, data.get("disapproved_reason"), _x(px), _y(py), _x(width_px), max_lines=3, size=7.0)

    if coords["approval_date"] and _clean(data.get("approval_date")):
        px, py, width_px = coords["approval_date"]
        _draw_text_fit(c, data.get("approval_date"), _x(px), _y(py), _x(width_px), size=7.0)

    c.save()
    overlay_stream.seek(0)

    template_reader = PdfReader(str(template_path))
    overlay_reader = PdfReader(overlay_stream)
    first_page = template_reader.pages[0]
    first_page.merge_page(overlay_reader.pages[0])

    writer = PdfWriter()
    writer.add_page(first_page)
    if include_back:
        back_reader = PdfReader(str(TEMPLATE_DIR / "form6_back.pdf"))
        writer.add_page(back_reader.pages[0])

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def build_simple_request_pdf(data: Mapping[str, Any], settings: Mapping[str, Any]) -> bytes:
    request_type = _clean(data.get("request_type"))
    title = "CERTIFICATE OF EMPLOYMENT REQUEST" if request_type == "COE" else "SERVICE RECORD REQUEST"
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=letter)

    navy = (6 / 255, 61 / 255, 113 / 255)
    sky = (163 / 255, 203 / 255, 239 / 255)
    green = (0 / 255, 110 / 255, 0 / 255)

    c.setFillColorRGB(*navy)
    c.rect(0, 730, PAGE_W, 62, fill=1, stroke=0)
    c.setFillColorRGB(*sky)
    c.rect(0, 720, PAGE_W, 10, fill=1, stroke=0)

    if LOGO_PATH.exists():
        c.drawImage(ImageReader(str(LOGO_PATH)), 44, 680, 78, 78, preserveAspectRatio=True, mask="auto")

    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(142, 764, "SANGLEY POINT NATIONAL HIGH SCHOOL")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(142, 746, "SENIOR HIGH SCHOOL")

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    c.drawString(142, 704, _clean(settings.get("division")) or "Schools Division Office of Cavite City")
    c.drawString(142, 690, _clean(settings.get("address")) or "Sangley Point, Cavite City")

    c.setFillColorRGB(*navy)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(PAGE_W / 2, 634, title)
    c.setStrokeColorRGB(*green)
    c.setLineWidth(2)
    c.line(70, 620, PAGE_W - 70, 620)

    labels = [
        ("Surname", data.get("surname")),
        ("First Name", data.get("first_name")),
        ("Middle Initial", data.get("middle_initial")),
        ("Date of First Day of Service", data.get("first_day_service")),
        ("Contact Number", data.get("contact_no")),
        ("Tracking Number", data.get("tracking_no")),
        ("Date Requested", data.get("submitted_date")),
    ]
    y = 560
    for label, value in labels:
        c.setFillColorRGB(*navy)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(85, y, label.upper())
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", 11)
        c.drawString(260, y, _clean(value))
        c.setStrokeColorRGB(0.55, 0.62, 0.68)
        c.setLineWidth(0.6)
        c.line(255, y - 4, 520, y - 4)
        y -= 54

    c.setFillColorRGB(0.96, 0.98, 1)
    c.roundRect(70, 160, PAGE_W - 140, 95, 8, fill=1, stroke=0)
    c.setFillColorRGB(*navy)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(88, 230, "RECORDS OFFICE USE")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(88, 208, "Status: ______________________________")
    c.drawString(88, 187, "Remarks: ______________________________________________________________")

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.30, 0.35, 0.40)
    c.drawCentredString(PAGE_W / 2, 92, "This form records a request only. Release remains subject to verification by the Records Office.")
    c.drawCentredString(PAGE_W / 2, 76, "Keep the tracking number for status checking and document claiming.")

    c.showPage()
    c.save()
    return output.getvalue()
