"""UC07 Register CHW, UC08 Deactivate CHW, UC09 Reset CHW Password (Administrator only)."""
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import TEMP_PASSWORD_HOURS
from ..database import get_db
from ..models import Role, User
from ..schemas import CredentialsOut, RegisterCHWIn, UserOut
from ..security import generate_temporary_password, hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["CHW accounts (Administrator)"])


def _make_username(db: Session, full_name: str) -> str:
    """'Jane Wanjiru' -> 'jwanjiru', then 'jwanjiru2', 'jwanjiru3' ... if taken."""
    parts = re.sub(r"[^a-z ]", "", full_name.lower()).split()
    base = (parts[0][0] + parts[-1]) if len(parts) > 1 else parts[0]
    base = base[:45]
    candidate, n = base, 1
    while db.scalar(select(User).where(User.username == candidate)):
        n += 1
        candidate = f"{base}{n}"
    return candidate


def _issue_temp_password(user: User) -> tuple[str, datetime]:
    temp = generate_temporary_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.temp_password_expires_at = datetime.now() + timedelta(hours=TEMP_PASSWORD_HOURS)
    return temp, user.temp_password_expires_at


def _out(u: User) -> UserOut:
    return UserOut(user_id=u.user_id, full_name=u.full_name, username=u.username, phone=u.phone,
                   role=u.role.value, chu_name=u.chu_name, is_active=u.is_active, last_login=u.last_login)


def _get_chw(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.role != Role.CHW:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CHW account not found.")
    return user


@router.get("", response_model=list[UserOut])
def list_chws(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    users = db.scalars(select(User).where(User.role == Role.CHW).order_by(User.full_name)).all()
    return [_out(u) for u in users]


@router.post("", response_model=CredentialsOut, status_code=status.HTTP_201_CREATED)
def register_chw(body: RegisterCHWIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    phone = body.phone.replace("+254", "0")
    if db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this phone number already exists.")
    user = User(full_name=body.full_name.strip(), username=_make_username(db, body.full_name), phone=phone,
                role=Role.CHW, chu_name=body.chu_name.strip(), created_by=admin.user_id, password_hash="")
    temp, expires = _issue_temp_password(user)
    db.add(user)
    db.commit()
    return CredentialsOut(user_id=user.user_id, username=user.username, temporary_password=temp, expires_at=expires)


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate_chw(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = _get_chw(db, user_id)
    user.is_active = False          # never deleted: past assessments keep a valid owner
    db.commit()
    return _out(user)


@router.post("/{user_id}/reactivate", response_model=UserOut)
def reactivate_chw(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = _get_chw(db, user_id)
    user.is_active = True
    db.commit()
    return _out(user)


@router.post("/{user_id}/reset-password", response_model=CredentialsOut)
def reset_password(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = _get_chw(db, user_id)
    temp, expires = _issue_temp_password(user)
    db.commit()
    return CredentialsOut(user_id=user.user_id, username=user.username, temporary_password=temp, expires_at=expires)
