"""Authentication helpers: password hashing (bcrypt), JWT tokens, role checks."""
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import SECRET_KEY, TOKEN_EXPIRE_MINUTES
from .database import get_db
from .models import Role, User

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def generate_temporary_password(length: int = 10) -> str:
    """e.g. 'K7m-29Qxa4' - letters and digits, always contains a digit."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd):
            return pwd


def password_problem(password: str) -> str | None:
    """Returns a message if the password breaks the rules, otherwise None."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"\d", password) or not re.search(r"[A-Za-z]", password):
        return "Password must contain both letters and at least one number."
    return None


# ---------- tokens ----------
def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.user_id),
        "role": user.role.value,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _user_from_token(credentials: HTTPAuthorizationCredentials | None, db: Session) -> User:
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in or session expired.",
                                 headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorised
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise unauthorised
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorised
    return user


def get_user_allow_password_change(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    """Used ONLY by the change-password endpoint."""
    return _user_from_token(credentials, db)


def get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    """Every other endpoint: the user must have replaced their temporary password."""
    user = _user_from_token(credentials, db)
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You must set a new password first.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access only.")
    return user


def require_chw(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.CHW:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Community Health Worker access only.")
    return user
