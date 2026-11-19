"""
Domain classes (ORM). These map one-to-one to the tables in the database
schema (database/schema.sql) and to the domain classes in the class diagram.

SQLAlchemy generates the attribute access (getters/setters) for each mapped
column; read-only rules (e.g. a Prediction never changes once saved) are
enforced in the service layer, which never updates those rows.
"""
import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .crypto import EncryptedDate, EncryptedString
from .database import Base


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    CHW = "CHW"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class IdentityAction(str, enum.Enum):
    VIEW = "VIEW"        # a client's full personal details were shown
    UPDATE = "UPDATE"    # personal details were corrected
    REMOVE = "REMOVE"    # identity consent withdrawn: name, phone and village deleted


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(15), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), nullable=False)
    chu_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    temp_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime)

    assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="chw")


class Client(Base):
    """Pseudonymous record of a woman assessed. Her personal details are kept apart,
    encrypted, in ClientIdentity, so health data never sits next to a name."""
    __tablename__ = "clients"

    client_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    chu_name: Mapped[str] = mapped_column(String(100), nullable=False)
    registered_by: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="client")
    identity: Mapped["ClientIdentity | None"] = relationship(
        back_populates="client", uselist=False, cascade="all, delete-orphan")


class ClientIdentity(Base):
    """Who the client is. Every personal field is encrypted in the database.
    Date of birth is required (age is calculated from it at each assessment);
    name, phone and village are optional and saved only with the client's consent."""
    __tablename__ = "client_identities"

    client_id: Mapped[int] = mapped_column(ForeignKey("clients.client_id"), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(EncryptedString)
    phone: Mapped[str | None] = mapped_column(EncryptedString)
    village: Mapped[str | None] = mapped_column(EncryptedString)
    date_of_birth: Mapped[date] = mapped_column(EncryptedDate, nullable=False)
    dob_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    identity_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    details_removed_at: Mapped[datetime | None] = mapped_column(DateTime)

    client: Mapped[Client] = relationship(back_populates="identity")
    access_log: Mapped[list["IdentityAccessLog"]] = relationship(
        back_populates="identity", order_by="IdentityAccessLog.log_id.desc()",
        cascade="all, delete-orphan")

    def age_on(self, day: date) -> int:
        """Age in completed years on the given day."""
        dob = self.date_of_birth
        return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


class IdentityAccessLog(Base):
    """Audit trail: who saw or changed a client's personal details, and when.
    Records the action and the names of the fields changed, never the values themselves."""
    __tablename__ = "identity_access_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("client_identities.client_id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    action: Mapped[IdentityAction] = mapped_column(Enum(IdentityAction, name="identity_action"), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(200))     # e.g. "phone, village"
    accessed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    identity: Mapped[ClientIdentity] = relationship(back_populates="access_log")
    user: Mapped[User] = relationship()


class RiskAssessment(Base):
    """One visit. Holds the 12 model inputs; NULL = client declined / did not know.
    Age is calculated from the client's date of birth on the day of the visit and stored here."""
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint("consent_obtained = TRUE", name="ck_consent"),
        CheckConstraint("age BETWEEN 18 AND 100", name="ck_age"),
        CheckConstraint("num_sexual_partners >= 0", name="ck_partners"),
        CheckConstraint("age_first_intercourse BETWEEN 8 AND 60", name="ck_first_intercourse"),
        CheckConstraint("num_pregnancies >= 0", name="ck_pregnancies"),
        CheckConstraint("smokes_years >= 0", name="ck_smokes_years"),
        CheckConstraint("hormonal_contraceptives_years >= 0", name="ck_hc_years"),
        CheckConstraint("iud_years >= 0", name="ck_iud_years"),
        CheckConstraint("stds_number >= 0", name="ck_stds_number"),
    )

    assessment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.client_id"), nullable=False, index=True)
    chw_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    consent_obtained: Mapped[bool] = mapped_column(Boolean, nullable=False)
    age: Mapped[int | None] = mapped_column(SmallInteger)
    num_sexual_partners: Mapped[int | None] = mapped_column(SmallInteger)
    age_first_intercourse: Mapped[int | None] = mapped_column(SmallInteger)
    num_pregnancies: Mapped[int | None] = mapped_column(SmallInteger)
    smokes: Mapped[bool | None] = mapped_column(Boolean)
    smokes_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    hormonal_contraceptives: Mapped[bool | None] = mapped_column(Boolean)
    hormonal_contraceptives_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    iud: Mapped[bool | None] = mapped_column(Boolean)
    iud_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    stds: Mapped[bool | None] = mapped_column(Boolean)
    stds_number: Mapped[int | None] = mapped_column(SmallInteger)

    client: Mapped[Client] = relationship(back_populates="assessments")
    chw: Mapped[User] = relationship(back_populates="assessments")
    prediction: Mapped["Prediction"] = relationship(back_populates="assessment", uselist=False)

    def to_feature_dict(self, feature_names: list[str]) -> dict:
        return {name: getattr(self, name) for name in feature_names}


class Prediction(Base):
    """Model output + referral rule result. Read-only once saved (audit record)."""
    __tablename__ = "predictions"
    __table_args__ = (CheckConstraint("probability BETWEEN 0 AND 1", name="ck_probability"),)

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.assessment_id"), nullable=False, unique=True)
    probability: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel, name="risk_level"), nullable=False, index=True)
    referral_message: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    guideline_notice: Mapped[str | None] = mapped_column(Text)   # e.g. outside screening age 25-65
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    assessment: Mapped[RiskAssessment] = relationship(back_populates="prediction")
    factors: Mapped[list["ExplanationFactor"]] = relationship(
        back_populates="prediction", order_by="ExplanationFactor.rank", cascade="all, delete-orphan")


class ExplanationFactor(Base):
    """One of the top SHAP contributors for a prediction. Read-only once saved."""
    __tablename__ = "explanation_factors"
    __table_args__ = (
        UniqueConstraint("prediction_id", "rank", name="uq_prediction_rank"),
        CheckConstraint("rank >= 1", name="ck_rank"),
    )

    factor_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.prediction_id", ondelete="CASCADE"), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(50), nullable=False)
    feature_value: Mapped[str | None] = mapped_column(String(30))
    shap_value: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    plain_language_text: Mapped[str] = mapped_column(Text, nullable=False)

    prediction: Mapped[Prediction] = relationship(back_populates="factors")