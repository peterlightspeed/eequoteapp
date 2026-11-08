import io, json, os, re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import config
from .db import Base, engine, ensure_columns, get_db, SessionLocal, User, Setting, Quote, Audit
from .security import (hash_pw, check_pw, make_token, current_user, admin_user, check_password_policy,
                       login_limiter, api_limiter, DUMMY_HASH, new_totp_secret, verify_totp, totp_uri)
from .calc import Item, compute_quote, markup_from_margin, margin_from_markup, markup_for_budget
from .currency import CURRENCIES, quote_date, valid_code
from .pdf_parse import parse_invoice, extract_text
from .invoice_pdf import build_invoice
from .fx import live_rate

app = FastAPI(title="EE Solutions Quote Automation",
              docs_url="/docs" if config.ENABLE_DOCS else None, redoc_url=None,
              openapi_url="/openapi.json" if config.ENABLE_DOCS else None)

_ALLOWED = [h.lower() for h in config.ALLOWED_HOSTS] + ["localhost", "127.0.0.1"]


def _host_ok(host: str) -> bool:
    host = host.split(":")[0].lower()
    return any(host == a or (a.startswith("*.") and host.endswith(a[1:])) for a in _ALLOWED)


if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    p = request.url.path
    if config.ALLOWED_HOSTS != ["*"] and p != "/health" and not _host_ok(request.headers.get("host", "")):
        return PlainTextResponse("Invalid host header", status_code=400)     # only the addresses in ALLOWED_HOSTS are served
    if p.startswith("/api") and not api_limiter.allow(_ip(request)):
        return JSONResponse({"detail": "Too many requests. Please slow down for a moment."}, status_code=429)
    resp = await call_next(request)
    h = resp.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    h["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    if not (p.startswith("/docs") or p.startswith("/openapi")):
        h["Content-Security-Policy"] = CSP
    if p.startswith("/api") or p in ("/", "/index.html"):
        h["Cache-Control"] = "no-store"
    if request.url.scheme == "https":
        h["Strict-Transport-Security"] = "max-age=31536000"
    return resp


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Short, safe messages: never echo back what the user typed (passwords included)."""
    errs = [{"loc": [str(x) for x in e.get("loc", [])][-2:], "msg": e.get("msg", "invalid value")} for e in exc.errors()]
    return JSONResponse({"detail": errs}, status_code=422)


def audit(db: Session, actor: str, action: str, detail: str = "", ip: str = ""):
    try:
        db.add(Audit(actor=(actor or "")[:255], action=action[:60], detail=(detail or "")[:500], ip=(ip or "")[:64]))
        db.commit()
    except Exception:
        db.rollback()


def _production_checks():
    if not config.PRODUCTION:
        return
    problems = []
    if config.JWT_SECRET in ("change-me", "temp", "put-a-long-random-string-here") or len(config.JWT_SECRET) < 32:
        problems.append("JWT_SECRET must be a random string of at least 32 characters")
    if config.SUPERADMIN_PASSWORD:
        try:
            check_password_policy(config.SUPERADMIN_PASSWORD)
        except HTTPException as e:
            problems.append("SUPERADMIN_PASSWORD: " + str(e.detail))
    if config.ALLOWED_HOSTS == ["*"]:
        problems.append("ALLOWED_HOSTS must list the address(es) people use, e.g. ALLOWED_HOSTS=ee-quotes.onrender.com")
    if problems:
        raise RuntimeError("Unsafe production configuration:\n - " + "\n - ".join(problems))


@app.on_event("startup")
def startup():
    _production_checks()
    Base.metadata.create_all(engine)
    ensure_columns()
    with SessionLocal() as db:
        for k, v in {"fx_rate": config.DEFAULT_FX, "vat_rate": config.DEFAULT_VAT, "margin": config.DEFAULT_MARGIN}.items():
            if not db.get(Setting, k):
                db.add(Setting(key=k, value=v))
        if config.SUPERADMIN_EMAIL and config.SUPERADMIN_PASSWORD:
            if not db.scalar(select(User).where(User.email == config.SUPERADMIN_EMAIL)):
                db.add(User(email=config.SUPERADMIN_EMAIL, password_hash=hash_pw(config.SUPERADMIN_PASSWORD), role="superadmin"))
        db.commit()


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"ok": True}


# ---------- auth ----------
class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    code: str = Field("", max_length=12)                 # 6-digit code from the authenticator app (if turned on)


LOCK_MSG = "Account locked after too many failed attempts. Ask an admin to unlock it."


def _login_failed(db, u, ip, kind, message):
    u.failed_attempts += 1
    if u.failed_attempts >= config.MAX_LOGIN_ATTEMPTS:
        u.locked = True
    left = config.MAX_LOGIN_ATTEMPTS - u.failed_attempts
    locked, email = u.locked, u.email
    db.commit()
    audit(db, email, "login_locked" if locked else kind, "", ip)
    if locked:
        raise HTTPException(423, LOCK_MSG)
    raise HTTPException(401, f"{message} ({left} attempts left)")


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = _ip(request)
    if not login_limiter.allow(ip):
        raise HTTPException(429, "Too many sign-in attempts from this computer. Please wait a minute and try again.")
    email = body.email.strip().lower()
    u = db.scalar(select(User).where(User.email == email))
    if not u:                                   # not on the allow-list
        check_pw(body.password, DUMMY_HASH)     # same response time as a real account
        audit(db, email, "login_unknown_email", "", ip)
        raise HTTPException(401, "Invalid email or password")
    if u.locked:
        audit(db, u.email, "login_blocked_locked", "", ip)
        raise HTTPException(423, LOCK_MSG)
    if not check_pw(body.password, u.password_hash):
        _login_failed(db, u, ip, "login_failed", "Invalid email or password")
    if u.totp_enabled:                          # second step
        code = body.code.strip()
        if not code:
            return {"mfa_required": True}
        if not verify_totp(u.totp_secret or "", code, u.id):
            _login_failed(db, u, ip, "login_bad_code", "That code is not right")
    u.failed_attempts = 0
    db.commit()
    audit(db, u.email, "login_ok", "2-step" if u.totp_enabled else "", ip)
    return {"token": make_token(u), "email": u.email, "role": u.role}


@app.get("/api/auth/me")
def me(u: User = Depends(current_user)):
    return {"email": u.email, "role": u.role, "totp_enabled": bool(u.totp_enabled)}


class PwIn(BaseModel):
    old_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@app.post("/api/auth/change-password")
def change_pw(b: PwIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not check_pw(b.old_password, u.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if b.new_password == b.old_password:
        raise HTTPException(400, "Choose a password different from the current one")
    check_password_policy(b.new_password)
    u.password_hash = hash_pw(b.new_password)
    db.commit()
    audit(db, u.email, "password_changed", "", _ip(request))
    return {"ok": True, "token": make_token(u)}     # fresh token; all older sessions stop working


class CodeIn(BaseModel):
    code: str = Field(max_length=12)


@app.post("/api/auth/2fa/setup")
def totp_setup(u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.totp_enabled:
        raise HTTPException(400, "Two-step sign-in is already on. Turn it off first if you want to set it up again.")
    u.totp_secret = new_totp_secret()
    db.commit()
    return {"secret": u.totp_secret, "uri": totp_uri(u.totp_secret, u.email)}


@app.post("/api/auth/2fa/enable")
def totp_enable(b: CodeIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not u.totp_secret:
        raise HTTPException(400, "Start the setup first")
    if not verify_totp(u.totp_secret, b.code, u.id):
        raise HTTPException(400, "That code is not right. Check the time on your phone and try the next code.")
    u.totp_enabled = True
    db.commit()
    audit(db, u.email, "2fa_enabled", "", _ip(request))
    return {"ok": True}


class DisableIn(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field("", max_length=12)


@app.post("/api/auth/2fa/disable")
def totp_disable(b: DisableIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not check_pw(b.password, u.password_hash):
        raise HTTPException(400, "Password is wrong")
    if u.totp_enabled and not verify_totp(u.totp_secret or "", b.code, u.id):
        raise HTTPException(400, "Enter a current code from your authenticator app")
    u.totp_enabled = False
    u.totp_secret = None
    db.commit()
    audit(db, u.email, "2fa_disabled", "", _ip(request))
    return {"ok": True}


# ---------- admin ----------
EMAIL_RE = re.compile(r"^[^@\s]{1,100}@[^@\s]+\.[^@\s]{2,}$")


def _u(u):
    return {"id": u.id, "email": u.email, "role": u.role, "locked": u.locked, "failed_attempts": u.failed_attempts,
            "totp_enabled": bool(u.totp_enabled)}


@app.get("/api/admin/users")
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [_u(u) for u in db.scalars(select(User).order_by(User.email))]


class NewUser(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    role: str = "user"


@app.post("/api/admin/users")
def add_user(b: NewUser, request: Request, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    if b.role not in ("user", "admin"):
        raise HTTPException(400, "role must be user or admin")
    if b.role == "admin" and a.role != "superadmin":
        raise HTTPException(403, "Only the super admin can create admins")
    email = b.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "That does not look like an email address")
    check_password_policy(b.password)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already exists")
    u = User(email=email, password_hash=hash_pw(b.password), role=b.role)
    db.add(u)
    db.commit()
    audit(db, a.email, "user_added", f"{email} ({b.role})", _ip(request))
    return _u(u)


def _target(db, uid):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


@app.post("/api/admin/users/{uid}/unlock")
def unlock(uid: int, request: Request, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _target(db, uid)
    u.locked = False
    u.failed_attempts = 0
    db.commit()
    audit(db, a.email, "user_unlocked", u.email, _ip(request))
    return _u(u)


class ResetIn(BaseModel):
    new_password: str = Field(max_length=200)


def _may_touch(a, u):
    if u.role in ("admin", "superadmin") and a.role != "superadmin" and u.id != a.id:
        raise HTTPException(403, "Only the super admin can change an admin's account")


@app.post("/api/admin/users/{uid}/reset-password")
def reset_pw(uid: int, b: ResetIn, request: Request, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _target(db, uid)
    _may_touch(a, u)
    check_password_policy(b.new_password)
    u.password_hash = hash_pw(b.new_password)
    u.locked = False
    u.failed_attempts = 0
    db.commit()
    audit(db, a.email, "password_reset", u.email, _ip(request))
    return _u(u)


@app.post("/api/admin/users/{uid}/reset-2fa")
def reset_2fa(uid: int, request: Request, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _target(db, uid)
    _may_touch(a, u)
    u.totp_enabled = False
    u.totp_secret = None
    db.commit()
    audit(db, a.email, "2fa_reset", u.email, _ip(request))
    return _u(u)


@app.delete("/api/admin/users/{uid}")
def delete_user(uid: int, request: Request, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _target(db, uid)
    if u.id == a.id:
        raise HTTPException(400, "You cannot delete yourself")
    if u.role == "superadmin":
        raise HTTPException(403, "The super admin cannot be deleted")
    if u.role == "admin" and a.role != "superadmin":
        raise HTTPException(403, "Only the super admin can delete admins")
    email = u.email
    db.delete(u)
    db.commit()
    audit(db, a.email, "user_deleted", email, _ip(request))
    return {"ok": True}


@app.get("/api/admin/audit")
def audit_log(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Audit).order_by(Audit.id.desc()).limit(200))
    return [{"ts": r.ts.isoformat(), "actor": r.actor, "action": r.action, "detail": r.detail, "ip": r.ip} for r in rows]


# ---------- settings / meta / fx ----------
def get_settings(db):
    return {s.key: s.value for s in db.scalars(select(Setting))}


@app.get("/api/settings")
def settings(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_settings(db)


class SettingsIn(BaseModel):
    vat_rate: float | None = Field(None, ge=0, lt=1)
    margin: float | None = Field(None, ge=0, lt=1)
    fx_pair: str | None = Field(None, pattern=r"^[A-Z]{3}_[A-Z]{3}$")     # e.g. USD_NGN  (1 USD = fx_value NGN)
    fx_value: float | None = Field(None, gt=0, le=1_000_000_000)


@app.put("/api/settings")
def put_settings(b: SettingsIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    changes = {}
    if b.vat_rate is not None: changes["vat_rate"] = b.vat_rate
    if b.margin is not None: changes["margin"] = b.margin
    if b.fx_pair and b.fx_value:
        changes["fx_USD_NGN" if b.fx_pair == "USD_NGN" else f"fx_{b.fx_pair}"] = b.fx_value
    for k, v in changes.items():
        s = db.get(Setting, k)
        if s:
            s.value = str(v)
        else:
            db.add(Setting(key=k, value=str(v)))
    db.commit()
    audit(db, u.email, "defaults_saved", json.dumps(changes), _ip(request))
    return get_settings(db)


@app.get("/api/meta")
def meta(_: User = Depends(current_user)):
    return {"company_name": config.COMPANY_NAME, "authorized_by": config.AUTHORIZED_BY,
            "prepared": {"name": config.PREPARED_BY, "role": config.PREPARED_ROLE,
                         "email": config.PREPARED_EMAIL, "phone": config.PREPARED_PHONE},
            "terms_template": config.TERMS_TEMPLATE, "valid_days": config.QUOTE_VALID_DAYS,
            "currencies": [{"code": c, "name": v[0]} for c, v in CURRENCIES.items()]}


@app.get("/api/fx/live")
def fx_live(base: str = "USD", quote: str = "NGN", _: User = Depends(current_user)):
    return {"base": base.upper(), "quote": quote.upper(), "rate": live_rate(base, quote),
            "note": "Market suggestion only. The rate used on a quote is the editable one."}


# ---------- PDFs ----------
async def _read_pdf(file: UploadFile) -> bytes:
    data = await file.read(15_000_001)
    if len(data) > 15_000_000:
        raise HTTPException(413, "PDF too large (15 MB max)")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a PDF")
    try:
        pages = len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        raise HTTPException(400, "Could not read this PDF (is it password-protected or damaged?)")
    if pages > 60:
        raise HTTPException(400, "PDF has too many pages (60 max)")
    return data


@app.post("/api/pdf/parse")
async def pdf_parse(file: UploadFile = File(...), _: User = Depends(current_user)):
    data = await _read_pdf(file)
    try:
        return parse_invoice(data)
    except Exception:
        raise HTTPException(400, "Could not read this PDF")


@app.post("/api/pdf/text")
async def pdf_text(file: UploadFile = File(...), _: User = Depends(current_user)):
    return {"text": extract_text(await _read_pdf(file))}


# ---------- calculation ----------
class ItemIn(BaseModel):
    sku: str = Field("", max_length=100)
    description: str = Field("", max_length=1500)
    duration: str = Field("", max_length=40)               # e.g. "12 months"
    qty: float = Field(gt=0, le=1_000_000)
    list_unit: float = Field(ge=0, le=100_000_000_000)     # distributor price per unit (source currency)
    discount: float = Field(0, ge=0, lt=1)                 # distributor discount (buy side)
    margin: float | None = Field(None, ge=0, lt=1)         # per-line margin override (e.g. services)


class CalcIn(BaseModel):
    items: list[ItemIn] = Field(max_length=200)
    margin: float = Field(ge=0, lt=1)                      # quote-level margin, e.g. 0.30
    fx_rate: float = Field(gt=0, le=1_000_000_000)         # quote currency per 1 source currency
    vat_rate: float = Field(0.075, ge=0, lt=1)


def _items(items):
    return [Item(i.sku, i.description, D(str(i.qty)), D(str(i.list_unit)), D(str(i.discount)),
                 None if i.margin is None else markup_from_margin(i.margin), i.duration) for i in items]


def _run(b: CalcIn):
    return compute_quote(_items(b.items), markup_from_margin(b.margin), b.fx_rate, b.vat_rate, config.ROUND_LINES)


def _ser(r):
    f = float
    lines = [{**{k: (f(v) if isinstance(v, D) else v) for k, v in l.__dict__.items()},
              "margin_used": f(margin_from_markup(l.markup_used))} for l in r.lines]
    return {"lines": lines, **{k: f(v) for k, v in r.__dict__.items() if k != "lines"}}


@app.post("/api/calc")
def calc(b: CalcIn, _: User = Depends(current_user)):
    return _ser(_run(b))


class BudgetIn(BaseModel):
    items: list[ItemIn] = Field(max_length=200)
    budget: float = Field(gt=0, le=1_000_000_000_000)      # customer budget before VAT, in the SOURCE currency


@app.post("/api/calc/budget")
def budget(b: BudgetIn, _: User = Depends(current_user)):
    try:
        mk = markup_for_budget(_items(b.items), D(str(b.budget)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"margin": float(margin_from_markup(mk))}


# ---------- quotes ----------
LAGOS = timezone(timedelta(hours=1))


def _today() -> date:
    return datetime.now(LAGOS).date()


def _pct(vat) -> str:
    return f"{D(str(vat)) * 100:.2f}".rstrip("0").rstrip(".")


def default_terms(vat) -> list[str]:
    return [t.format(vat=_pct(vat), days=config.QUOTE_VALID_DAYS) for t in config.TERMS_TEMPLATE]


@app.get("/api/quotes/next-number")
def next_number(_: User = Depends(current_user), db: Session = Depends(get_db)):
    n = (db.scalar(select(func.count(Quote.id))) or 0) + config.REF_SEQ_START
    return {"reference": f"{config.REF_PREFIX}/{_today():%Y%m%d}_{n:04d}"}


@app.get("/api/distributors")
def distributors(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return sorted({d for d in db.scalars(select(Quote.distributor)) if d})


class QuoteIn(CalcIn):
    reference: str = Field(min_length=1, max_length=60)
    distributor: str = Field("", max_length=120)
    source_currency: str = "USD"
    quote_currency: str = "NGN"
    quote_date: str = Field("", max_length=10)             # YYYY-MM-DD (blank = today)
    product_title: str = Field("", max_length=80)          # prints as "<PRODUCT> QUOTE"
    company_name: str = Field(min_length=1, max_length=200)
    client_name: str = Field("", max_length=200)
    position: str = Field("", max_length=200)
    address1: str = Field("", max_length=300)
    address2: str = Field("", max_length=300)
    city_country: str = Field("", max_length=200)
    prepared_by: str = Field("", max_length=120)
    prepared_role: str = Field("", max_length=120)
    prepared_email: str = Field("", max_length=200)
    prepared_phone: str = Field("", max_length=60)
    authorized_by: str = Field("", max_length=120)
    terms: str = Field("", max_length=3000)                # one term per line


def _fill(qt: Quote, b: QuoteIn):
    """Copy the submitted quote form onto a Quote row (used by create and update)."""
    if not (valid_code(b.source_currency) and valid_code(b.quote_currency)):
        raise HTTPException(400, "Unsupported currency")
    try:
        qd = date.fromisoformat(b.quote_date) if b.quote_date else _today()
    except ValueError:
        raise HTTPException(400, "Quote date must look like 2026-11-04")
    r = _run(b)
    meta_ = {k: getattr(b, k) for k in ("product_title", "client_name", "position", "address1", "address2", "city_country",
                                        "prepared_by", "prepared_role", "prepared_email", "prepared_phone",
                                        "authorized_by", "terms")}
    meta_["date_iso"], meta_["date_display"] = qd.isoformat(), quote_date(qd)
    qt.invoice_no, qt.invoice_date, qt.distributor = b.reference.strip(), f"{qd:%d %B %Y}", b.distributor.strip()
    qt.customer_name = b.company_name.strip()
    qt.customer_address = "\n".join(x for x in (b.address1, b.address2, b.city_country) if x)
    qt.margin, qt.fx_rate, qt.vat_rate, qt.note, qt.show_rate = b.margin, b.fx_rate, b.vat_rate, "", True
    qt.items_json = json.dumps([i.model_dump() for i in b.items])
    qt.total_usd, qt.total_ngn = float(r.total_src), float(r.total_out)      # source / quote currency totals
    qt.source_currency, qt.quote_currency, qt.meta_json = b.source_currency, b.quote_currency, json.dumps(meta_)


@app.post("/api/quotes")
def save_quote(b: QuoteIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    qt = Quote(created_by=u.email)
    _fill(qt, b)
    db.add(qt)
    db.commit()
    audit(db, u.email, "quote_saved", f"{qt.invoice_no} / {qt.customer_name}", _ip(request))
    return {"id": qt.id, "reference": qt.invoice_no}


@app.put("/api/quotes/{qid}")
def update_quote(qid: int, b: QuoteIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    qt = _quote(db, qid)
    _fill(qt, b)
    db.commit()
    audit(db, u.email, "quote_updated", f"{qt.invoice_no} / {qt.customer_name}", _ip(request))
    return {"id": qt.id, "reference": qt.invoice_no}


@app.get("/api/quotes")
def list_quotes(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": q.id, "reference": q.invoice_no, "date": q.invoice_date, "distributor": q.distributor,
             "company": q.customer_name, "total_src": q.total_usd, "total_out": q.total_ngn,
             "source_currency": q.source_currency or "USD", "quote_currency": q.quote_currency or "NGN",
             "created_by": q.created_by}
            for q in db.scalars(select(Quote).order_by(Quote.id.desc()).limit(300))]


def _quote(db, qid):
    q = db.get(Quote, qid)
    if not q:
        raise HTTPException(404, "Not found")
    return q


def _fields(q: Quote) -> dict:
    """All editable fields of a saved quote (works for old quotes that have no meta yet)."""
    m = json.loads(q.meta_json or "{}")
    parts = (q.customer_address or "").split("\n")
    return {"reference": q.invoice_no, "distributor": q.distributor, "source_currency": q.source_currency or "USD",
            "quote_currency": q.quote_currency or "NGN", "product_title": m.get("product_title", ""),
            "company_name": q.customer_name, "client_name": m.get("client_name", ""), "position": m.get("position", ""),
            "address1": m.get("address1", parts[0] if parts else ""),
            "address2": m.get("address2", parts[1] if len(parts) > 1 else ""),
            "city_country": m.get("city_country", ""), "prepared_by": m.get("prepared_by", ""),
            "prepared_role": m.get("prepared_role", ""), "prepared_email": m.get("prepared_email", ""),
            "prepared_phone": m.get("prepared_phone", ""), "authorized_by": m.get("authorized_by", config.AUTHORIZED_BY),
            "terms": m["terms"] if "terms" in m else "\n".join(default_terms(q.vat_rate)),
            "date_display": m.get("date_display") or q.invoice_date}


@app.get("/api/quotes/{qid}")
def get_quote(qid: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = _quote(db, qid)
    return {"id": q.id, **_fields(q), "margin": q.margin, "fx_rate": q.fx_rate, "vat_rate": q.vat_rate,
            "items": json.loads(q.items_json)}


@app.get("/api/quotes/{qid}/pdf")
def quote_pdf(qid: int, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    q = _quote(db, qid)
    f = _fields(q)
    cur = f["quote_currency"] if f["quote_currency"] in CURRENCIES else "NGN"
    r = _run(CalcIn(items=json.loads(q.items_json), margin=q.margin, fx_rate=q.fx_rate, vat_rate=q.vat_rate))
    f.update(vat_rate=q.vat_rate, terms=[t for t in f["terms"].split("\n")])
    pdf = build_invoice(f, r, cur)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", q.invoice_no)[:60] or "quote"
    audit(db, u.email, "quote_downloaded", f"{q.invoice_no} {cur}", _ip(request))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'})


@app.delete("/api/quotes/{qid}")
def delete_quote(qid: int, request: Request, a: User = Depends(admin_user), db: Session = Depends(get_db)):
    q = _quote(db, qid)
    no = q.invoice_no
    db.delete(q)
    db.commit()
    audit(db, a.email, "quote_deleted", no, _ip(request))
    return {"ok": True}


# ---------- frontend (served by the same app; keep LAST) ----------
FRONT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONT):
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="frontend")
