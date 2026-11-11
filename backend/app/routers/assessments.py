"""UC04 Conduct Risk Assessment, UC06 View Own History (CHW), UC10 View All Records (Admin)."""
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import AssessmentIn, AssessmentResultOut, AssessmentSummaryOut
from ..security import get_current_user, require_chw
from ..services import assessment_service

router = APIRouter(prefix="/api/assessments", tags=["Risk assessments"])


@router.post("", response_model=AssessmentResultOut, status_code=status.HTTP_201_CREATED)
def conduct_assessment(body: AssessmentIn, request: Request, db: Session = Depends(get_db),
                       chw: User = Depends(require_chw)):
    return assessment_service.submit_assessment(db, request.app.state.ml, chw, body)


@router.get("", response_model=list[AssessmentSummaryOut])
def list_assessments(client_code: str | None = None,
                     risk_level: str | None = Query(None, pattern="^(LOW|MODERATE|HIGH)$"),
                     chw_id: int | None = None, chu_name: str | None = None,
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """CHW: own assessments only. Administrator: all assessments, with optional filters."""
    return assessment_service.list_assessments(db, user, client_code, risk_level, chw_id, chu_name, limit, offset)


@router.get("/{assessment_id}", response_model=AssessmentResultOut)
def view_assessment(assessment_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    return assessment_service.get_assessment(db, user, assessment_id, request.app.state.ml.features)
