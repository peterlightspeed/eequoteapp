"""Distributor invoice PDF -> text + candidate line items.  Works for any distributor whose
PDF has a text layer. Three strategies, tried in order:
  1. table extraction (ruled tables)             – e.g. the sample invoices
  2. column positions taken from the header row  – tables drawn without lines
  3. one-line regex  SKU  description  qty  unit  total
Staff always review the result in the UI. Scanned PDFs have no text and need OCR (see GUIDE)."""
import io, re
import pdfplumber

NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
SYN = {
    "sku": ("sku", "part", "item", "code", "product", "mfr"),
    "desc": ("desc", "detail", "particular", "service"),
    "qty": ("qty", "quantity", "units", "seats", "users"),
    "unit": ("unit", "rate", "list", "price"),
    "total": ("total", "amount", "extended", "ext"),
}


def to_num(s):
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(s)))
    except ValueError:
        return None


def clean_sku(s):
    return re.sub(r"\s+", "", s or "")          # wrapped SKUs like "ADOBE-ACR-PR\nO" -> "ADOBE-ACR-PRO"


def clean_desc(s):
    return " ".join((s or "").split())


def extract_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _pick(head, key, skip=()):
    for i, h in enumerate(head):
        if i not in skip and any(n in h for n in SYN[key]):
            return i


def _from_tables(pdf):
    items = []
    for page in pdf.pages:
        for table in page.extract_tables():
            if not table or len(table) < 2:
                continue
            head = [" ".join((c or "").lower().split()) for c in table[0]]
            c_desc = _pick(head, "desc"); c_qty = _pick(head, "qty")
            c_sku = _pick(head, "sku", skip=(c_desc,) if c_desc is not None else ())
            c_unit = _pick(head, "unit", skip=tuple(x for x in (c_sku, c_desc, c_qty) if x is not None))
            if None in (c_desc, c_qty, c_unit):
                continue
            for row in table[1:]:
                qty, unit = to_num(row[c_qty]), to_num(row[c_unit])
                if qty and unit is not None:
                    items.append({"sku": clean_sku(row[c_sku]) if c_sku is not None else "",
                                  "description": clean_desc(row[c_desc]), "qty": qty, "list_unit": unit})
    return items


def _from_positions(pdf):
    items = []
    for page in pdf.pages:
        words = page.extract_words()
        heads = [w for w in words if w["text"].lower().strip(":") in
                 {x for k in ("sku", "qty", "unit") for x in SYN[k] if k != "unit"} | {"description", "unit", "price", "rate", "total", "amount"}]
        anchor = next((w for w in words if w["text"].lower() in ("sku", "part", "item", "code")), None)
        if not anchor:
            continue
        band = [w for w in words if abs(w["top"] - anchor["top"]) < 16 and w["top"] >= anchor["top"] - 16]
        def x_of(keys):
            c = [w["x0"] for w in band if w["text"].lower().strip(":") in keys]
            return min(c) if c else None
        xs = [("sku", anchor["x0"]), ("desc", x_of({"description", "details", "desc", "particulars"})),
              ("qty", x_of({"qty", "quantity", "seats", "units"})),
              ("unit", x_of({"unit", "rate", "price"})), ("total", x_of({"total", "amount"}))]
        if any(x is None for _, x in xs):
            continue
        # "total" may sit left of "unit" in some layouts -> order columns by x
        xs.sort(key=lambda t: t[1])
        bounds = [(k, x - 8) for k, x in xs]
        def col(w):
            c = (w["x0"] + w["x1"]) / 2
            name = bounds[0][0]
            for k, b in bounds:
                if c >= b: name = k
            return name
        head_bottom = max(w["bottom"] for w in band) + 2
        stop = [w["top"] for w in words if w["top"] > head_bottom and w["text"].upper() in
                ("NET", "SUBTOTAL", "SUB-TOTAL", "GRAND", "VAT", "TAX") ]
        end = min(stop) - 1 if stop else page.height
        body = [w for w in words if head_bottom <= w["top"] < end]
        starts = sorted({round(w["top"]) for w in body if col(w) == "qty" and to_num(w["text"]) is not None})
        sku_tops = sorted({round(w["top"]) for w in body if col(w) == "sku"})
        for i, qt in enumerate(starts):
            # a row begins at the SKU line at/above its qty value
            top = max([t for t in sku_tops if t <= qt + 2] or [qt]) - 2
            nxt = [t for t in sku_tops if t > qt + 2]
            bottom = (min(nxt) - 2) if nxt else end
            rw = [w for w in body if top <= w["top"] < bottom]
            cell = {k: " ".join(w["text"] for w in sorted(rw, key=lambda w: (round(w["top"]), w["x0"])) if col(w) == k)
                    for k in ("sku", "desc", "qty", "unit", "total")}
            qty, unit = to_num(cell["qty"]), to_num(cell["unit"])
            if qty and unit is not None:
                items.append({"sku": clean_sku(cell["sku"]), "description": clean_desc(cell["desc"]),
                              "qty": qty, "list_unit": unit})
    return items


LINE = re.compile(rf"^(?P<sku>[A-Za-z0-9][A-Za-z0-9\-_./]{{2,}})\s+(?P<desc>.+?)\s+(?P<qty>{NUM})\s+\D{{0,4}}(?P<unit>{NUM})\s+\D{{0,4}}(?P<total>{NUM})\s*$")


def _from_text(text):
    items = []
    for line in text.splitlines():
        m = LINE.match(line.strip())
        if m:
            qty, unit = to_num(m["qty"]), to_num(m["unit"])
            if qty and unit is not None:
                items.append({"sku": m["sku"], "description": m["desc"].strip(), "qty": qty, "list_unit": unit})
    return items


def parse_invoice(data: bytes) -> dict:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        items, method = [], ""
        for name, fn in (("table", lambda: _from_tables(pdf)), ("columns", lambda: _from_positions(pdf)),
                         ("text", lambda: _from_text(text))):
            try:
                items = fn()
            except Exception:
                items = []
            if items:
                method = name
                break
    return {"text": text, "items": items, "method": method, "has_text_layer": bool(text.strip())}
