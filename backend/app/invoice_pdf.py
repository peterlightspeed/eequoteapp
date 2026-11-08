"""EE Solutions QUOTE PDF – reproduces EE's real quote template (landscape):
logo + RC + office / training-centre addresses, client & prepared-by grid, '<PRODUCT> QUOTE' bar,
bill-of-materials table, TOTAL / VAT / TOTAL BUY PRICE, amount in words, terms, logo bottom right.
Numbers are printed without currency symbols; the currency is named in the column headings."""
import io, os
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Image

from .currency import amount_in_words, heading_name

HERE = os.path.dirname(__file__)
ASSETS = os.path.abspath(os.path.join(HERE, "..", "..", "assets"))
LOGO = os.path.join(ASSETS, "logo.png")

NAVY, NAVY2 = colors.HexColor("#002060"), colors.HexColor("#1F3864")
FILL, BLUE = colors.HexColor("#D6DCE4"), colors.HexColor("#0563C1")

try:   # Carlito = Calibri look-alike (the template is Calibri); fall back to Helvetica if missing
    pdfmetrics.registerFont(TTFont("EE", os.path.join(ASSETS, "fonts", "Carlito-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("EE-B", os.path.join(ASSETS, "fonts", "Carlito-Bold.ttf")))
    F, FB = "EE", "EE-B"
except Exception:
    F, FB = "Helvetica", "Helvetica-Bold"

DEFAULT_OFFICE = "4, (Plot 1063), Abagbon Close,|Off Ologun Agbaje Street,|Off Adeola Odeku Street,|Victoria Island|Lagos – Nigeria"
DEFAULT_TRAINING = "2nd Floor,|60, Akerele Street,|Surulere|Lagos Mainland|Lagos - Nigeria"
DEFAULT_TAGLINE = "Cybersecurity || Enterprise Infrastructure || AI|Prof. Services || App Dev. || VAPT || I.T Training"   # | = line break
DEFAULT_ADDRESS = "4,(Plot 1063), Abagbon Close, off Ologun Agbaje Street,|Victoria Island, Lagos Nigeria"


def tagline_html() -> str:
    """Tagline with '|' as a line break ('||' stays as the visible separator)."""
    raw = env("COMPANY_TAGLINE", DEFAULT_TAGLINE).replace("||", "\u0001")
    return "<br/>".join(escape(part) for part in raw.split("|")).replace("\u0001", "||")


def env(k, default=""):
    return os.getenv(k, default)


def num(x) -> str:
    return f"{Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def unit_num(x, code, qty, total) -> str:
    """NGN: kobo precision. Other currencies: 2 decimals when qty x unit still equals the printed total, else up to 4."""
    x = Decimal(str(x))
    if code == "NGN":
        return num(x)
    two = x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if (two * Decimal(str(qty))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal(str(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
        return f"{two:,.2f}"
    s = f"{x.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):,.4f}".rstrip("0")
    return s


def build_invoice(q: dict, r, currency="NGN") -> bytes:
    """q: reference, date_display, product_title, company_name, client_name, position, address1, address2,
    city_country, prepared_by, prepared_role, prepared_email, prepared_phone, authorized_by, terms(list), vat_rate"""
    page = landscape(LETTER if env("QUOTE_PAGE", "A4").upper() == "LETTER" else A4)
    M = 22
    W = page[0] - 2 * M
    ps = lambda size=8.5, **k: ParagraphStyle("x", **{"fontName": F, "fontSize": size, "leading": size * 1.22, **k})
    P = lambda t, st=None: Paragraph(escape(str(t or "")).replace("\n", "<br/>"), st or ps())
    PB = lambda t, size=8.5, **k: Paragraph(escape(str(t or "")), ps(size, fontName=FB, **k))

    def logo(width):
        w, h = PILImage.open(LOGO).size
        return Image(LOGO, width=width, height=width * h / w)

    story = []

    # ---- header: logo + tagline | RC + office | training centre ----
    tag = Paragraph(tagline_html(), ps(9, fontName=FB, textColor=colors.HexColor("#1F3864"), leading=11.2))
    left = [logo(170), Spacer(1, 3), tag]
    addr = lambda t: P(t.replace("|", "\n"), ps(8.8, leading=11.2))
    mid = [PB(f"RC: {env('COMPANY_RC', '1848259')}", 11.5, alignment=TA_RIGHT), Spacer(1, 4),
           PB("Office Address:", 9), addr(env("OFFICE_ADDRESS", DEFAULT_OFFICE))]
    right = [Spacer(1, 17), PB("Training Centre Address:", 9), addr(env("TRAINING_ADDRESS", DEFAULT_TRAINING))]
    head = Table([[left, mid, right]], colWidths=[W * .45, W * .27, W * .28])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story.append(head)

    # ---- client / prepared-by grid ----
    co_addr = env("COMPANY_ADDRESS", DEFAULT_ADDRESS).split("|")
    right_txt = [f"Quote by: {env('COMPANY_NAME', 'EE Solutions Limited')}", f"Prepared by: {q.get('prepared_by', '')}",
                 q.get("prepared_role", ""), f"Contact: {q.get('prepared_email', '')}", q.get("prepared_phone", ""),
                 f"Authorized by: {q.get('authorized_by', '')}", co_addr[0] if co_addr else "",
                 co_addr[1] if len(co_addr) > 1 else ""]
    left_rows = [("Date:", q.get("date_display", "")), ("Company Name", q.get("company_name", "")),
                 ("Client's name:", q.get("client_name", "")), ("Position/Role", q.get("position", "")),
                 ("Address Line 1:", q.get("address1", "")), ("Address Line 2:", q.get("address2", "")),
                 ("City and Country", q.get("city_country", "")), ("Reference", q.get("reference", ""))]
    cell = ps(8.4, fontName=FB, leading=10)
    grid = Table([[Paragraph(escape(a), cell), Paragraph(escape(b), cell), Paragraph(escape(c), cell)]
                  for (a, b), c in zip(left_rows, right_txt)], colWidths=[W * .20, W * .38, W * .42])
    grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FILL), ("GRID", (0, 0), (-1, -1), .5, colors.black),
                              ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
                              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [grid, Spacer(1, 9)]

    # ---- title bar ----
    title = (q.get("product_title") or "SOFTWARE").strip().upper() + " QUOTE"
    bar = Table([[PB(title, 11.5, textColor=colors.white, alignment=TA_CENTER)]], colWidths=[W])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 4),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(bar)

    # ---- bill of materials ----
    cname = heading_name(currency)
    hdr = ps(8.2, textColor=colors.white, alignment=TA_CENTER)
    rows = [[Paragraph(t, hdr) for t in ("SOFTWARE KIT UNIT", "DESCRIPTION OF BILL OF MATERIALS", "DURATION", "QTY",
                                         f"UNIT PRICE ({cname})", f"TOTAL COST ({cname})")]]
    body, ctr, rt = ps(8.6), ps(8.6, alignment=TA_CENTER), ps(8.6, alignment=TA_RIGHT)
    for l in r.lines:
        rows.append([P(l.sku, body), P(l.description, body), P(l.duration, ctr), P(f"{l.qty.normalize():f}", ctr),
                     P(unit_num(l.sell_unit_out, currency, l.qty, l.sell_total_out), rt), P(num(l.sell_total_out), rt)])
    n = len(rows)
    vr = Decimal(str(q.get("vat_rate", 0.075))) * 100
    wh = ps(9, fontName=FB, textColor=colors.white, alignment=TA_CENTER)
    whr = ps(8.8, fontName=FB, textColor=colors.white, alignment=TA_RIGHT)
    rows.append(["", Paragraph("TOTAL", wh), "", "", "", Paragraph(num(r.subtotal_out), whr)])
    rows.append(["", "", "", "", P(f"VAT ({vr.normalize():f}%)", ctr), P(num(r.vat_out), rt)])
    rows.append(["", Paragraph("TOTAL BUY PRICE", ps(12.5, fontName=FB, textColor=colors.white, alignment=TA_CENTER)),
                 "", "", "", Paragraph(num(r.total_out), whr)])
    cw = [W * .195, W * .485, W * .068, W * .036, W * .105, W * .111]
    t = Table(rows, colWidths=cw, repeatRows=1)
    st = [("BACKGROUND", (0, 0), (-1, 0), NAVY2), ("BOX", (0, 0), (-1, -1), .8, colors.black),
          ("INNERGRID", (0, 0), (-1, n - 1), .5, colors.black), ("VALIGN", (0, 0), (-1, n - 1), "BOTTOM"),
          ("VALIGN", (0, n), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, 0), 3), ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
          ("TOPPADDING", (0, 1), (-1, n - 1), 14), ("BOTTOMPADDING", (0, 1), (-1, n - 1), 3),
          ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    st += [("BACKGROUND", (0, i), (-1, i), FILL) for i in range(1, n)]
    st += [("BACKGROUND", (0, n), (-1, n), NAVY2), ("SPAN", (1, n), (4, n)),
           ("TOPPADDING", (0, n), (-1, n), 2), ("BOTTOMPADDING", (0, n), (-1, n), 2),
           ("BACKGROUND", (0, n + 1), (-1, n + 1), colors.white), ("SPAN", (0, n + 1), (3, n + 1)),
           ("BOX", (4, n + 1), (5, n + 1), .5, colors.black), ("LINEBEFORE", (5, n + 1), (5, n + 1), .5, colors.black),
           ("TOPPADDING", (0, n + 1), (-1, n + 1), 2), ("BOTTOMPADDING", (0, n + 1), (-1, n + 1), 2),
           ("BACKGROUND", (0, n + 2), (-1, n + 2), NAVY), ("SPAN", (1, n + 2), (4, n + 2)),
           ("TOPPADDING", (0, n + 2), (-1, n + 2), 7), ("BOTTOMPADDING", (0, n + 2), (-1, n + 2), 7)]
    t.setStyle(TableStyle(st))
    story += [t, Spacer(1, 18)]

    # ---- amount in words, prepared by, terms, logo ----
    lab = ps(8.8, fontName=FB)
    info = Table([[Paragraph("Amount in words:", lab), P(amount_in_words(r.total_out, currency), ps(8.8))],
                  [Paragraph("Quote prepared by:", lab), P(q.get("prepared_by", ""), ps(8.8))],
                  [Paragraph("Contact:", lab), Paragraph(escape(q.get("prepared_email", "")), ps(8.2, textColor=BLUE))]],
                 colWidths=[W * .17, W * .5])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                              ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    terms = [t.strip() for t in q.get("terms", []) if t and t.strip()]
    tparas = []
    for i, tx in enumerate(terms, 1):
        tx = tx if tx[:2].rstrip(".").isdigit() else f"{i}. {tx}"
        tparas.append(P(tx, ps(7.6, leading=9.2)))
    leftcol = [info, Spacer(1, 12), PB("TERMS:", 8.8), Spacer(1, 6)] + tparas
    foot = Table([[leftcol, logo(120)]], colWidths=[W * .78, W * .22])
    foot.setStyle(TableStyle([("VALIGN", (0, 0), (0, 0), "TOP"), ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(KeepTogether([foot]))

    def frame(c, d):
        c.saveState(); c.setLineWidth(1); c.setStrokeColor(colors.black)
        c.rect(M - 1, M - 1, W + 2, page[1] - 2 * M + 2); c.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M,
                            title=f"Quote {q.get('reference', '')}", author=env("COMPANY_NAME", "EE Solutions Limited"))
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
