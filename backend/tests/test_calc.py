"""Run:  cd backend && python -m pytest -q
Checks the app against Dami's Excel sheet, EE's real quote template, and the sample PDFs."""
import os, sys
from datetime import date
from decimal import Decimal as D
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.calc import Item, compute_quote, markup_from_margin, markup_for_budget, margin_from_markup, money
from app.currency import amount_in_words, quote_date
from app.pdf_parse import parse_invoice

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def test_matches_dami_sheet():
    # Excel: AR-Core 300 x $2, "discount" -0.667 (=66.7% markup); PS $20 at 50% markup; rate 1400
    items = [Item("AR-Core", "x", D(300), D(2), markup=D("0.667")), Item("PS", "x", D(1), D(20), markup=D("0.5"))]
    r = compute_quote(items, 0, 1400)
    assert r.lines[0].sell_total_src == D("1000.2") and r.lines[0].sell_unit_src == D("3.334")
    assert r.lines[0].sell_unit_out == D("4667.6")
    assert r.subtotal_src == D("1030.2") and r.vat_src == D("77.265") and r.total_src == D("1107.465")
    assert r.total_out == D("1550451") and r.vat_out == D("108171") and r.subtotal_out == D("1442280")
    assert abs(float(r.margin) - 0.3981751116288099) < 1e-12


def test_ee_quote_template_numbers():
    # EE's real quote: 50 x 5,000.24 + services 2,000.00 = 252,012.00 ; VAT 7.5% = 18,900.90 ; total 270,912.90 (Naira -> Naira, rate 1)
    items = [Item("AR-COMPLETE", "x", D(50), D("5000.24"), markup=D(0), duration="12 months"), Item("PS", "x", D(1), D(2000), markup=D(0))]
    r = compute_quote(items, 0, 1)
    assert money(r.subtotal_out) == D("252012.00") and money(r.vat_out) == D("18900.90") and money(r.total_out) == D("270912.90")
    assert amount_in_words(r.total_out, "NGN") == "Two hundred and seventy thousand, nine hundred and twelve naira, ninety kobo."
    assert quote_date(date(2026, 11, 4)) == "4TH NOV., 2026"


def test_other_currency_pairs():
    # distributor quotes EUR 100, customer wants USD at 1 EUR = 1.10 USD, 25% margin -> markup 33.33% -> EUR 133.33 -> USD 146.67
    r = compute_quote([Item("a", "", D(1), D(100))], markup_from_margin("0.25"), "1.10")
    assert money(r.subtotal_src) == D("133.33") and money(r.subtotal_out) == D("146.67")
    # NGN distributor price shown in NGN with the same margin maths
    r = compute_quote([Item("a", "", D(1), D(600000))], markup_from_margin("0.4"), 1)
    assert r.subtotal_out == D("1000000")


def test_margin_conversion_and_budget():
    assert markup_from_margin("0.2") == D("0.25") and round(markup_from_margin("0.4"), 6) == D("0.666667")
    items = [Item("a", "", D(1), D(600))]
    assert round(compute_quote(items, markup_from_margin("0.4"), 1400).subtotal_src, 6) == D("1000")
    assert round(margin_from_markup(markup_for_budget(items, 1000)), 6) == D("0.4")


def test_parse_sample_pdfs():
    for name, prices in (("distributor_invoice_sample.pdf", [19.99, 7.0, 14.16]), ("ee_invoice_template_sample.pdf", [35.0, 15.0, 25.0])):
        r = parse_invoice(open(os.path.join(SAMPLES, name), "rb").read())
        assert [i["list_unit"] for i in r["items"]] == prices
        assert r["items"][0]["sku"] == "ADOBE-ACR-PRO"
