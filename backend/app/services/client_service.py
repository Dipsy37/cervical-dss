"""
ClientService - UC05 Register Client and the privacy rules for showing who a client is.

Privacy rules (Option B, role-based visibility):
  * The CHW who registered the client sees her full name, phone, village and date of birth.
  * Everyone else (the Administrator, other CHWs) sees initials and age only, e.g. "M. W., 34".
  * Name, phone and village are saved only with the client's identity consent.
"""
from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto import mask_name
from ..models import Client, ClientIdentity, Role, User
from ..schemas import ClientOut, ClientRegisterIn


def dob_from_estimated_age(age: int, today: date | None = None) -> date:
    """Approximate date of birth that makes the client exactly `age` today."""
    today = today or date.today()
    try:
        return today.replace(year=today.year - age)
    except ValueError:                       # 29 February in a non-leap year
        return today.replace(year=today.year - age, day=28)


def register_client(db: Session, chw: User, data: ClientRegisterIn) -> Client:
    estimated = data.date_of_birth is None
    client = Client(client_code="PENDING", chu_name=chw.chu_name or "Unknown", registered_by=chw.user_id)
    client.identity = ClientIdentity(
        date_of_birth=dob_from_estimated_age(data.estimated_age) if estimated else data.date_of_birth,
        dob_estimated=estimated,
        identity_consent=data.identity_consent,
        consent_recorded_at=datetime.now() if data.identity_consent else None,
        full_name=data.full_name, phone=data.phone, village=data.village,
    )
    db.add(client)
    db.flush()                                  # obtains client_id
    client.client_code = f"CL-{client.client_id:05d}"
    db.commit()
    return client


def find_client(db: Session, client_code: str) -> Client:
    client = db.scalar(select(Client).where(Client.client_code == client_code.strip().upper()))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client {client_code} not found.")
    return client


def can_see_identity(client: Client, viewer: User) -> bool:
    return viewer.role == Role.CHW and client.registered_by == viewer.user_id


def display_name(client: Client, viewer: User) -> tuple[str | None, bool]:
    """Returns (name to show, whether it was masked)."""
    identity = client.identity
    if identity is None or not identity.full_name:
        return None, False
    if can_see_identity(client, viewer):
        return identity.full_name, False
    return mask_name(identity.full_name), True


def to_client_out(client: Client, viewer: User) -> ClientOut:
    name, masked = display_name(client, viewer)
    out = ClientOut(client_id=client.client_id, client_code=client.client_code, chu_name=client.chu_name,
                    created_at=client.created_at, display_name=name, name_masked=masked)
    identity = client.identity
    if identity is not None:
        out.has_date_of_birth = True
        out.age = identity.age_on(date.today())
        out.dob_estimated = identity.dob_estimated
        if can_see_identity(client, viewer):
            out.date_of_birth = identity.date_of_birth
            out.phone, out.village = identity.phone, identity.village
    return out