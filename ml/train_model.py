"""
OFFLINE MODEL DEVELOPMENT  (Phase 1 - training)
================================================
Follows the Machine Learning Pipeline figure step by step:

  1. Data acquisition + cleaning 6. Train + tune XGBoost, Random Forest, Logistic Regression
  2. Feature selection         7. Evaluate on the held-out test set (used once)
  3. Stratified train/test     8. Choose LOW / MODERATE / HIGH cut-offs (t1, t2)
  4. Preprocessing (train)     9. SHAP explainability
  5. SMOTE (train folds only) 10. Save model files for the web application

"""

# %% 0. Imports and settings
import json
import sys
from datetime import date
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.base import clone
from sklearn.calibration import calibration_curve
from sklearn.feature_selection import f_classif, mutual_info_classif
from sklearn.metrics import average_precision_score, brier_score_loss, classification_report, precision_recall_curve
from sklearn.model_selection import (GridSearchCV, RepeatedStratifiedKFold, StratifiedKFold, cross_val_predict,
                                     cross_val_score, train_test_split)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

try:
    ML_DIR = Path(__file__).resolve().parent
except NameError:
    ML_DIR = Path.cwd() if (Path.cwd() / "features.py").exists() else Path.cwd() / "ml"
sys.path.insert(0, str(ML_DIR))
from features import DIAGNOSIS_COLUMNS, FEATURE_MAP, FEATURES, PLAIN_LABELS, TARGET, TEST_RESULT_COLUMNS  # noqa: E402

DATA_FILE = ML_DIR / "data" / "risk_factors_cervical_cancer.csv"
ARTIFACTS = ML_DIR / "artifacts"
REPORTS = ML_DIR / "reports"
ARTIFACTS.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

RANDOM_STATE = 42
TEST_SIZE = 0.20
TARGET_SENSITIVITY = 0.90   # cut-off t1: at least 90% of positives must be MODERATE or HIGH
HIGH_SPECIFICITY = 0.90     # cut-off t2: at most 10% of negatives may be HIGH
MODEL_VERSION = f"xgb-v1.0-{date.today().isoformat()}"

REFERRAL_MESSAGES = {
    "LOW": "Low risk. Encourage routine cervical cancer screening at the nearest health facility "
           "as per national guidelines (every 5 years for women aged 25-49).",
    "MODERATE": "Moderate risk. Refer for cervical cancer screening at the nearest health facility "
                "within 3 months.",
    "HIGH": "High risk. Refer for cervical cancer screening as soon as possible "
            "(within 30 days) at the nearest health facility.",
}

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)

# %% 1. Data acquisition
if not DATA_FILE.exists():
    sys.exit(f"Dataset not found: {DATA_FILE}\n"
             "Download it from https://archive.ics.uci.edu/dataset/383/cervical+cancer+risk+factors "
             "and place risk_factors_cervical_cancer.csv in ml/data/")

raw = pd.read_csv(DATA_FILE, na_values="?")
print(f"Loaded {raw.shape[0]} records x {raw.shape[1]} columns")

missing = [c for c in list(FEATURE_MAP) + [TARGET] if c not in raw.columns]
if missing:
    sys.exit(f"These expected columns are missing from the CSV: {missing}")

# %% 1b. Data cleaning
#   (i)  exact duplicate rows are removed, so the same woman cannot appear in both the training
#        and the test set (which would make the test results look better than they are);
#   (ii) records with impossible answers are removed: age at first sexual intercourse greater than
#        current age (the web application rejects the same combination, see test TC17).
n_raw = len(raw)
duplicates = int(raw.duplicated().sum())
raw = raw.drop_duplicates().reset_index(drop=True)
impossible = raw["First sexual intercourse"] > raw["Age"]
n_impossible = int(impossible.sum())
raw = raw[~impossible].reset_index(drop=True)
cleaning = pd.DataFrame([
    {"step": "Records loaded", "records": n_raw, "positives": None},
    {"step": "Exact duplicate rows removed", "records": -duplicates, "positives": None},
    {"step": "Removed: age at first intercourse > current age", "records": -n_impossible, "positives": None},
    {"step": "Records used for modelling", "records": len(raw), "positives": int(raw[TARGET].sum())},
])
cleaning.to_csv(REPORTS / "data_cleaning.csv", index=False)
print(f"Cleaning: {n_raw} records -> removed {duplicates} duplicates and {n_impossible} impossible "
      f"-> {len(raw)} records ({int(raw[TARGET].sum())} positive)")

# %% 2. Feature selection
roles = []
for col in raw.columns:
    if col == TARGET:
        role = "Target (label)"
    elif col in TEST_RESULT_COLUMNS:
        role = "Excluded: screening test result (target leakage)"
    elif col in DIAGNOSIS_COLUMNS:
        role = "Excluded: prior clinical diagnosis (leakage, not collectable by a CHW)"
    elif col in FEATURE_MAP:
        role = "Input feature"
    else:
        role = "Excluded: sparse / not practical for CHW collection"
    roles.append({"column": col, "role": role, "missing_values": int(raw[col].isna().sum())})
pd.DataFrame(roles).to_csv(REPORTS / "feature_selection_table.csv", index=False)

X = raw[list(FEATURE_MAP)].rename(columns=FEATURE_MAP).astype(float)
y = raw[TARGET].astype(int)
print(f"Positive (Biopsy = 1): {y.sum()} of {len(y)} ({y.mean():.1%})")

# %% 3. Stratified train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
print(f"Train: {len(X_train)} ({y_train.sum()} positive) | Test: {len(X_test)} ({y_test.sum()} positive)")

# %% 3b. Statistical check of the selected features (training data only)
# The 12 features were chosen on domain grounds (collectable by a CHW, no leakage). These tests
# show how strongly each one is related to the biopsy result on its own:
#   ANOVA F-test: does the feature's mean differ between positive and negative cases? (p < 0.05 = yes)
#   Mutual information: how much knowing the feature reduces uncertainty about the result (0 = none);
#   it also picks up non-linear relationships that the F-test misses.
# Missing values are filled with the training median for this check only.
X_train_filled = X_train.fillna(X_train.median())
f_stat, f_p = f_classif(X_train_filled, y_train)
mi = mutual_info_classif(X_train_filled, y_train, random_state=RANDOM_STATE)
feature_stats = (pd.DataFrame({"feature": [PLAIN_LABELS[f] for f in FEATURES], "ANOVA_F": f_stat,
                               "p_value": f_p, "mutual_information": mi})
                 .sort_values("ANOVA_F", ascending=False).round(4))
feature_stats.to_csv(REPORTS / "feature_statistics.csv", index=False)
print("\nStatistical check of the selected features (training set):\n", feature_stats.to_string(index=False))


# %% 4 + 5. Preprocessing and SMOTE live INSIDE the pipeline, so during cross-validation
#            they are fitted on the training folds only (no leakage into validation folds).
def make_pipeline(classifier):
    return ImbPipeline([
        ("imputer", SimpleImputer(strategy="median")),  # "Declined / don't know" -> median
        ("scaler", StandardScaler()),
        ("smote", SMOTE(random_state=RANDOM_STATE)),     # applied to training data only
        ("clf", classifier),
    ])


# %% 6. Train and tune the three models
# Two ways of handling class imbalance are compared for every model, and cross-validation picks:
#   A) SMOTE oversampling of the training folds
#   B) the model's own class weighting (XGBoost scale_pos_weight, class_weight="balanced")
# Tuning uses repeated stratified 5-fold CV (10 repeats) on the training set: with so few positive
# cases, a single 5-fold split is too noisy to choose settings reliably.
POS_WEIGHT = float((y_train == 0).sum() / (y_train == 1).sum())
smote = SMOTE(random_state=RANDOM_STATE)
tune_cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=10, random_state=RANDOM_STATE)


def both_balancing(model_grid, weighted_param):
    """Return a grid list: model_grid with SMOTE, and model_grid with class weighting instead."""
    key, value = weighted_param
    return [
        {**model_grid, "smote": [smote], key: [None if key.endswith("class_weight") else 1]},
        {**model_grid, "smote": ["passthrough"], key: [value]},
    ]


candidates = {
    "XGBoost": (
        XGBClassifier(eval_metric="logloss", random_state=RANDOM_STATE, n_jobs=1),
        both_balancing({"clf__max_depth": [1, 2, 3], "clf__n_estimators": [150],
                        "clf__learning_rate": [0.05], "clf__subsample": [0.8],
                        "clf__colsample_bytree": [0.8], "clf__min_child_weight": [5]},
                       ("clf__scale_pos_weight", POS_WEIGHT)),
    ),
    "Random Forest": (
        RandomForestClassifier(n_estimators=300, random_state=RANDOM_STATE, n_jobs=1),
        both_balancing({"clf__max_depth": [None, 5], "clf__min_samples_leaf": [3, 10]},
                       ("clf__class_weight", "balanced_subsample")),
    ),
    "Logistic Regression": (
        LogisticRegression(max_iter=2000),
        both_balancing({"clf__C": [0.01, 0.1, 1]}, ("clf__class_weight", "balanced")),
    ),
}

fitted = {}
for name, (clf, grid) in candidates.items():
    search = GridSearchCV(make_pipeline(clf), grid, scoring="roc_auc", cv=tune_cv, n_jobs=-1)
    search.fit(X_train, y_train)
    fitted[name] = search
    params = {k.replace("clf__", ""): (v if k != "smote" else ("SMOTE" if v != "passthrough" else "class weighting"))
              for k, v in search.best_params_.items()}
    print(f"{name:20s} best CV AUC = {search.best_score_:.3f}  params = {params}")


# %% 7. Evaluate on the test set
def evaluate(y_true, prob, threshold):
    pred = (prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "AUC-ROC": roc_auc_score(y_true, prob),
        "Sensitivity (recall)": recall_score(y_true, pred, zero_division=0),
        "Specificity": tn / (tn + fp) if (tn + fp) else 0.0,
        "Precision": precision_score(y_true, pred, zero_division=0),
        "F1-score": f1_score(y_true, pred, zero_division=0),
        "Accuracy": accuracy_score(y_true, pred),
        "TP": tp, "FN": fn, "FP": fp, "TN": tn,
    }


test_probs = {name: s.predict_proba(X_test)[:, 1] for name, s in fitted.items()}
rows = []
for name, s in fitted.items():
    r = {"Model": name, "CV AUC (train)": s.best_score_}
    r.update(evaluate(y_test, test_probs[name], 0.5))
    rows.append(r)
comparison = pd.DataFrame(rows).round(3)
comparison.to_csv(REPORTS / "model_comparison.csv", index=False)
print("\nTest-set results at the default 0.5 threshold:\n", comparison.to_string(index=False))

# ROC curves
fig, ax = plt.subplots(figsize=(6, 5))
for name, prob in test_probs.items():
    fpr, tpr, _ = roc_curve(y_test, prob)
    ax.plot(fpr, tpr, label=f"{name} (AUC = {roc_auc_score(y_test, prob):.3f})")
ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Chance")
ax.set_xlabel("False positive rate (1 - specificity)")
ax.set_ylabel("True positive rate (sensitivity)")
ax.set_title("ROC curves on the test set")
ax.legend(loc="lower right")
fig.tight_layout()
fig.savefig(REPORTS / "roc_curves.png", dpi=200)
plt.close(fig)

# Confusion matrices (default threshold)
fig, axes = plt.subplots(1, 3, figsize=(13, 4))
for ax, (name, prob) in zip(axes, test_probs.items()):
    ConfusionMatrixDisplay(confusion_matrix(y_test, (prob >= 0.5).astype(int), labels=[0, 1]),
                           display_labels=["Negative", "Positive"]).plot(ax=ax, colorbar=False, cmap="Greys")
    ax.set_title(name)
fig.suptitle("Confusion matrices on the test set (threshold 0.5)")
fig.tight_layout()
fig.savefig(REPORTS / "confusion_matrices.png", dpi=200)
plt.close(fig)

# Precision-recall curves: more informative than ROC when positives are rare (6.5% here).
# Average precision (AP) summarises each curve; a model that guesses scores about the positive rate.
fig, ax = plt.subplots(figsize=(6, 5))
for name, prob in test_probs.items():
    prec, rec, _ = precision_recall_curve(y_test, prob)
    ax.plot(rec, prec, label=f"{name} (AP = {average_precision_score(y_test, prob):.3f})")
ax.axhline(y_test.mean(), color="k", linestyle="--", linewidth=1, label=f"Chance ({y_test.mean():.3f})")
ax.set_xlabel("Recall (sensitivity)")
ax.set_ylabel("Precision")
ax.set_title("Precision-recall curves on the test set")
ax.legend(loc="upper right")
fig.tight_layout()
fig.savefig(REPORTS / "pr_curves.png", dpi=200)
plt.close(fig)

# Calibration curves: do predicted probabilities match observed positive rates?
# Few positive cases, so 5 bins with equal numbers of women (quantile strategy).
# Brier score = mean squared error of the probabilities (lower is better).
fig, ax = plt.subplots(figsize=(6, 5))
for name, prob in test_probs.items():
    frac_pos, mean_pred = calibration_curve(y_test, prob, n_bins=5, strategy="quantile")
    ax.plot(mean_pred, frac_pos, marker="o", label=f"{name} (Brier = {brier_score_loss(y_test, prob):.3f})")
ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Perfectly calibrated")
ax.set_xlabel("Mean predicted probability")
ax.set_ylabel("Observed fraction positive")
ax.set_title("Calibration curves on the test set")
ax.legend(loc="upper left")
fig.tight_layout()
fig.savefig(REPORTS / "calibration_curves.png", dpi=200)
plt.close(fig)

pr_cal = pd.DataFrame([{"Model": name, "Average precision (PR-AUC)": average_precision_score(y_test, prob),
                        "Brier score": brier_score_loss(y_test, prob),
                        "Mean predicted probability": prob.mean(), "Observed positive rate": y_test.mean()}
                       for name, prob in test_probs.items()]).round(3)
pr_cal.to_csv(REPORTS / "pr_and_calibration.csv", index=False)
print("\nPrecision-recall and calibration:\n", pr_cal.to_string(index=False))

# Per-class report for each model at the default 0.5 threshold
with open(REPORTS / "classification_report.txt", "w") as fh:
    for name, prob in test_probs.items():
        fh.write(f"{name} (threshold 0.5)\n")
        fh.write(classification_report(y_test, (prob >= 0.5).astype(int), target_names=["Negative", "Positive"],
                                       zero_division=0, digits=3))
        fh.write("\n")

# %% 7b. Robustness checks (the test set has very few positive cases, so one split is noisy)
#   (i)  95% bootstrap confidence interval for each model's test AUC
#   (ii) repeated stratified cross-validation on ALL data with each model's tuned settings
rng = np.random.default_rng(RANDOM_STATE)
robust_rows = []
rcv = RepeatedStratifiedKFold(n_splits=5, n_repeats=5, random_state=RANDOM_STATE)
for name, s in fitted.items():
    prob, yt = test_probs[name], y_test.values
    boot = []
    for _ in range(2000):
        idx = rng.integers(0, len(yt), len(yt))
        if yt[idx].min() != yt[idx].max():
            boot.append(roc_auc_score(yt[idx], prob[idx]))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    rep = cross_val_score(clone(s.best_estimator_), X, y, scoring="roc_auc", cv=rcv, n_jobs=-1)
    robust_rows.append({"Model": name, "Test AUC": round(roc_auc_score(yt, prob), 3),
                        "Test AUC 95% CI": f"{lo:.3f} - {hi:.3f}",
                        "Repeated CV AUC mean": round(rep.mean(), 3), "Repeated CV AUC SD": round(rep.std(), 3)})
robust = pd.DataFrame(robust_rows)
robust.to_csv(REPORTS / "model_robustness.csv", index=False)
print("\nRobustness checks:\n", robust.to_string(index=False))

best_xgb = fitted["XGBoost"].best_estimator_

# %% 8. Choose the cut-offs t1 and t2 from OUT-OF-FOLD predictions on the training set
oof = cross_val_predict(best_xgb, X_train, y_train, cv=cv, method="predict_proba")[:, 1]
pos_oof, neg_oof = oof[y_train == 1], oof[y_train == 0]

# t1: the highest cut-off that still flags >= TARGET_SENSITIVITY of positives as MODERATE/HIGH
t1 = float(np.quantile(pos_oof, 1 - TARGET_SENSITIVITY))
# t2: the cut-off above which only (1 - HIGH_SPECIFICITY) of negatives fall
t2 = float(np.quantile(neg_oof, HIGH_SPECIFICITY))
if t2 <= t1:  # keep the three bands in order
    t2 = float(min(1.0, t1 + (1 - t1) / 2))
t1, t2 = round(t1, 4), round(t2, 4)
print(f"\nCut-offs: LOW < {t1} <= MODERATE < {t2} <= HIGH")


def risk_level(p):
    return np.where(p >= t2, "HIGH", np.where(p >= t1, "MODERATE", "LOW"))


xgb_test = test_probs["XGBoost"]
levels = pd.DataFrame({"level": risk_level(xgb_test), "actual": y_test.values})
dist = (levels.groupby("level")["actual"].agg(cases="count", positives="sum")
        .reindex(["LOW", "MODERATE", "HIGH"]).fillna(0).astype(int))
dist["positive_rate"] = (dist["positives"] / dist["cases"].replace(0, np.nan)).round(3)
dist.to_csv(REPORTS / "risk_level_distribution.csv")
print("\nTest set by risk level (XGBoost):\n", dist.to_string())

# Operational performance: "refer" = MODERATE or HIGH (probability >= t1)
operational = evaluate(y_test, xgb_test, t1)
print(f"\nReferral decision (MODERATE or HIGH) on test set: sensitivity = "
      f"{operational['Sensitivity (recall)']:.3f}, specificity = {operational['Specificity']:.3f}")

# %% 9. SHAP explainability (global view for the report)
# The fitted imputer + scaler become the Preprocessor used by the web application
preprocessor = Pipeline([("imputer", best_xgb.named_steps["imputer"]),
                         ("scaler", best_xgb.named_steps["scaler"])])
model = best_xgb.named_steps["clf"]
explainer = shap.TreeExplainer(model)
X_test_t = preprocessor.transform(X_test)
shap_values = explainer.shap_values(X_test_t)
labels = [PLAIN_LABELS[f] for f in FEATURES]

shap.summary_plot(shap_values, X_test, feature_names=labels, show=False)
plt.title("SHAP summary: how each factor pushes risk up or down")
plt.tight_layout()
plt.savefig(REPORTS / "shap_summary.png", dpi=200, bbox_inches="tight")
plt.close()

shap.summary_plot(shap_values, X_test, feature_names=labels, plot_type="bar", show=False)
plt.title("Mean absolute SHAP value (overall feature importance)")
plt.tight_layout()
plt.savefig(REPORTS / "shap_importance.png", dpi=200, bbox_inches="tight")
plt.close()

# %% 10. Save the files the web application loads at start-up
model.save_model(ARTIFACTS / "model.json")
joblib.dump(preprocessor, ARTIFACTS / "preprocessor.pkl")
config = {
    "model_version": MODEL_VERSION,
    "trained_on": date.today().isoformat(),
    "features": FEATURES,
    "feature_labels": PLAIN_LABELS,
    "target": TARGET,
    "thresholds": {"t1": t1, "t2": t2},
    "referral_messages": REFERRAL_MESSAGES,
    "top_k_factors": 3,
    "training_records": int(len(X_train)),
    "data_cleaning": {"records_loaded": n_raw, "duplicates_removed": duplicates,
                      "impossible_removed": n_impossible, "records_used": int(len(raw))},
    "imbalance_method": "SMOTE" if best_xgb.named_steps["smote"] != "passthrough" else "class weighting (scale_pos_weight)",
    "test_metrics_default_threshold": {k: round(float(v), 4) for k, v in
                                       comparison.set_index("Model").loc["XGBoost"].items()},
    "test_metrics_referral_threshold_t1": {k: round(float(v), 4) for k, v in operational.items()},
}
(ARTIFACTS / "config.json").write_text(json.dumps(config, indent=2))
print(f"\nSaved model files to {ARTIFACTS}")
print(f"Saved report tables and figures to {REPORTS}")

