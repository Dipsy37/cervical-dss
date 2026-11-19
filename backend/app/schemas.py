"""
Pydantic schemas: validate every request BEFORE it reaches the model.
Invalid input -> HTTP 422 with field-level messages (sequence diagram, alt branch).
"""
from datetime import date, datetime

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
MIN_CLIENT_AGE, MAX_CLIENT_AGE = 18, 100
KENYAN_MOBILE = r"^(\+254|0)[17]\d{8}$"


def age_on(dob: date, day: date) -> int:
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


class ClientRegisterIn(BaseModel):
    """UC05 Register Client. Date of birth (or an approximate age) is required: the model
    needs age and it is calculated from this at every visit. Name, phone and village are
    optional and may only be saved when the client agrees (identity_consent)."""
    date_of_birth: date | None = Field(None, description="Exact date of birth, if known")
    estimated_age: int | None = Field(None, ge=MIN_CLIENT_AGE, le=MAX_CLIENT_AGE,
                                      description="Use ONLY when the exact date of birth is not known")
    identity_consent: bool = Field(False, description="Client agrees to her name/phone/village being recorded")
    full_name: str | None = Field(None, min_length=2, max_length=100)
    phone: str | None = Field(None, pattern=KENYAN_MOBILE, description="Kenyan mobile, e.g. 0712345678")
    village: str | None = Field(None, min_length=2, max_length=100)

    @field_validator("full_name", "village", "phone", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        if isinstance(v, str):
            v = " ".join(v.split())          # trim and collapse extra spaces
            return v or None
        return v

    @model_validator(mode="after")
    def check_rules(self):
        if (self.date_of_birth is None) == (self.estimated_age is None):
            raise ValueError("Give either the date of birth or, if it is not known, an approximate age.")
        if self.date_of_birth is not None:
            today = date.today()
            if self.date_of_birth > today:
                raise ValueError("Date of birth cannot be in the future.")
            age = age_on(self.date_of_birth, today)
            if age < MIN_CLIENT_AGE:
                raise ValueError(f"The client must be {MIN_CLIENT_AGE} years or older (she is {age}).")
            if age > MAX_CLIENT_AGE:
                raise ValueError("Please check the date of birth (age over 100).")
        if not self.identity_consent and any([self.full_name, self.phone, self.village]):
            raise ValueError("Name, phone and village can only be recorded if the client agrees. "
                             "Tick the identity consent box or leave these fields empty.")
        return self


class ClientOut(BaseModel):
    """What a user may see about a client. The CHW who registered the client sees her full
    details; anyone else (e.g. the Administrator) sees initials and age only."""
    client_id: int
    client_code: str
    chu_name: str
    created_at: datetime
    display_name: str | None = None        # "Mary Wanjiru", or "M. W." when masked, or None
    name_masked: bool = False
    age: int | None = None                 # today, calculated from date of birth
    dob_estimated: bool | None = None
    date_of_birth: date | None = None      # only for the registering CHW
    phone: str | None = None               # only for the registering CHW
    village: str | None = None             # only for the registering CHW
    has_date_of_birth: bool = False        # False = registered before DOB was recorded


# ---------- assessments ----------
class AssessmentIn(BaseModel):
    """11 of the 12 risk factors. Age is NOT entered: it is calculated from the client's date
    of birth on the day of the visit. Any factor may be None = client declined / did not know.
    Answers that depend on age (e.g. age at first intercourse) are checked in the service."""
    client_code: str = Field(pattern=r"^CL-\d{5}$")
    consent_obtained: bool
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
    client_name: str | None = None         # full name or initials, depending on who is viewing
    age: int | None = None                 # age on the day of the assessment
    age_estimated: bool | None = None
    assessed_at: datetime
    chw_name: str
    risk_level: str
    probability: float
    referral_message: str
    model_version: str
    guideline_notice: str | None = None
    top_factors: list[FactorOut]
    answers: dict
    disclaimer: str = "This is a risk estimate to guide referral. It is NOT a diagnosis."


class AssessmentSummaryOut(BaseModel):
    assessment_id: int
    assessed_at: datetime
    client_code: str
    client_name: str | None = None
    chw_name: str
    chu_name: str
    risk_level: str
    probability: float