# Explainable Cervical Cancer Risk Decision Support System for CHWs

A web-based decision support system that helps Community Health Workers (CHWs) in rural Kenya identify
women at elevated risk of cervical cancer from non-clinical, questionnaire-based answers. An XGBoost model
classifies risk as **Low, Moderate or High**, SHAP explains the main factors behind each result in plain
language, and the system gives a referral recommendation. It is a risk-prediction and referral tool, not a
diagnostic instrument.

Built with Object-Oriented Analysis and Design and Evolutionary Prototyping, as described in Chapter 3.

## Project structure

```
cervical-dss/
├── ml/
│   ├── data/                 risk_factors_cervical_cancer.csv (UCI Cervical Cancer Risk Factors dataset)
│   ├── features.py           the 12 non-clinical input features
│   ├── train_model.py        the ML pipeline (load → clean → select → split → balance → tune → evaluate → explain → save)
│   ├── artifacts/            trained model files: model.json, preprocessor.pkl, config.json
│   └── reports/              evaluation tables and figures (model comparison, ROC, confusion matrices, SHAP, ...)
├── backend/
│   ├── app/
│   │   ├── main.py           FastAPI application
│   │   ├── config.py         settings from backend/.env
│   │   ├── database.py       PostgreSQL connection (SQLAlchemy)
│   │   ├── models.py         the 5 tables: users, clients, assessments, predictions, explanation_factors
│   │   ├── schemas.py        request and response validation (Pydantic)
│   │   ├── security.py       bcrypt passwords, JWT login, role checks
│   │   ├── ml/inference.py   Preprocessor, RiskPredictor, SHAPExplainer, ReferralRuleEngine
│   │   ├── services/         assessment_service.py (predict, explain, classify, save)
│   │   └── routers/          auth, users (CHW accounts), clients, assessments, dashboard
│   ├── init_db.py            creates the tables and the first Administrator
│   └── tests/                22 automated black-box tests
├── frontend/                 HTML/CSS/JavaScript pages: login, change password, dashboards, CHW accounts,
│                             assessment form, result, assessment history, all assessments
├── database/schema.sql       the database schema as SQL
└── requirements.txt
```

## 1. Set up (once)

From the `cervical-dss` folder:

| | PowerShell | Git Bash | WSL |
|---|---|---|---|
| Create environment | `python -m venv .venv` | `python -m venv .venv` | `python3 -m venv .venv` |
| Activate (every new terminal) | `.\.venv\Scripts\Activate.ps1` | `source .venv/Scripts/activate` | `source .venv/bin/activate` |
| Install packages | `pip install -r requirements.txt` | same | same |

## 2. Train the model (optional)

The trained model is already in `ml/artifacts/`. To retrain, from the `cervical-dss` folder:
```
python ml/train_model.py
```
XGBoost, Random Forest and Logistic Regression are tuned with grid search and repeated stratified
cross-validation (SMOTE and class weighting both compared). Results go to `ml/reports/` and the model
files to `ml/artifacts/`.

## 3. Create the database

Create an empty PostgreSQL database (pgAdmin → Databases → Create), for example `cervical_dss`. Then, in
`backend/`:
```
cp .env.example .env        # PowerShell: copy .env.example .env
```
Edit `backend/.env`: put your postgres password and database name in `DATABASE_URL`, and a random
`SECRET_KEY`. Then:
```
python init_db.py
```
Note the **admin username and temporary password** it prints.

## 4. Run

From `backend/`:
```
uvicorn app.main:app --reload
```
Open http://localhost:8000.

1. Log in as the Administrator and set a new password.
2. **CHW Accounts** → register a CHW (the system generates her username and temporary password).
3. Log out, log in as the CHW and set a password.
4. **New Assessment** → enter a client code or register a new client (a pseudonymous code such as
   CL-00001 is generated) → confirm consent → answer the questionnaire → submit.
5. The result shows the **risk level**, a **referral recommendation** and the **top risk factors** (SHAP).
6. **Assessment History** lists the CHW's own assessments; the Administrator sees **All Assessments**.

API documentation: http://localhost:8000/docs

## 5. Test

From `backend/`: `pytest -v` → 22 tests covering login, forced password change, CHW account management,
client registration, risk assessment (valid, declined, boundary and invalid inputs), saved results,
access control and the dashboard.

## Privacy

Clients are identified only by a pseudonymous code. No names, phone numbers or ID numbers are collected,
and `.gitignore` keeps `backend/.env` (passwords and keys) out of the repository.
