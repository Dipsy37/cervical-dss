from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import TEMP_PASSWORD_HOURS
from app.crypto import get_fernet
from app.database import Base, SessionLocal, engine
from app.models import Role, User
from app.security import generate_temporary_password, hash_password


def main():
    get_fernet()                     # stops here with a clear message if ENCRYPTION_KEY is missing
    Base.metadata.create_all(engine)
    print("Tables created (or already present): users, clients, client_identities, identity_access_log,\n"
          "  assessments, predictions, explanation_factors")

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.role == Role.ADMIN)):
            print("An Administrator account already exists - nothing else to do.")
            return
        temp = generate_temporary_password()
        db.add(User(full_name="System Administrator", username="admin", role=Role.ADMIN,
                    password_hash=hash_password(temp), must_change_password=True,
                    temp_password_expires_at=datetime.now() + timedelta(hours=TEMP_PASSWORD_HOURS)))
        db.commit()
    print("\nAdministrator account created")
    print("  username           : admin")
    print(f"  temporary password : {temp}")
    print(f"  (expires in {TEMP_PASSWORD_HOURS} hours; you will be asked to set a new password at first login)")


if __name__ == "__main__":
    main()