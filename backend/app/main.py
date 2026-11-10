"""
FastAPI application entry point.

Start the server from the backend folder:
    uvicorn app.main:app --reload
Then open:
    http://localhost:8000          -> the web application (frontend)
    http://localhost:8000/docs     -> interactive API documentation (Swagger)

Prototype 1 scope: authentication, CHW account management and the dashboard.
The trained model's details (config.json) are read for the dashboard; risk
prediction endpoints are added in a later prototype.
"""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIR, MODEL_DIR
from .routers import auth, dashboard, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_file = MODEL_DIR / "config.json"
    if not config_file.exists():
        raise FileNotFoundError(f"{config_file} not found. Train the model first: python ml/train_model.py")
    app.state.ml = SimpleNamespace(config=json.loads(config_file.read_text()))
    yield


app = FastAPI(
    title="Cervical Cancer Risk Decision Support System",
    description="Explainable XGBoost risk prediction for Community Health Workers in Kenya.",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(dashboard.router)


@app.get("/api/health", tags=["System"])
def health():
    cfg = app.state.ml.config
    return {"status": "ok", "model_version": cfg["model_version"], "thresholds": cfg["thresholds"]}


# Serve the HTML/CSS/JS frontend from the same server (mounted last so /api routes take priority)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
