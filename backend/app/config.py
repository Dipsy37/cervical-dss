"""Application settings, read from environment variables or backend/.env"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/cervical_dss")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-before-deployment")
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))      # one working day
TEMP_PASSWORD_HOURS = int(os.getenv("TEMP_PASSWORD_HOURS", "72"))
MODEL_DIR = Path(os.getenv("MODEL_DIR", PROJECT_DIR / "ml" / "artifacts"))
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", PROJECT_DIR / "frontend"))

# Key for encrypting client personal details (name, phone, village, date of birth).
# Generate once with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Keep it secret and NEVER change or lose it: details saved with one key cannot be read with another.
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")