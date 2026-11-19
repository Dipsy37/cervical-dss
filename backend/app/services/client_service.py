"""
ClientService - UC05 Register Client, UC11 View Client Record, UC12 Update / Remove Client Details,
and the privacy rules for showing who a client is.

Privacy rules (Option B, role-based visibility):
  * The CHW who registered the client sees her full name, phone, village and date of birth.
  * Everyone else (the Administrator, other CHWs) sees initials and age only, e.g. "M. W., 34".
  * Name, phone and village are saved only with the client's identity consent.
  * Every time full details are shown on a client record, corrected or removed, the action is
    written to identity_access_log (the field names only, never the values).
"""
from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..crypto import mask_name
from ..models import Client, ClientIdentity, IdentityAccessLog, IdentityAction, RiskAssessment, Role, User
from ..schemas import (AccessLogOut, AssessmentSummaryOut, ClientOut, ClientRecordOut, ClientRegisterIn,
                       ClientSummaryOut, ClientUpdateIn)


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

# ---------------- UC11 / UC12: client records ----------------
def log_access(db: Session, client: Client, user: User, action: IdentityAction, detail: str | None = None) -> None:
    if client.identity is not None:
        db.add(IdentityAccessLog(client_id=client.client_id, user_id=user.user_id, action=action, detail=detail))


def own_client_or_403(client: Client, user: User) -> None:
    """A CHW may open, correct or remove details only for clients she registered."""
    if user.role == Role.CHW and client.registered_by != user.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only open the records of clients you registered.")


def list_clients(db: Session, user: User, search: str | None = None, chu_name: str | None = None,
                 limit: int = 100) -> list[ClientSummaryOut]:
    """CHW: the clients she registered. Administrator: all clients (initials only).
    Names are encrypted, so a name search is done after decrypting, on the CHW's own clients only."""
    q = (select(Client).options(joinedload(Client.identity),
                                selectinload(Client.assessments).joinedload(RiskAssessment.prediction))
         .order_by(Client.client_id.desc()))
    if user.role == Role.CHW:
        q = q.where(Client.registered_by == user.user_id)
    elif chu_name:
        q = q.where(Client.chu_name == chu_name)
    rows = []
    term = (search or "").strip().lower()
    for c in db.scalars(q).unique():
        name, masked = display_name(c, user)
        if term and term not in c.client_code.lower() and not (name and not masked and term in name.lower()):
            continue
        visits = sorted(c.assessments, key=lambda a: (a.assessed_at, a.assessment_id))
        last = visits[-1] if visits else None
        identity = c.identity
        rows.append(ClientSummaryOut(
            client_code=c.client_code, display_name=name, name_masked=masked,
            age=identity.age_on(date.today()) if identity else None,
            dob_estimated=identity.dob_estimated if identity else None,
            chu_name=c.chu_name, registered_at=c.created_at, visits=len(visits),
            last_assessed_at=last.assessed_at if last else None,
            last_risk_level=last.prediction.risk_level.value if last and last.prediction else None,
            details_removed=bool(identity and identity.details_removed_at and not identity.full_name)))
    rows.sort(key=lambda r: r.last_assessed_at or r.registered_at, reverse=True)
    return rows[:limit]


def client_record(db: Session, user: User, client_code: str) -> ClientRecordOut:
    client = find_client(db, client_code)
    own_client_or_403(client, user)
    out = to_client_out(client, user)
    if can_see_identity(client, user):
        log_access(db, client, user, IdentityAction.VIEW)
        db.commit()
    visits = sorted(client.assessments, key=lambda a: (a.assessed_at, a.assessment_id), reverse=True)
    record = ClientRecordOut(
        client=out, registered_by=db.get(User, client.registered_by).full_name,
        details_removed_at=client.identity.details_removed_at if client.identity else None,
        visits=[AssessmentSummaryOut(assessment_id=a.assessment_id, assessed_at=a.assessed_at,
                                     client_code=client.client_code, client_name=out.display_name,
                                     chw_name=a.chw.full_name, chu_name=client.chu_name,
                                     risk_level=a.prediction.risk_level.value,
                                     probability=float(a.prediction.probability))
                for a in visits if a.prediction is not None])
    if user.role == Role.ADMIN and client.identity is not None:
        record.access_log = [AccessLogOut(accessed_at=e.accessed_at, user_name=e.user.full_name,
                                          action=e.action.value, detail=e.detail)
                             for e in client.identity.access_log]
    return record


def _identity_for_change(db: Session, user: User, client_code: str) -> Client:
    client = find_client(db, client_code)
    if user.role != Role.CHW:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the CHW who registered the client can change her details.")
    own_client_or_403(client, user)
    if client.identity is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Client {client.client_code} was registered before dates of birth were recorded. "
                            "Register her again as a new client.")
    return client


def update_client(db: Session, user: User, client_code: str, data: ClientUpdateIn) -> ClientOut:
    client = _identity_for_change(db, user, client_code)
    identity = client.identity
    sent = data.model_fields_set
    changed = []

    if "identity_consent" in sent and data.identity_consent is not None \
            and data.identity_consent != identity.identity_consent:
        if not data.identity_consent:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "To withdraw identity consent, use Remove personal details.")
        identity.identity_consent = True
        identity.consent_recorded_at = datetime.now()
        changed.append("identity consent")

    personal = [f for f in ("full_name", "phone", "village") if f in sent]
    if any(getattr(data, f) for f in personal) and not identity.identity_consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Name, phone and village can only be recorded if the client agrees. "
                            "Tick the identity consent box first.")
    for f in personal:
        if getattr(identity, f) != getattr(data, f):
            setattr(identity, f, getattr(data, f))
            changed.append(f.replace("_", " "))

    if data.date_of_birth is not None and (data.date_of_birth != identity.date_of_birth or identity.dob_estimated):
        identity.date_of_birth, identity.dob_estimated = data.date_of_birth, False
        changed.append("date of birth")
    elif data.estimated_age is not None:
        identity.date_of_birth, identity.dob_estimated = dob_from_estimated_age(data.estimated_age), True
        changed.append("date of birth (approximate)")

    if changed:
        log_access(db, client, user, IdentityAction.UPDATE, ", ".join(changed))
        db.commit()
    return to_client_out(client, user)


def remove_details(db: Session, user: User, client_code: str) -> ClientOut:
    """The client withdraws identity consent: her name, phone and village are deleted.
    Her date of birth stays (her age is needed for future assessments) and so do her
    assessments, which were never linked to her name."""
    client = _identity_for_change(db, user, client_code)
    identity = client.identity
    identity.full_name = identity.phone = identity.village = None
    identity.identity_consent = False
    identity.consent_recorded_at = None
    identity.details_removed_at = datetime.now()
    log_access(db, client, user, IdentityAction.REMOVE, "name, phone, village")
    db.commit()
    return to_client_out(client, user)
