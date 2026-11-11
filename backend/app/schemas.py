"""
Pydantic schemas: validate every request BEFORE it reaches the model.
Invalid input -> HTTP 422 with field-level messages (sequence diagram, alt branch).
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


# ---------- clients ----------
class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    client_id: int
    client_code: str
    chu_name: str
    created_at: datetime


# ---------- assessments ----------
class AssessmentIn(BaseModel):
    """The 12 risk factors. Any factor may be None = client declined / did not know."""
    client_code: str = Field(pattern=r"^CL-\d{5}$")
    consent_obtained: bool
    age: int | None = Field(None, ge=13, le=100)
    num_sexual_partners: int | None = Field(None, ge=0, le=50)
    age_first_intercourse: int | None = Field(None, ge=8, le=60)
    num_pregnancies: int | None = Field(None, ge=0, le=20)
    smokes: bool | None = None
    smokes_years: float | None = Field(None, ge=0, le=80)
    hormonal_contraceptives: bool | None = None
    hormonal_contraceptives_years: float | None = Field(None, ge=0, le=40)
    iud: bool | None = None
    iud_years: float | None = Field(None, ge=0, le=40)
    stds: bool | None = None
    stds_number: int | None = Field(None, ge=0, le=20)

    @field_validator("consent_obtained")
    @classmethod
    def consent_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Verbal consent must be obtained before an assessment is recorded.")
        return v

    @model_validator(mode="after")
    def check_consistency(self):
        # Years / counts only make sense when the yes/no answer is Yes: set them to 0 when No.
        for flag, amount in [("smokes", "smokes_years"), ("hormonal_contraceptives", "hormonal_contraceptives_years"),
                             ("iud", "iud_years"), ("stds", "stds_number")]:
            if getattr(self, flag) is False:
                setattr(self, amount, 0)
        if self.age is not None:
            if self.age_first_intercourse is not None and self.age_first_intercourse > self.age:
                raise ValueError("Age at first intercourse cannot be greater than current age.")
            for f in ["smokes_years", "hormonal_contraceptives_years", "iud_years"]:
                v = getattr(self, f)
                if v is not None and v > self.age:
                    raise ValueError(f"{f.replace('_', ' ')} cannot be greater than current age.")
        return self


class FactorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    rank: int
    feature_name: str
    feature_value: str | None
    shap_value: float
    plain_language_text: str


class AssessmentResultOut(BaseModel):
    assessment_id: int
    client_code: str
    assessed_at: datetime
    chw_name: str
    risk_level: str
    probability: float
    referral_message: str
    model_version: str
    top_factors: list[FactorOut]
    answers: dict
    disclaimer: str = "This is a risk estimate to guide referral. It is NOT a diagnosis."


class AssessmentSummaryOut(BaseModel):
    assessment_id: int
    assessed_at: datetime
    client_code: str
    chw_name: str
    chu_name: str
    risk_level: str
    probability: float
