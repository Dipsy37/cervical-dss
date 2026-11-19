"""UC05 Register Client and client look-up (CHW only)."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import ClientOut, ClientRegisterIn
from ..security import require_chw
from ..services import client_service

router = APIRouter(prefix="/api/clients", tags=["Clients (CHW)"])


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def register_client(body: ClientRegisterIn, db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    """Registers a client and gives her a system-generated code (e.g. CL-00042).
    Date of birth (or an approximate age) is required; name, phone and village are optional
    and are saved, encrypted, only when identity_consent is true. Clients must be 18 or older."""
    client = client_service.register_client(db, chw, body)
    return client_service.to_client_out(client, chw)


@router.get("/{client_code}", response_model=ClientOut)
def find_client(client_code: str, db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    """Look up a returning client. Her full details are shown only to the CHW who registered her."""
    return client_service.to_client_out(client_service.find_client(db, client_code), chw)