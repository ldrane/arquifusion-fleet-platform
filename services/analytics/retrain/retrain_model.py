"""Entrenamiento y evaluación del IsolationForest (RF-13.2, MH-AI-04, TRZ-05).

Funciones puras sobre DataFrames (sin AWS):
- Etiquetas: una lectura es positiva si cae en la ventana precursora `[precursor_start, failure_at)` de una falla
  de `labels/failures.parquet`. Las lecturas de reparación `[failure_at, repair_end)` se excluyen. Sin archivo de
  fallas, se usa `sim_scenario` (solo los escenarios de falla; ociosa/sobreexplotada son de productividad).
- Score: `-model.score_samples(X)`, escala 0-1 del paper (≈0.5 normal, →1 anómalo). Es la MISMA escala que usa
  `procesar` para compararlo con `ModelMetadata.score_threshold`.
- Solo se entrenan y evalúan lecturas con `state = operating` (SCORED_STATES): en ralentí o detenida la máquina
  no está en un régimen comparable y el modelo las marcaría siempre. `procesar` debe omitir la capa ML en esos
  estados; la regla viaja en `metadata.extra["scored_states"]`.
- Partición temporal: 60 % entrenamiento (solo lecturas normales), 20 % calibración del umbral (máximo F1),
  20 % prueba (precision, recall y anticipación media reportadas).
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from arquifusion_ml.features import DERIVED_FEATURES, FEATURES, RAW_FEATURES
from arquifusion_ml.model_store import ModelMetadata
from sklearn.ensemble import IsolationForest

SCORED_STATES = ("operating",)
FAILURE_SCENARIOS = frozenset({"degradacion", "combustible", "falla_subita", "grupal_zona"})
TRAIN_SHARE, CALIBRATION_SHARE = 0.6, 0.2
MAX_TRAIN_ROWS = 200_000
N_ESTIMATORS = 200
FALLBACK_QUANTILE = 0.995
CANDIDATE_QUANTILES = np.linspace(0.80, 0.999, 60)
RANDOM_STATE = 42


@dataclass
class TrainResult:
    model: IsolationForest
    metadata: ModelMetadata


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos, agrega la variable derivada y ordena por tiempo. Descarta filas sin variables."""
    frame = df.copy()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True, format="mixed")
    for column in RAW_FEATURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(RAW_FEATURES))
    if "state" in frame:
        frame = frame[frame["state"].isin(SCORED_STATES)]
    # misma fórmula que arquifusion_ml.features.derive, vectorizada
    frame[DERIVED_FEATURES[0]] = frame["fuel_rate_lph"] / frame["load_pct"].clip(lower=1.0)
    return frame.sort_values("ts", kind="stable").reset_index(drop=True)


def label(frame: pd.DataFrame, failures: pd.DataFrame | None) -> tuple[pd.Series, pd.Series]:
    """Devuelve (positivo, excluir) por fila."""
    positive = pd.Series(False, index=frame.index)
    excluded = pd.Series(False, index=frame.index)
    if failures is None or failures.empty:
        scenario = frame.get("sim_scenario", pd.Series(None, index=frame.index)).fillna("")
        return scenario.isin(FAILURE_SCENARIOS), excluded
    for f in failures.itertuples():
        same = frame["machine_id"] == f.machine_id
        positive |= same & (frame["ts"] >= f.precursor_start) & (frame["ts"] < f.failure_at)
        excluded |= same & (frame["ts"] >= f.failure_at) & (frame["ts"] < f.repair_end)
    return positive, excluded


def anomaly_score(model: IsolationForest, x: np.ndarray) -> np.ndarray:
    return -model.score_samples(x)


def precision_recall(scores: np.ndarray, y: np.ndarray, threshold: float) -> tuple[float, float]:
    predicted = scores >= threshold
    tp = int(np.sum(predicted & y))
    precision = tp / int(np.sum(predicted)) if predicted.any() else 0.0
    recall = tp / int(np.sum(y)) if y.any() else 0.0
    return precision, recall


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def best_threshold(scores: np.ndarray, y: np.ndarray) -> float:
    candidates = np.quantile(scores, CANDIDATE_QUANTILES)
    return float(max(candidates, key=lambda t: f1(*precision_recall(scores, y, t))))


def mean_lead_time_hours(
    test: pd.DataFrame, scores: np.ndarray, threshold: float, failures: pd.DataFrame | None
) -> tuple[float, float]:
    """(anticipación media en horas, fracción de fallas detectadas) sobre las fallas del periodo de prueba."""
    if failures is None or failures.empty or test.empty:
        return 0.0, 0.0
    flagged = test.assign(score=scores)
    flagged = flagged[flagged["score"] >= threshold]
    start = test["ts"].min()
    leads, total = [], 0
    for f in failures.itertuples():
        if f.failure_at < start:
            continue
        total += 1
        hits = flagged[
            (flagged["machine_id"] == f.machine_id)
            & (flagged["ts"] >= f.precursor_start)
            & (flagged["ts"] < f.failure_at)
        ]
        if not hits.empty:
            leads.append((f.failure_at - hits["ts"].min()).total_seconds() / 3600)
    if not total:
        return 0.0, 0.0
    return (round(float(np.mean(leads)), 2) if leads else 0.0), round(len(leads) / total, 3)


def train(df: pd.DataFrame, failures: pd.DataFrame | None, version: str, now: datetime) -> TrainResult:
    """Entrena, calibra y evalúa un modelo candidato (promoted=False)."""
    frame = prepare(df)
    if len(frame) < 100:
        raise ValueError(f"Datos insuficientes para entrenar: {len(frame)} filas")
    if failures is not None and not failures.empty:
        failures = failures.assign(
            **{c: pd.to_datetime(failures[c], utc=True) for c in ("precursor_start", "failure_at", "repair_end")}
        )
    positive, excluded = label(frame, failures)
    frame, positive = frame[~excluded].reset_index(drop=True), positive[~excluded].reset_index(drop=True)

    n = len(frame)
    cut_train, cut_cal = int(n * TRAIN_SHARE), int(n * (TRAIN_SHARE + CALIBRATION_SHARE))
    x = frame[list(FEATURES)].to_numpy(dtype=float)
    y = positive.to_numpy(dtype=bool)

    train_x = x[:cut_train][~y[:cut_train]]
    if len(train_x) > MAX_TRAIN_ROWS:
        rng = np.random.default_rng(RANDOM_STATE)
        train_x = train_x[rng.choice(len(train_x), MAX_TRAIN_ROWS, replace=False)]
    model = IsolationForest(n_estimators=N_ESTIMATORS, max_samples=min(256, len(train_x)), random_state=RANDOM_STATE)
    model.fit(train_x)

    cal_scores, cal_y = anomaly_score(model, x[cut_train:cut_cal]), y[cut_train:cut_cal]
    if cal_y.any():
        threshold = best_threshold(cal_scores, cal_y)
    else:
        threshold = float(np.quantile(anomaly_score(model, train_x), FALLBACK_QUANTILE))

    test_scores, test_y = anomaly_score(model, x[cut_cal:]), y[cut_cal:]
    precision, recall = precision_recall(test_scores, test_y, threshold)
    lead, detection_rate = mean_lead_time_hours(frame.iloc[cut_cal:], test_scores, threshold, failures)

    metadata = ModelMetadata(
        model_version=version,
        trained_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        features=list(FEATURES),
        score_threshold=round(threshold, 6),
        precision=round(precision, 4),
        recall=round(recall, 4),
        mean_lead_time_hours=lead,
        promoted=False,
        training_rows=int(len(train_x)),
        extra={
            "f1": round(f1(precision, recall), 4),
            "failure_detection_rate": detection_rate,
            "score": "-score_samples (0-1)",
            "scored_states": list(SCORED_STATES),
            "label_source": "labels/failures.parquet"
            if failures is not None and not failures.empty
            else "sim_scenario",
            "test_rows": int(len(test_y)),
            "test_positives": int(test_y.sum()),
        },
    )
    return TrainResult(model, metadata)


def is_better(candidate: ModelMetadata, current: ModelMetadata | None) -> bool:
    """Regla de promoción: F1 del candidato ≥ F1 del modelo activo (sin modelo activo, siempre)."""
    if current is None:
        return True
    current_f1 = current.extra.get("f1", f1(current.precision, current.recall))
    return candidate.extra["f1"] >= current_f1


def next_version(active: str | None) -> str:
    try:
        return f"v{int(str(active).removeprefix('v')) + 1}"
    except ValueError:
        return "v1"
