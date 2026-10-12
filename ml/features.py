"""
Single source of truth for the model's input features.

The same 12 names are used in:
  - the CHW input form (frontend)
  - the RiskAssessment class / `assessments` table (backend)
  - the trained model
"""

# Mapping: UCI column name  ->  name used everywhere in the system
FEATURE_MAP = {
    "Age": "age",
    "Number of sexual partners": "num_sexual_partners",
    "First sexual intercourse": "age_first_intercourse",
    "Num of pregnancies": "num_pregnancies",
    "Smokes": "smokes",
    "Smokes (years)": "smokes_years",
    "Hormonal Contraceptives": "hormonal_contraceptives",
    "Hormonal Contraceptives (years)": "hormonal_contraceptives_years",
    "IUD": "iud",
    "IUD (years)": "iud_years",
    "STDs": "stds",
    "STDs (number)": "stds_number",
}

FEATURES = list(FEATURE_MAP.values())

TARGET = "Biopsy"

# Columns that must NEVER be used as inputs (leakage / clinical-only)
TEST_RESULT_COLUMNS = ["Hinselmann", "Schiller", "Citology", "Biopsy"]
DIAGNOSIS_COLUMNS = ["Dx:Cancer", "Dx:CIN", "Dx:HPV", "Dx"]

# Plain-language labels shown to CHWs in the SHAP explanation
PLAIN_LABELS = {
    "age": "Age",
    "num_sexual_partners": "Number of sexual partners",
    "age_first_intercourse": "Age at first sexual intercourse",
    "num_pregnancies": "Number of pregnancies",
    "smokes": "Smoking",
    "smokes_years": "Years of smoking",
    "hormonal_contraceptives": "Use of hormonal contraceptives",
    "hormonal_contraceptives_years": "Years of hormonal contraceptive use",
    "iud": "Has an IUD",
    "iud_years": "Years with an IUD",
    "stds": "History of a sexually transmitted infection",
    "stds_number": "Number of sexually transmitted infections",
}
