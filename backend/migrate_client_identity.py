"""
Upgrades an EXISTING database for the client-identity changes. Safe to run more than once.

Run from the backend folder (after adding ENCRYPTION_KEY to backend/.env):
    python migrate_client_identity.py

What it does:
  1. creates the new table client_identities (encrypted name, phone, village, date of birth)
  2. adds predictions.guideline_notice
  3. changes the age rule on assessments from 13-100 to 18-100 for NEW records
     (NOT VALID: old records are kept exactly as they were)

Clients registered before this change have no date of birth. They can still be
looked up and their old results viewed, but a new assessment asks you to register
them again with a date of birth.

A brand-new database does not need this script: init_db.py creates everything.
"""
from sqlalchemy import inspect, text

from app.crypto import get_fernet
from app.database import Base, engine
from app import models  # noqa: F401  (registers every table with Base)


def main():
    get_fernet()
    if engine.dialect.name != "postgresql":
        raise SystemExit("This script is for the PostgreSQL database.")

    Base.metadata.create_all(engine)                     # only creates tables that are missing
    print("1. client_identities table: ready")

    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("predictions")}
        if "guideline_notice" not in columns:
            conn.execute(text("ALTER TABLE predictions ADD COLUMN guideline_notice TEXT"))
            print("2. predictions.guideline_notice: added")
        else:
            print("2. predictions.guideline_notice: already present")

        rule = conn.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_age' AND conrelid = 'assessments'::regclass")).scalar()
        if rule and "18" in rule:
            print("3. age rule (18-100): already present")
        else:
            conn.execute(text("ALTER TABLE assessments DROP CONSTRAINT IF EXISTS ck_age"))
            conn.execute(text("ALTER TABLE assessments ADD CONSTRAINT ck_age "
                              "CHECK (age BETWEEN 18 AND 100) NOT VALID"))
            print("3. age rule changed to 18-100 for new assessments")

    print("\nDone. Restart the server.")


if __name__ == "__main__":
    main()