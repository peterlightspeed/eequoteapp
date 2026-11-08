from datetime import datetime
from sqlalchemy import create_engine, String, Integer, Boolean, Text, DateTime, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "app_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")   # user | admin | superadmin
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)      # authenticator-app key
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))


class Quote(Base):
    __tablename__ = "app_quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(60), index=True)
    invoice_date: Mapped[str] = mapped_column(String(30))
    distributor: Mapped[str] = mapped_column(String(120), default="")
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_address: Mapped[str] = mapped_column(Text, default="")
    margin: Mapped[float] = mapped_column(Float)
    fx_rate: Mapped[float] = mapped_column(Float)
    vat_rate: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")
    show_rate: Mapped[bool] = mapped_column(Boolean, default=True)
    items_json: Mapped[str] = mapped_column(Text)
    total_usd: Mapped[float] = mapped_column(Float, default=0)
    total_ngn: Mapped[float] = mapped_column(Float, default=0)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # NOTE: total_usd / total_ngn are historical names; they now hold the total in the SOURCE and the QUOTE currency.
    source_currency: Mapped[str] = mapped_column(String(3), default="USD")
    quote_currency: Mapped[str] = mapped_column(String(3), default="NGN")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")      # client name, position, prepared by, terms, ...


class Audit(Base):
    """Who did what, when, from which IP. New table: created automatically on start-up."""
    __tablename__ = "app_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(60), index=True)
    detail: Mapped[str] = mapped_column(String(500), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


def ensure_columns():
    """Tiny auto-migration: add columns that exist in the models but not yet in the database
    (create_all only creates missing TABLES). Safe to run on every start."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'
            if col.default is not None and getattr(col.default, "is_scalar", False):
                v = col.default.arg
                ddl += " DEFAULT " + ("TRUE" if v is True else "FALSE" if v is False else
                                      "'" + str(v).replace("'", "''") + "'" if isinstance(v, str) else str(v))
            with engine.begin() as cn:
                cn.execute(text(ddl))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()