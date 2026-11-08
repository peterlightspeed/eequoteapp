"""Live exchange-rate SUGGESTION for any currency pair. Free, no API key: https://open.er-api.com/v6/latest/<BASE>
The rate actually used on a quote is always the editable one typed by staff."""
import re, time
import httpx

_cache: dict = {}          # base -> (timestamp, rates)
TTL = 3600                 # refresh hourly


def live_rate(base: str, quote: str) -> float | None:
    base, quote = (base or "").upper(), (quote or "").upper()
    if not (re.fullmatch(r"[A-Z]{3}", base) and re.fullmatch(r"[A-Z]{3}", quote)):
        return None
    if base == quote:
        return 1.0
    ent = _cache.get(base)
    if not ent or time.time() - ent[0] > TTL:
        try:
            r = httpx.get(f"https://open.er-api.com/v6/latest/{base}", timeout=8).json()
            if r.get("result") == "success":
                _cache[base] = (time.time(), r["rates"])
        except Exception:
            pass
    rates = _cache.get(base, (0, {}))[1]
    v = rates.get(quote)
    return float(v) if v else None
