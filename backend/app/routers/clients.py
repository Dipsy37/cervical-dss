"""UC05 Register Client (pseudonymous) and client look-up (CHW only)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Client, User
from ..schemas import ClientOut
from ..security import require_chw

router = APIRouter(prefix="/api/clients", tags=["Clients (CHW)"])


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def register_client(db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    """Creates a client with a system-generated code (e.g. CL-00042). No personal details are stored."""
    client = Client(client_code="PENDING", chu_name=chw.chu_name or "Unknown", registered_by=chw.user_id)
    db.add(client)
    db.flush()                                  # obtains client_id
    client.client_code = f"CL-{client.client_id:05d}"
    db.commit()
    return client


@router.get("/{client_code}", response_model=ClientOut)
def find_client(client_code: str, db: Session = Depends(get_db), chw: User = Depends(require_chw)):
    client = db.scalar(select(Client).where(Client.client_code == client_code.strip().upper()))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client {client_code} not found.")
    return client
