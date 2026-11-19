# Explainable Cervical Cancer Risk Decision Support System for CHWs

**Prototype 1 (≈30%)** – project setup, PostgreSQL database, login and CHW account management,
the machine-learning training pipeline, and the dashboard. Risk assessment screens are added in later
prototypes.

## Project structure (Prototype 1)

```
cervical-dss/
├── ml/
│   ├── data/                 put risk_factors_cervical_cancer.csv here
│   ├── features.py           the 12 non-clinical input features
│   ├── train_model.py        the full ML pipeline (load → select → split → balance → train → evaluate → explain → save)
│   ├── artifacts/            created by training: model.json, preprocessor.pkl, config.json
│   └── reports/              created by training: tables and figures
├── backend/
│   ├── app/
│   │   ├── main.py           FastAPI app
│   │   ├── config.py         settings from backend/.env
│   │   ├── database.py       PostgreSQL connection (SQLAlchemy)
│   │   ├── models.py         all tables (users, clients, client_identities, identity_access_log, assessments, predictions, explanation_factors)
│   │   ├── schemas.py        request validation (Pydantic)
│   │   ├── security.py       bcrypt passwords, JWT login, role checks
│   │   ├── crypto.py         encryption of client personal details (name, phone, village, date of birth)
│   │   ├── services/         assessment_service.py (risk assessment), client_service.py (registration, client records, who sees names)
│   │   └── routers/          auth.py (login), users.py (CHW accounts), dashboard.py
│   ├── init_db.py            creates the tables + first Administrator
│   ├── migrate_client_identity.py   upgrades a database created before client names / dates of birth
│   └── tests/                40 automated tests
├── frontend/                 login, set password, dashboards, CHW accounts, assessment, results, history, clients
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

## 2. Train the model

Copy `risk_factors_cervical_cancer.csv` (https://archive.ics.uci.edu/dataset/383/cervical+cancer+risk+factors)
into `ml/data/`, then:
```
python ml/train_model.py
```
Results go to `ml/reports/` (model comparison, robustness checks, ROC curves, confusion matrices,
SHAP plots, risk-level distribution, feature-selection table) and the model files to `ml/artifacts/`.

## 3. Create the database

Create an empty PostgreSQL database called `cervical_dss` (pgAdmin → Databases → Create, or
`psql -U postgres -c "CREATE DATABASE cervical_dss;"`). Then, in `backend/`:
```
cp .env.example .env        # PowerShell: copy .env.example .env
```
Edit `backend/.env`: put your postgres password in `DATABASE_URL` and a random `SECRET_KEY`.
Add an `ENCRYPTION_KEY` generated with:
```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
It encrypts client names, phone numbers, villages and dates of birth. **Never change or lose it** once
clients are registered (their details could no longer be read); keep a copy outside the project. Then:
```
python init_db.py
```
Note the **admin username and temporary password** it prints.

Database created **before** client names and dates of birth were added? Upgrade it once (keeps all data):
```
python migrate_client_identity.py
```
Then run `python init_db.py` once more: it adds any new tables (such as `identity_access_log`) and keeps all data.

## 4. Run

From `backend/`:
```
uvicorn app.main:app --reload
```
Open http://localhost:8000 → log in as `admin` → set a new password → **Dashboard**.
**CHW Accounts** → register a CHW → log out → log in as the CHW → set a password → CHW dashboard.
API documentation: http://localhost:8000/docs

## 5. Test

From `backend/` (after training): `pytest -v` → 40 tests: login, forced password change, CHW account
management, client registration (date of birth, 18+ rule, identity consent, encryption, who sees names),
client records (list, search, visit history, updating and removing details, access log),
risk assessment inputs, age from date of birth, access control, dashboard and the installable app (PWA).

## 6. Git

```
git init
git config user.name "Your Name"
git config user.email "you@example.com"
git add .
git commit -m "Prototype 1: setup, database schema, login, CHW accounts, ML pipeline, dashboard"
```
GitHub: create an empty **private** repository, then
```
git branch -M main
git remote add origin https://github.com/<your-username>/cervical-dss.git
git push -u origin main
```
`.gitignore` keeps out `.venv`, `backend/.env` (passwords) and test databases.

## 7. Install on a phone (Progressive Web App)

The web app can be installed on a CHW's smartphone like an app (home-screen icon, opens full-screen).
No app store is needed and the code is the same as the web version.

- **Android (Chrome):** open the site, then tap **Install app on this phone** on the login page
  (or Chrome menu > **Add to Home screen**).
- **iPhone (Safari):** Share > **Add to Home Screen**.

Installing needs the site to be served over **HTTPS** (or `localhost` on the same computer).
To try it on a phone during development, use an HTTPS tunnel such as `ngrok http 8000`, or deploy the app.

What the service worker (`frontend/sw.js`) does:
- Loads pages, CSS and JavaScript from the server first whenever there is a connection, so updates reach every phone at once.
- Keeps a saved copy of the app's own pages, CSS, JavaScript and icons for when the network is slow or down.
- **Never** saves anything under `/api/` (logins, client codes, answers, results): no patient data is stored on the phone.
- When offline, shows a banner and an offline page. Assessments still need a connection, because the model runs on the server.

When you change any frontend file, raise `CACHE_VERSION` in `frontend/sw.js` so installed phones pick up the update.

## Client privacy (Kenya Data Protection Act 2019)

- Health data is linked to a client **code** only (e.g. CL-00042). Her personal details live in a separate
  table, `client_identities`, and are **encrypted**; pgAdmin shows them as unreadable text.
- **Date of birth is required** (or an approximate age if she does not know it). Age is calculated from it
  on the day of each visit, so it is never typed in and stays correct on return visits.
- **Name, phone and village are optional** and saved only with her **separate identity consent**.
  No national ID number is collected.
- The CHW who registered her sees her full name; the Administrator and other CHWs see **initials** ("M. W.").
- Clients must be **18 or older**. Outside the national screening ages (25–65) the result shows a guideline
  notice; the risk level itself is not changed.
- **Client records:** a CHW can open only the clients she registered (**My Clients**): her details and all her visits.
  She can correct the details, or **remove** name, phone and village if the client withdraws consent; the client
  code, date of birth and results are kept.
- **Identity access log:** every time full details are shown on a client record, corrected or removed, the system
  records who did it and when (field names only, never the values). The Administrator sees this log on the client
  record.