"""
Pydantic schemas: validate every request before it is processed.
Invalid input -> HTTP 422 with field-level messages.
(Assessment and client schemas are added with the risk assessment module.)
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- auth ----------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    must_change_password: bool


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=128)


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    full_name: str
    username: str
    role: str
    chu_name: str | None


# ---------- users (admin) ----------
class RegisterCHWIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=100)
    phone: str = Field(pattern=r"^(\+254|0)[17]\d{8}$", description="Kenyan mobile, e.g. 0712345678")
    chu_name: str = Field(min_length=2, max_length=100)


class CredentialsOut(BaseModel):
    user_id: int
    username: str
    temporary_password: str
    expires_at: datetime
    message: str = "Shown once only. Hand these details to the CHW in person."


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    full_name: str
    username: str
    phone: str | None
    role: str
    chu_name: str | None
    is_active: bool
    last_login: datetime | None
