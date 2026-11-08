"""Currencies the app understands, plus 'amount in words' for the printed quote."""
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# code: (display name used in the column heading, major singular, major plural, minor singular, minor plural)
CURRENCIES = {
    "NGN": ("Naira", "naira", "naira", "kobo", "kobo"),
    "USD": ("US Dollars", "dollar", "dollars", "cent", "cents"),
    "EUR": ("Euro", "euro", "euros", "cent", "cents"),
    "GBP": ("Pounds", "pound", "pounds", "penny", "pence"),
    "ZAR": ("Rand", "rand", "rand", "cent", "cents"),
    "GHS": ("Cedis", "cedi", "cedis", "pesewa", "pesewas"),
    "KES": ("Kenya Shillings", "shilling", "shillings", "cent", "cents"),
    "CAD": ("Canadian Dollars", "dollar", "dollars", "cent", "cents"),
    "AED": ("Dirhams", "dirham", "dirhams", "fils", "fils"),
}

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = ["", "thousand", "million", "billion", "trillion"]


def _below_1000(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(_ONES[n // 100] + " hundred")
        n %= 100
        if n:
            parts.append("and")
    if n >= 20:
        t = _TENS[n // 10]
        parts.append(t + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n > 0 or not parts:
        parts.append(_ONES[n])
    return " ".join(parts)


def int_to_words(n: int) -> str:
    if n == 0:
        return "zero"
    groups = []
    i = 0
    while n > 0:
        n, g = divmod(n, 1000)
        if g:
            groups.append((g, _SCALES[i]))
        i += 1
    groups.reverse()
    texts = [(_below_1000(g) + (" " + s if s else "")) for g, s in groups]
    if len(texts) == 1:
        return texts[0]
    # "two hundred and seventy thousand, nine hundred and twelve"  /  "one thousand and five"
    last_g = groups[-1][0]
    if last_g < 100:
        return ", ".join(texts[:-1]) + " and " + texts[-1]
    return ", ".join(texts)


def amount_in_words(amount, code: str) -> str:
    name, maj1, majn, min1, minn = CURRENCIES.get(code, ("", code, code, "", ""))
    v = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, minor = int(v), int((v - int(v)) * 100)
    major_word = maj1 if whole == 1 else majn
    s = f"{int_to_words(whole)} {major_word}"
    if minor:
        s += f", {int_to_words(minor)} {min1 if minor == 1 else minn}"
    else:
        s += " only"
    s = s[0].upper() + s[1:]
    return s + "."


_MONTHS = ["JAN.", "FEB.", "MAR.", "APR.", "MAY", "JUN.", "JUL.", "AUG.", "SEPT.", "OCT.", "NOV.", "DEC."]


def quote_date(d: date) -> str:
    """4TH NOV., 2026   (same style as EE's Excel template)"""
    suffix = "TH" if 11 <= d.day % 100 <= 13 else {1: "ST", 2: "ND", 3: "RD"}.get(d.day % 10, "TH")
    return f"{d.day}{suffix} {_MONTHS[d.month - 1]}, {d.year}"


def valid_code(code: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", code or "")) and code in CURRENCIES


def heading_name(code: str) -> str:
    return CURRENCIES.get(code, (code,))[0]
