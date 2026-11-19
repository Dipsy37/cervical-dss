"""UC05 Register Client, client look-up, UC11 View Client Record, UC12 Update / Remove Client Details."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import ClientOut, ClientRecordOut, ClientRegisterIn, ClientSummaryOut, ClientUpdateIn
from ..security import get_current_user, require_chw
from ..services import client_service

router = APIRouter(prefix="/api/clients", tags=["Clients"])


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def register_client(body: ClientRegisterIn, db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    """Registers a client and gives her a system-generated code (e.g. CL-00042).
    Date of birth (or an approximate age) is required; name, phone and village are optional
    and are saved, encrypted, only when identity_consent is true. Clients must be 18 or older."""
    client = client_service.register_client(db, chw, body)
    return client_service.to_client_out(client, chw)


@router.get("", response_model=list[ClientSummaryOut])
def list_clients(search: str | None = Query(None, max_length=100), chu_name: str | None = None,
                 limit: int = Query(100, ge=1, le=500),
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """CHW: the clients she registered (search by code or name). Administrator: all clients,
    initials only (search by code, filter by CHU)."""
    return client_service.list_clients(db, user, search, chu_name, limit)


@router.get("/{client_code}", response_model=ClientOut)
def find_client(client_code: str, db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    """Look up a returning client. Her full details are shown only to the CHW who registered her."""
    return client_service.to_client_out(client_service.find_client(db, client_code), chw)


@router.get("/{client_code}/record", response_model=ClientRecordOut)
def client_record(client_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The client's details and all her visits. CHW: own clients only (the view is logged).
    Administrator: any client, initials only, with the identity access log."""
    return client_service.client_record(db, user, client_code)


@router.patch("/{client_code}", response_model=ClientOut)
def update_client(client_code: str, body: ClientUpdateIn, db: Session = Depends(get_db),
                  chw: User = Depends(require_chw)):
    """Correct her details (registering CHW only). Send only the fields that change."""
    return client_service.update_client(db, chw, client_code, body)


@router.post("/{client_code}/remove-details", response_model=ClientOut)
def remove_details(client_code: str, db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    """She withdraws identity consent: name, phone and village are deleted. Her code, date of birth
    and assessments are kept."""
    return client_service.remove_details(db, chw, client_code)
