-- ============================================================
-- Database Schema (PostgreSQL)
-- Explainable Cervical Cancer Risk Prediction System for CHWs
-- This file both documents the physical design AND creates the
-- real database:  psql -U postgres -d cervical_dss -f 07_database_schema.sql
-- ============================================================

CREATE TYPE user_role  AS ENUM ('ADMIN', 'CHW');
CREATE TYPE risk_level AS ENUM ('LOW', 'MODERATE', 'HIGH');
CREATE TYPE identity_action AS ENUM ('VIEW', 'UPDATE', 'REMOVE');

-- ------------------------------------------------------------
-- 1. USERS: Administrators and CHWs (accounts created by Admin)
-- ------------------------------------------------------------
CREATE TABLE users (
    user_id                  SERIAL        PRIMARY KEY,
    full_name                VARCHAR(100)  NOT NULL,
    username                 VARCHAR(50)   NOT NULL UNIQUE,
    phone                    VARCHAR(15)   UNIQUE,
    password_hash            VARCHAR(255)  NOT NULL,          -- bcrypt hash, never plain text
    role                     user_role     NOT NULL,
    chu_name                 VARCHAR(100),                    -- Community Health Unit (CHWs)
    is_active                BOOLEAN       NOT NULL DEFAULT TRUE,
    must_change_password     BOOLEAN       NOT NULL DEFAULT TRUE,
    temp_password_expires_at TIMESTAMP,
    created_by               INTEGER       REFERENCES users(user_id),
    created_at               TIMESTAMP     NOT NULL DEFAULT NOW(),
    last_login               TIMESTAMP
);

-- ------------------------------------------------------------
-- 2. CLIENTS: pseudonymous record of each woman assessed.
--    Health data links to client_id only; who she is lives in
--    client_identities (encrypted), never in this table.
-- ------------------------------------------------------------
CREATE TABLE clients (
    client_id      SERIAL        PRIMARY KEY,
    client_code    VARCHAR(12)   NOT NULL UNIQUE,             -- e.g. CL-00042
    chu_name       VARCHAR(100)  NOT NULL,
    registered_by  INTEGER       NOT NULL REFERENCES users(user_id),
    created_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 2b. CLIENT_IDENTITIES: personal details, one row per client (1:1).
--     Every personal field is ENCRYPTED by the application (Fernet)
--     before it is saved, so it is stored as TEXT and is unreadable
--     in pgAdmin or a backup. No national ID number is collected.
-- ------------------------------------------------------------
CREATE TABLE client_identities (
    client_id            INTEGER    PRIMARY KEY REFERENCES clients(client_id),
    full_name            TEXT,                                -- encrypted; optional, needs identity consent
    phone                TEXT,                                -- encrypted; optional, needs identity consent
    village              TEXT,                                -- encrypted; optional, needs identity consent
    date_of_birth        TEXT       NOT NULL,                 -- encrypted; age is calculated from it
    dob_estimated        BOOLEAN    NOT NULL DEFAULT FALSE,   -- TRUE = only an approximate age was known
    identity_consent     BOOLEAN    NOT NULL DEFAULT FALSE,   -- separate from consent to the assessment
    consent_recorded_at  TIMESTAMP,
    updated_at           TIMESTAMP  NOT NULL DEFAULT NOW(),
    details_removed_at   TIMESTAMP                            -- set if she later withdraws identity consent
);

-- ------------------------------------------------------------
-- 2c. IDENTITY_ACCESS_LOG: who opened, corrected or removed a
--     client's personal details, and when. Records the action and
--     the names of the fields changed, never the values.
-- ------------------------------------------------------------
CREATE TABLE identity_access_log (
    log_id       SERIAL           PRIMARY KEY,
    client_id    INTEGER          NOT NULL REFERENCES client_identities(client_id),
    user_id      INTEGER          NOT NULL REFERENCES users(user_id),
    action       identity_action  NOT NULL,
    detail       VARCHAR(200),                                -- e.g. 'phone, village'
    accessed_at  TIMESTAMP        NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 3. ASSESSMENTS: the 12 model input features per visit
--    NULL in a feature column = client declined / did not know
-- ------------------------------------------------------------
CREATE TABLE assessments (
    assessment_id                 SERIAL       PRIMARY KEY,
    client_id                     INTEGER      NOT NULL REFERENCES clients(client_id),
    chw_id                        INTEGER      NOT NULL REFERENCES users(user_id),
    assessed_at                   TIMESTAMP    NOT NULL DEFAULT NOW(),
    consent_obtained              BOOLEAN      NOT NULL CHECK (consent_obtained = TRUE),
    age                           SMALLINT     CHECK (age BETWEEN 18 AND 100),  -- from date of birth, on the visit day
    num_sexual_partners           SMALLINT     CHECK (num_sexual_partners >= 0),
    age_first_intercourse         SMALLINT     CHECK (age_first_intercourse BETWEEN 8 AND 60),
    num_pregnancies               SMALLINT     CHECK (num_pregnancies >= 0),
    smokes                        BOOLEAN,
    smokes_years                  NUMERIC(4,1) CHECK (smokes_years >= 0),
    hormonal_contraceptives       BOOLEAN,
    hormonal_contraceptives_years NUMERIC(4,1) CHECK (hormonal_contraceptives_years >= 0),
    iud                           BOOLEAN,
    iud_years                     NUMERIC(4,1) CHECK (iud_years >= 0),
    stds                          BOOLEAN,
    stds_number                   SMALLINT     CHECK (stds_number >= 0)
);

-- ------------------------------------------------------------
-- 4. PREDICTIONS: model output + referral rule result (1:1)
-- ------------------------------------------------------------
CREATE TABLE predictions (
    prediction_id     SERIAL        PRIMARY KEY,
    assessment_id     INTEGER       NOT NULL UNIQUE REFERENCES assessments(assessment_id),
    probability       NUMERIC(5,4)  NOT NULL CHECK (probability BETWEEN 0 AND 1),
    risk_level        risk_level    NOT NULL,
    referral_message  TEXT          NOT NULL,
    model_version     VARCHAR(20)   NOT NULL,                 -- audit: which model produced this
    guideline_notice  TEXT,                                   -- e.g. age outside screening range 25-65
    created_at        TIMESTAMP     NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 5. EXPLANATION_FACTORS: top SHAP contributors per prediction
-- ------------------------------------------------------------
CREATE TABLE explanation_factors (
    factor_id            SERIAL        PRIMARY KEY,
    prediction_id        INTEGER       NOT NULL REFERENCES predictions(prediction_id) ON DELETE CASCADE,
    feature_name         VARCHAR(50)   NOT NULL,
    feature_value        VARCHAR(30),
    shap_value           NUMERIC(8,4)  NOT NULL,              -- + raises risk, - lowers risk
    rank                 SMALLINT      NOT NULL CHECK (rank >= 1),
    plain_language_text  TEXT          NOT NULL,
    UNIQUE (prediction_id, rank)
);

-- Indexes for the most common look-ups
CREATE INDEX idx_assessments_chw    ON assessments(chw_id);
CREATE INDEX idx_assessments_client ON assessments(client_id);
CREATE INDEX idx_predictions_level  ON predictions(risk_level);
CREATE INDEX idx_access_log_client  ON identity_access_log(client_id);