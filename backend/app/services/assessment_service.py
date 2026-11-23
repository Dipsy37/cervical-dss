"""
AssessmentService - the core use case "Conduct Risk Assessment".
Implements the sequence diagram: preprocess -> predict -> explain -> classify -> save.
"""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..ml.inference import MLModule
from ..models import Client, ExplanationFactor, Prediction, RiskAssessment, RiskLevel, Role, User
from ..schemas import AssessmentIn, AssessmentResultOut, AssessmentSummaryOut, FactorOut


def submit_assessment(db: Session, ml: MLModule, chw: User, data: AssessmentIn) -> AssessmentResultOut:
    client = db.scalar(select(Client).where(Client.client_code == data.client_code))
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client {data.client_code} not found.")

    features = data.model_dump(include=set(ml.features))

    # 1-4: inference (model, preprocessor and explainer are already in memory)
    vector = ml.preprocessor.transform(features)
    probability = ml.predictor.predict_probability(vector)
    factors = ml.explainer.explain(vector, features)
    level = ml.rules.classify(probability)
    message = ml.rules.get_referral(level)

    # 5: save assessment + prediction + explanation factors in ONE transaction
    assessment = RiskAssessment(client_id=client.client_id, chw_id=chw.user_id,
                                consent_obtained=data.consent_obtained, **features)
    assessment.prediction = Prediction(
        probability=round(probability, 4), risk_level=RiskLevel(level), referral_message=message,
        model_version=ml.predictor.get_model_version(),
        factors=[ExplanationFactor(feature_name=f.feature_name, feature_value=f.feature_value,
                                   shap_value=f.shap_value, rank=f.rank,
                                   plain_language_text=f.plain_language_text) for f in factors],
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return to_result(assessment, ml.features)


def to_result(a: RiskAssessment, feature_names: list[str]) -> AssessmentResultOut:
    p = a.prediction
    answers = {k: (float(v) if v is not None and not isinstance(v, bool) else v)
               for k, v in a.to_feature_dict(feature_names).items()}
    return AssessmentResultOut(
        assessment_id=a.assessment_id, client_code=a.client.client_code, assessed_at=a.assessed_at,
        chw_name=a.chw.full_name, risk_level=p.risk_level.value, probability=float(p.probability),
        referral_message=p.referral_message, model_version=p.model_version,
        top_factors=[FactorOut.model_validate(f) for f in p.factors], answers=answers)


def get_assessment(db: Session, user: User, assessment_id: int, feature_names: list[str]) -> AssessmentResultOut:
    a = db.get(RiskAssessment, assessment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found.")
    if user.role == Role.CHW and a.chw_id != user.user_id:  # CHWs see only their own records
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only view your own assessments.")
    return to_result(a, feature_names)


def list_assessments(db: Session, user: User, client_code: str | None = None, risk_level: str | None = None,
                     chw_id: int | None = None, chu_name: str | None = None,
                     limit: int = 50, offset: int = 0) -> list[AssessmentSummaryOut]:
    q = (select(RiskAssessment).join(RiskAssessment.prediction).join(RiskAssessment.client)
         .options(joinedload(RiskAssessment.prediction), joinedload(RiskAssessment.client),
                  joinedload(RiskAssessment.chw))
         .order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.assessment_id.desc()))
    if user.role == Role.CHW:
        q = q.where(RiskAssessment.chw_id == user.user_id)
    elif chw_id:
        q = q.where(RiskAssessment.chw_id == chw_id)
    if client_code:
        q = q.where(Client.client_code == client_code.strip().upper())
    if risk_level:
        q = q.where(Prediction.risk_level == RiskLevel(risk_level))
    if chu_name:
        q = q.where(Client.chu_name == chu_name)
    rows = db.scalars(q.limit(limit).offset(offset)).unique().all()
    return [AssessmentSummaryOut(assessment_id=a.assessment_id, assessed_at=a.assessed_at,
                                 client_code=a.client.client_code, chw_name=a.chw.full_name,
                                 chu_name=a.client.chu_name, risk_level=a.prediction.risk_level.value,
                                 probability=float(a.prediction.probability)) for a in rows]
