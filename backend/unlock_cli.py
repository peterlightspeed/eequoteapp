"""Emergency: python unlock_cli.py someone@company.com   (unlocks + resets attempts)"""
import sys
from sqlalchemy import select
from app.db import SessionLocal, User
with SessionLocal() as db:
    u = db.scalar(select(User).where(User.email == sys.argv[1].lower()))
    if not u: sys.exit("No such user")
    u.locked = False; u.failed_attempts = 0; db.commit(); print("Unlocked", u.email)
