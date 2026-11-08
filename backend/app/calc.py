"""Pricing maths – mirrors Dami's Excel sheet, now for ANY source currency -> ANY quote currency.

  source currency  = what the distributor charges EE (USD, NGN, EUR, ...)
  quote currency   = what the customer is quoted in   (NGN, USD, ...)
  fx_rate          = units of QUOTE currency for 1 unit of SOURCE currency (1 when both are the same)

Per line (Excel columns in brackets):
  list_total  G = list_unit(E) x qty(F)
  cost        I = G x (1 - discount H)        what EE really pays the distributor   (source currency)
  sell        K = G x (1 + markup)            Excel stores markup as a NEGATIVE "discount" J:  K = G*(1-J)
  sell_unit   L = K / qty
Totals:
  margin      = 1 - cost_total / sell_total
  VAT         = subtotal x vat_rate           (7.5%)
  *_out       = the same figures x fx_rate    (what is printed on the customer quote)

Nothing is rounded while calculating (same as Excel); round only when displaying.
A margin target m is converted with  markup = m / (1 - m)   (40% margin = 66.67% markup).
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

D = Decimal
TWO = D("0.01")


def d(x) -> Decimal:
    return D(str(x))


def money(x) -> Decimal:
    """Excel-style display rounding (half away from zero)."""
    return d(x).quantize(TWO, rounding=ROUND_HALF_UP)


def markup_from_margin(margin) -> Decimal:
    m = d(margin)
    if not (D(0) <= m < D(1)):
        raise ValueError("margin must be from 0 up to (but not including) 100%")
    return m / (D(1) - m)


def margin_from_markup(markup) -> Decimal:
    k = d(markup)
    return k / (D(1) + k)


@dataclass
class Item:
    sku: str
    description: str
    qty: Decimal
    list_unit: Decimal                  # distributor price per unit (source currency)
    discount: Decimal = D(0)            # distributor discount on the buy side (fraction)
    markup: Decimal | None = None       # per-line override; None = use the quote markup
    duration: str = ""                  # e.g. "12 months" (printed on the quote)


@dataclass
class Line:
    sku: str
    description: str
    duration: str
    qty: Decimal
    list_unit: Decimal
    list_total: Decimal
    cost: Decimal
    sell_total_src: Decimal
    sell_unit_src: Decimal
    sell_total_out: Decimal
    sell_unit_out: Decimal
    markup_used: Decimal


@dataclass
class Quote:
    lines: list[Line] = field(default_factory=list)
    cost_total: Decimal = D(0)          # source currency
    subtotal_src: Decimal = D(0)
    vat_src: Decimal = D(0)
    total_src: Decimal = D(0)
    subtotal_out: Decimal = D(0)        # quote currency (printed)
    vat_out: Decimal = D(0)
    total_out: Decimal = D(0)
    profit_src: Decimal = D(0)
    margin: Decimal = D(0)


def compute_quote(items: list[Item], markup, fx_rate, vat_rate="0.075", round_lines=False) -> Quote:
    mk, fx, vat = d(markup), d(fx_rate), d(vat_rate)
    r = Quote()
    for it in items:
        qty = d(it.qty)
        g = d(it.list_unit) * qty
        used = mk if it.markup is None else d(it.markup)
        k = g * (D(1) + used)
        if round_lines:                      # optional: whole cents per line so the printed quote always adds up
            k = money(k)
        unit = k / qty if qty else D(0)
        r.lines.append(Line(it.sku, it.description, it.duration, qty, d(it.list_unit), g,
                            g * (D(1) - d(it.discount)), k, unit, k * fx, unit * fx, used))
    r.cost_total = sum((l.cost for l in r.lines), D(0))
    r.subtotal_src = sum((l.sell_total_src for l in r.lines), D(0))
    r.vat_src = money(r.subtotal_src * vat) if round_lines else r.subtotal_src * vat
    r.total_src = r.subtotal_src + r.vat_src
    r.subtotal_out, r.vat_out, r.total_out = r.subtotal_src * fx, r.vat_src * fx, r.total_src * fx
    r.profit_src = r.subtotal_src - r.cost_total
    r.margin = (D(1) - r.cost_total / r.subtotal_src) if r.subtotal_src else D(0)
    return r


def markup_for_budget(items: list[Item], target_subtotal) -> Decimal:
    """Customer budget mode: quote-level markup so that the (pre-VAT) subtotal equals the budget
    (in the SOURCE currency). Lines with their own markup stay fixed (e.g. professional services)."""
    fixed = D(0)
    base = D(0)
    for it in items:
        g = d(it.list_unit) * d(it.qty)
        if it.markup is None:
            base += g
        else:
            fixed += g * (D(1) + d(it.markup))
    if base <= 0:
        raise ValueError("Need at least one line that uses the default margin")
    mk = (d(target_subtotal) - fixed) / base - D(1)
    if mk < 0:
        raise ValueError("Budget is lower than the distributor price")
    return mk
