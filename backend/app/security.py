import base64, hashlib, hmac, re, secrets, struct, threading, time
from urllib.parse import quote as urlquote
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt, jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import config
from .db import get_db, User

bearer = HTTPBearer(auto_error=False)


# ---------- passwords ----------
def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def check_pw(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode()[:72], h.encode())
    except ValueError:
        return False


DUMMY_HASH = hash_pw("timing-equaliser-not-a-real-password")   # unknown e-mails cost the same time as real ones

COMMON = {"password", "password1", "password123", "1234567890", "123456789a", "qwertyuiop", "qwerty12345",
          "admin12345", "welcome123", "changeme123", "letmein123", "iloveyou123", "eesolutions", "eesolutions1"}


def check_password_policy(p: str) -> None:
    n = config.MIN_PASSWORD_LEN
    if len(p) < n:
        raise HTTPException(400, f"Password must be at least {n} characters long.")
    if len(p) > 128:
        raise HTTPException(400, "Password is too long (128 characters maximum).")
    if not (re.search(r"[A-Za-z]", p) and re.search(r"\d", p)):
        raise HTTPException(400, "Password must contain both letters and numbers.")
    if p.lower() in COMMON or len(set(p)) < 5:
        raise HTTPException(400, "That password is too easy to guess. Choose another.")


# ---------- simple per-IP rate limiter (one app process, so in-memory is enough) ----------
class RateLimiter:
    def __init__(self, limit: int, window: int = 60):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 5000:                    # keep memory bounded
                for k in [k for k, v in self.hits.items() if not v][:1000]:
                    self.hits.pop(k, None)
            return True


login_limiter = RateLimiter(config.LOGIN_RATE_PER_MIN, 60)
api_limiter = RateLimiter(config.GENERAL_RATE_PER_MIN, 60)


# ---------- two-step sign-in (TOTP, RFC 6238: Google Authenticator, Microsoft Authenticator, Authy, ...) ----------
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


_last_step: dict[int, int] = {}


def verify_totp(secret: str, code: str, user_id: int, window: int = 1) -> bool:
    code = re.sub(r"\s", "", code or "")
    if not (code.isdigit() and len(code) == 6) or not secret:
        return False
    now = int(time.time() // 30)
    for i in range(-window, window + 1):
        step = now + i
        if hmac.compare_digest(_hotp(secret, step), code):
            if _last_step.get(user_id, -1) >= step:      # a code can be used only once
                return False
            _last_step[user_id] = step
            return True
    return False


def totp_uri(secret: str, email: str) -> str:
    return (f"otpauth://totp/EE%20Solutions:{urlquote(email)}?secret={secret}"
            f"&issuer=EE%20Solutions&algorithm=SHA1&digits=6&period=30")


# ---------- sessions ----------
def _fingerprint(u: User) -> str:
    """Changes whenever the password changes, so old tokens stop working after a password change/reset."""
    return hashlib.sha256((config.JWT_SECRET + u.password_hash).encode()).hexdigest()[:16]


def make_token(u: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(u.id), "pv": _fingerprint(u), "iat": now,
                       "exp": now + timedelta(hours=config.JWT_HOURS)}, config.JWT_SECRET, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        data = jwt.decode(cred.credentials, config.JWT_SECRET, algorithms=["HS256"],
                          options={"require": ["exp", "sub", "pv"]})
        uid = int(data["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    u = db.get(User, uid)
    if not u or u.locked or not hmac.compare_digest(str(data["pv"]), _fingerprint(u)):
        raise HTTPException(401, "Session no longer valid. Please sign in again.")
    return u


def admin_user(u: User = Depends(current_user)) -> User:
    if u.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admins only")
    return u