"""UC01 Log In, UC02 Change Password, UC03 Log Out (client discards the token)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn, MeOut, TokenOut
from ..security import (create_access_token, get_current_user, get_user_allow_password_change, hash_password,
                        password_problem, verify_password)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password.")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated. Contact the Administrator.")
    if user.must_change_password and user.temp_password_expires_at and user.temp_password_expires_at < datetime.now():
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Your temporary password has expired. Ask the Administrator to reset it.")
    user.last_login = datetime.now()
    db.commit()
    return TokenOut(access_token=create_access_token(user), role=user.role.value, full_name=user.full_name,
                    must_change_password=user.must_change_password)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordIn, user: User = Depends(get_user_allow_password_change),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different from the current one.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.temp_password_expires_at = None
    db.commit()


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return MeOut(user_id=user.user_id, full_name=user.full_name, username=user.username,
                 role=user.role.value, chu_name=user.chu_name)
