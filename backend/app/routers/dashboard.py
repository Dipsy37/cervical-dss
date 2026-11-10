"""Dashboard summary figures. Administrator: whole system. CHW: own work only."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Client, Prediction, RiskAssessment, Role, User
from ..security import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
LEVELS = ["LOW", "MODERATE", "HIGH"]
DAYS = 14


@router.get("/summary")
def summary(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    is_chw = user.role == Role.CHW
    scope = (lambda q: q.where(RiskAssessment.chw_id == user.user_id)) if is_chw else (lambda q: q)

    total = db.scalar(scope(select(func.count(RiskAssessment.assessment_id)))) or 0
    clients = db.scalar(scope(select(func.count(func.distinct(RiskAssessment.client_id))))) or 0

    by_level = dict.fromkeys(LEVELS, 0)
    for level, n in db.execute(scope(select(Prediction.risk_level, func.count())
                                     .join(RiskAssessment, Prediction.assessment_id == RiskAssessment.assessment_id)
                                     .group_by(Prediction.risk_level))):
        by_level[level.value] = n

    # Assessments per day for the last 14 days (including days with none)
    start = date.today() - timedelta(days=DAYS - 1)
    counts = {}
    rows = db.execute(scope(select(RiskAssessment.assessed_at)
                            .where(RiskAssessment.assessed_at >= datetime.combine(start, datetime.min.time()))))
    for (ts,) in rows:
        counts[ts.date()] = counts.get(ts.date(), 0) + 1
    per_day = [{"date": (start + timedelta(days=i)).isoformat(), "count": counts.get(start + timedelta(days=i), 0)}
               for i in range(DAYS)]

    result = {"role": user.role.value, "total_assessments": total, "clients_assessed": clients,
              "by_level": by_level, "per_day": per_day}

    if not is_chw:
        result["active_chws"] = db.scalar(select(func.count()).where(User.role == Role.CHW, User.is_active)) or 0
        by_chu = {}
        for chu, level, n in db.execute(
                select(Client.chu_name, Prediction.risk_level, func.count())
                .join(RiskAssessment, RiskAssessment.client_id == Client.client_id)
                .join(Prediction, Prediction.assessment_id == RiskAssessment.assessment_id)
                .group_by(Client.chu_name, Prediction.risk_level)):
            by_chu.setdefault(chu, dict.fromkeys(LEVELS, 0))[level.value] = n
        result["by_chu"] = [{"chu_name": k, **v, "total": sum(v.values())}
                            for k, v in sorted(by_chu.items(), key=lambda kv: -sum(kv[1].values()))]
        cfg = request.app.state.ml.config
        result["model"] = {
            "version": cfg["model_version"], "trained_on": cfg.get("trained_on"),
            "thresholds": cfg["thresholds"], "imbalance_method": cfg.get("imbalance_method"),
            "test_auc": cfg.get("test_metrics_default_threshold", {}).get("AUC-ROC"),
            "referral_sensitivity": cfg.get("test_metrics_referral_threshold_t1", {}).get("Sensitivity (recall)"),
        }
    return result
