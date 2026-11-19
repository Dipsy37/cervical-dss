"""
AssessmentService - the core use case "Conduct Risk Assessment".
Implements the sequence diagram: preprocess -> predict -> explain -> classify -> save.
"""
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..ml.inference import MLModule
from ..models import Client, ExplanationFactor, Prediction, RiskAssessment, RiskLevel, Role, User
from ..schemas import MIN_CLIENT_AGE, AssessmentIn, AssessmentResultOut, AssessmentSummaryOut, FactorOut
from .client_service import display_name, find_client


def age_at_visit(client: Client, today: date | None = None) -> int:
    """Age is never typed in: it is calculated from the date of birth on the day of the visit."""
    if client.identity is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Client {client.client_code} was registered before dates of birth were recorded. "
                            "Register her again as a new client so that her age can be calculated.")
    age = client.identity.age_on(today or date.today())
    if age < MIN_CLIENT_AGE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"The client must be {MIN_CLIENT_AGE} years or older (she is {age}).")
    return age


def check_against_age(features: dict, age: int) -> None:
    """Answers that cannot be larger than her age (previously checked on the form)."""
    problems = []
    first = features.get("age_first_intercourse")
    if first is not None and first > age:
        problems.append(f"Age at first intercourse ({first}) cannot be greater than her age ({age}).")
    for name, label in [("smokes_years", "Years smoking"),
                        ("hormonal_contraceptives_years", "Years using hormonal contraceptives"),
                        ("iud_years", "Years with an IUD")]:
        v = features.get(name)
        if v is not None and v > age:
            problems.append(f"{label} ({v:g}) cannot be greater than her age ({age}).")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))


def submit_assessment(db: Session, ml: MLModule, chw: User, data: AssessmentIn) -> AssessmentResultOut:
    client = find_client(db, data.client_code)
    age = age_at_visit(client)

    features = data.model_dump(include=set(ml.features))
    features["age"] = age
    check_against_age(features, age)

    # 1-4: inference (model, preprocessor and explainer are already in memory)
    vector = ml.preprocessor.transform(features)
    probability = ml.predictor.predict_probability(vector)
    factors = ml.explainer.explain(vector, features)
    level = ml.rules.classify(probability)
    message = ml.rules.get_referral(level)
    notice = ml.rules.get_age_notice(age)

    # 5: save assessment + prediction + explanation factors in ONE transaction
    assessment = RiskAssessment(client_id=client.client_id, chw_id=chw.user_id,
                                consent_obtained=data.consent_obtained, **features)
    assessment.prediction = Prediction(
        probability=round(probability, 4), risk_level=RiskLevel(level), referral_message=message,
        model_version=ml.predictor.get_model_version(), guideline_notice=notice,
        factors=[ExplanationFactor(feature_name=f.feature_name, feature_value=f.feature_value,
                                   shap_value=f.shap_value, rank=f.rank,
                                   plain_language_text=f.plain_language_text) for f in factors],
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return to_result(assessment, ml.features, chw)


def to_result(a: RiskAssessment, feature_names: list[str], viewer: User) -> AssessmentResultOut:
    p = a.prediction
    answers = {k: (float(v) if v is not None and not isinstance(v, bool) else v)
               for k, v in a.to_feature_dict(feature_names).items()}
    identity = a.client.identity
    return AssessmentResultOut(
        assessment_id=a.assessment_id, client_code=a.client.client_code,
        client_name=display_name(a.client, viewer)[0], age=a.age,
        age_estimated=identity.dob_estimated if identity else None, assessed_at=a.assessed_at,
        chw_name=a.chw.full_name, risk_level=p.risk_level.value, probability=float(p.probability),
        referral_message=p.referral_message, model_version=p.model_version,
        guideline_notice=p.guideline_notice,
        top_factors=[FactorOut.model_validate(f) for f in p.factors], answers=answers)


def get_assessment(db: Session, user: User, assessment_id: int, feature_names: list[str]) -> AssessmentResultOut:
    a = db.get(RiskAssessment, assessment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found.")
    if user.role == Role.CHW and a.chw_id != user.user_id:  # CHWs see only their own records
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only view your own assessments.")
    return to_result(a, feature_names, user)


def list_assessments(db: Session, user: User, client_code: str | None = None, risk_level: str | None = None,
                     chw_id: int | None = None, chu_name: str | None = None,
                     limit: int = 50, offset: int = 0) -> list[AssessmentSummaryOut]:
    q = (select(RiskAssessment).join(RiskAssessment.prediction).join(RiskAssessment.client)
         .options(joinedload(RiskAssessment.prediction),
                  joinedload(RiskAssessment.client).joinedload(Client.identity),
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
                                 client_code=a.client.client_code,
                                 client_name=display_name(a.client, user)[0], chw_name=a.chw.full_name,
                                 chu_name=a.client.chu_name, risk_level=a.prediction.risk_level.value,
                                 probability=float(a.prediction.probability)) for a in rows]