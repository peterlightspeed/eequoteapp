import os
from dotenv import load_dotenv
load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development").lower()
PRODUCTION = APP_ENV == "production"


def _db_url():
    url = os.getenv("DATABASE_URL", "sqlite:///./local.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


DATABASE_URL = _db_url()
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_HOURS = int(os.getenv("JWT_HOURS", "8"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "3"))
LOGIN_RATE_PER_MIN = int(os.getenv("LOGIN_RATE_PER_MIN", "10"))     # per IP address
MIN_PASSWORD_LEN = int(os.getenv("MIN_PASSWORD_LEN", "10"))
SUPERADMIN_EMAIL = os.getenv("SUPERADMIN_EMAIL", "").strip().lower()
SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD", "")
CORS_ORIGINS = _list("CORS_ORIGINS")
ALLOWED_HOSTS = _list("ALLOWED_HOSTS", "*")                         # e.g. 192.168.1.50,quotes.ee.local
ENABLE_DOCS = os.getenv("ENABLE_DOCS", "false" if PRODUCTION else "true").lower() in ("1", "true", "yes")
DEFAULT_VAT = os.getenv("DEFAULT_VAT", "0.075")
DEFAULT_MARGIN = os.getenv("DEFAULT_MARGIN", "0.20")
DEFAULT_FX = os.getenv("DEFAULT_FX", "1400")
# false = identical to Dami's Excel (no rounding while calculating); true = each line rounded to cents
ROUND_LINES = os.getenv("ROUND_LINES", "false").lower() in ("1", "true", "yes")
# ---- quote reference: INV/EESOL/20261104_2603 ----
REF_PREFIX = os.getenv("REF_PREFIX", "INV/EESOL")
REF_SEQ_START = int(os.getenv("REF_SEQ_START", "1"))          # first running number (then +1 for every saved quote)
GENERAL_RATE_PER_MIN = int(os.getenv("GENERAL_RATE_PER_MIN", "240"))   # API calls per minute per IP

# ---- defaults printed on / offered for the quote ----
COMPANY_NAME = os.getenv("COMPANY_NAME", "EE Solutions Limited")
AUTHORIZED_BY = os.getenv("AUTHORIZED_BY", "Babajide Padonu")
PREPARED_BY = os.getenv("PREPARED_BY", "")
PREPARED_ROLE = os.getenv("PREPARED_ROLE", "")
PREPARED_EMAIL = os.getenv("PREPARED_EMAIL", "")
PREPARED_PHONE = os.getenv("PREPARED_PHONE", "")
QUOTE_VALID_DAYS = int(os.getenv("QUOTE_VALID_DAYS", "15"))
TERMS_TEMPLATE = [
    "Only Government {vat}% VAT included. All other (WHT taxes, levies or any other charges of Nigerian law are not included)",
    "Coverage period is stated",
    "Payment terms is bank transfer to the company's corporate account",
    "Quote is valid for {days} days from the date of the quote",
]
