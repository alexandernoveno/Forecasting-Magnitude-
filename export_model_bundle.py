#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export trained models to JSON so the landing page can run them in the browser.

    python export_model_bundle.py

Writes landing/model_bundle.json. Imports earthquake_analysis.py rather than
re-deriving anything, so the exported models are the same objects the paper
reports, fitted on the same combined training and validation partitions.

The bundle carries four models, one per family compared in the paper:

    Random Forest      the tuned model, best on the test partition
    Gradient Boosting  a second tree ensemble
    Elastic Net        a regularised linear model
    LSTM               the recurrent network, which loses to the baseline

It also carries the preprocessing constants (log flags, training medians,
winsorising bounds, scaler statistics) and a set of verification vectors. The
vectors are the whole point of shipping this file: the browser recomputes the
22 features from raw events in JavaScript, and a mismatch against the Python
values is silent unless something checks. `verify_bundle.mjs` checks.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import ElasticNet
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "landing" / "model_bundle.json"
CATALOGUE_OUT = ROOT / "landing" / "catalogue.json"
VECTORS_OUT = ROOT / "verification_vectors.json"   # development asset, not shipped
THRESH_ROUND = 9   # split thresholds: a flipped split is a visible error
VALUE_ROUND = 6    # leaf values: averaged over hundreds of trees
WEIGHT_ROUND = 9   # linear and LSTM weights


def load_analysis():
    spec = importlib.util.spec_from_file_location("ea", ROOT / "earthquake_analysis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_to_dict(tree):
    """Flat arrays beat nested objects here: same information, a third the bytes."""
    t = tree.tree_
    return {
        "l": t.children_left.astype(int).tolist(),
        "r": t.children_right.astype(int).tolist(),
        "f": t.feature.astype(int).tolist(),
        "t": np.round(t.threshold, THRESH_ROUND).tolist(),
        "v": np.round(t.value.reshape(-1), VALUE_ROUND).tolist(),
    }


def main() -> None:
    ea = load_analysis()
    print("Rebuilding the analysis ...")
    catalogue, _, _ = ea.load_catalogue()
    flagged, _ = ea.decluster(catalogue)
    independent = flagged[~flagged["IsDependent"]].reset_index(drop=True)
    sequences = ea.build_sequences(independent, full=catalogue)
    bundle = ea.DataBundle(sequences, catalogue)

    n = len(sequences)
    n_tr = int(round(ea.CFG.SPLIT_FRACTIONS[0] * n))
    n_va = int(round(ea.CFG.SPLIT_FRACTIONS[1] * n))
    idx_trval = np.arange(n_tr + n_va)
    idx_test = np.arange(n_tr + n_va, n)

    X, X_test = bundle.tabular(idx_trval, idx_test)
    y, y_test = bundle.y[idx_trval], bundle.y[idx_test]
    print(f"  {n} sequences, fitting on {len(idx_trval)}, scoring on {len(idx_test)}")

    # --- Preprocessing constants, taken from the training rows only ---------- #
    train_tab = bundle.tab.iloc[idx_trval]
    medians = train_tab.median(numeric_only=True).fillna(0.0)
    lo = train_tab.quantile(ea.WINSOR_QUANTILES[0])
    hi = train_tab.quantile(ea.WINSOR_QUANTILES[1])

    # --- Tabular models ------------------------------------------------------ #
    rf_params = dict(n_estimators=300, max_depth=8, min_samples_leaf=1, max_features=0.5)
    rf = RandomForestRegressor(random_state=ea.CFG.SEED, n_jobs=-1, **rf_params).fit(X, y)
    gb = GradientBoostingRegressor(n_estimators=400, learning_rate=0.05, max_depth=3,
                                   subsample=0.8, random_state=ea.CFG.SEED).fit(X, y)
    en = Pipeline([("scale", StandardScaler()),
                   ("model", ElasticNet(alpha=0.05, l1_ratio=0.5, max_iter=10000,
                                        random_state=ea.CFG.SEED))]).fit(X, y)

    # --- Sequence model ------------------------------------------------------ #
    seq_tr, seq_te = bundle.sequence(idx_trval, idx_test)
    cut = int(0.85 * len(seq_tr))
    lstm = ea.NumpyLSTM(seed=ea.CFG.SEED, epochs=ea.CFG.NN_EPOCHS)
    lstm.fit(seq_tr[:cut], y[:cut], seq_tr[cut:], y[cut:])

    # The sequence scaler has to be rebuilt here exactly as DataBundle builds it,
    # because the fitted object is not returned.
    raw_tr = bundle.tensors[idx_trval].copy()
    raw_tr[:, :, 2] = np.log1p(np.clip(raw_tr[:, :, 2], 0, None))
    flat = raw_tr.reshape(-1, raw_tr.shape[2])
    seq_lo = np.percentile(flat, 100 * ea.WINSOR_QUANTILES[0], axis=0)
    seq_hi = np.percentile(flat, 100 * ea.WINSOR_QUANTILES[1], axis=0)
    seq_scaler = StandardScaler().fit(np.clip(flat, seq_lo, seq_hi))

    def score(pred):
        err = pred - y_test
        ss_res = float((err ** 2).sum())
        ss_tot = float(((y_test - y_test.mean()) ** 2).sum())
        return {
            "rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
            "mae": round(float(np.mean(np.abs(err))), 4),
            "r2": round(1 - ss_res / ss_tot, 4),
        }

    clim = float(y.mean())
    clim_mse = float(np.mean((clim - y_test) ** 2))

    def skill(pred):
        return round(100 * (1 - float(np.mean((pred - y_test) ** 2)) / clim_mse), 1)

    preds = {
        "random_forest": rf.predict(X_test),
        "gradient_boosting": gb.predict(X_test),
        "elastic_net": en.predict(X_test),
        "lstm": lstm.predict(seq_te),
    }
    for key, pred in preds.items():
        print(f"  {key:18s} RMSE {score(pred)['rmse']:.4f}  skill {skill(pred):+.1f}%")

    models = {
        "random_forest": {
            "label": "Random Forest",
            "family": "Tree ensemble",
            "input": "features",
            "note": "Best model in the paper. 300 trees, depth 8.",
            "kind": "forest",
            "trees": [tree_to_dict(t) for t in rf.estimators_],
            **score(preds["random_forest"]), "skill": skill(preds["random_forest"]),
        },
        "gradient_boosting": {
            "label": "Gradient Boosting",
            "family": "Tree ensemble",
            "input": "features",
            "note": "400 shallow trees fitted in sequence on the residuals.",
            "kind": "boosted",
            "init": round(float(gb.init_.constant_.ravel()[0]), 6),
            "lr": gb.learning_rate,
            "trees": [tree_to_dict(t[0]) for t in gb.estimators_],
            **score(preds["gradient_boosting"]), "skill": skill(preds["gradient_boosting"]),
        },
        "elastic_net": {
            "label": "Elastic Net",
            "family": "Regularised linear",
            "input": "features",
            "note": "One weight per feature. The whole model is 22 numbers.",
            "kind": "linear",
            "mean": np.round(en.named_steps["scale"].mean_, WEIGHT_ROUND).tolist(),
            "scale": np.round(en.named_steps["scale"].scale_, WEIGHT_ROUND).tolist(),
            "coef": np.round(en.named_steps["model"].coef_, WEIGHT_ROUND).tolist(),
            "intercept": round(float(en.named_steps["model"].intercept_), WEIGHT_ROUND),
            **score(preds["elastic_net"]), "skill": skill(preds["elastic_net"]),
        },
        "lstm": {
            "label": "LSTM",
            "family": "Recurrent network",
            "input": "sequence",
            "note": "Reads the raw event stream. Scores worse than the baseline.",
            "kind": "lstm",
            "units": lstm.units,
            "seq_len": ea.CFG.SEQ_LEN,
            "W": np.round(lstm.p["W"], WEIGHT_ROUND).tolist(),
            "b": np.round(lstm.p["b"], WEIGHT_ROUND).tolist(),
            "Wy": np.round(lstm.p["Wy"].ravel(), WEIGHT_ROUND).tolist(),
            "by": round(float(lstm.p["by"][0]), WEIGHT_ROUND),
            "seq_lo": np.round(seq_lo, WEIGHT_ROUND).tolist(),
            "seq_hi": np.round(seq_hi, WEIGHT_ROUND).tolist(),
            "seq_mean": np.round(seq_scaler.mean_, WEIGHT_ROUND).tolist(),
            "seq_scale": np.round(seq_scaler.scale_, WEIGHT_ROUND).tolist(),
            **score(preds["lstm"]), "skill": skill(preds["lstm"]),
        },
    }

    # --- Verification vectors ------------------------------------------------ #
    # Raw events plus the Python-side features and predictions, so the browser's
    # reimplementation can be checked instead of trusted.
    rng = np.random.default_rng(ea.CFG.SEED)
    picks = sorted(rng.choice(idx_test, size=min(60, len(idx_test)), replace=False).tolist())
    vectors, examples = [], []
    cat_sorted = catalogue.sort_values("datetime", kind="mergesort").reset_index(drop=True)

    for pos, k in enumerate(picks):
        row = sequences.iloc[k]
        events = window_events(cat_sorted, row, ea)
        vec = {
            "events": events,
            "t_end_days": round(float((row["MainshockTime"]
                                       - cat_sorted["datetime"].iloc[0]).total_seconds()
                                      / 86400.0), 8),
            "epicentre": [round(float(row["MainshockLat"]), 4),
                          round(float(row["MainshockLon"]), 4)],
            "features": [round(float(row[f]), 6) if np.isfinite(row[f]) else None
                         for f in ea.FEATURE_NAMES],
            "expect": {key: round(float(preds[key][list(idx_test).index(k)]), 6)
                       for key in preds},
            "actual": round(float(row["Target"]), 2),
        }
        vectors.append(vec)
        if pos < 3:
            examples.append({
                "id": f"seq{pos + 1}",
                "when": row["MainshockTime"].strftime("%d %b %Y"),
                # Days since the catalogue origin, so the page uses the real
                # mainshock time rather than a date the reader typed.
                "t_end": vec["t_end_days"],
                "iso": row["MainshockTime"].strftime("%Y-%m-%d"),
                "epicentre": vec["epicentre"],
                "events": events,
                "actual": vec["actual"],
            })

    payload = {
        "generated_from": "earthquake_analysis.py",
        "seed": ea.CFG.SEED,
        "features": ea.FEATURE_NAMES,
        "log_features": list(ea.LOG_FEATURES),
        "median": [round(float(medians[f]), 6) for f in ea.FEATURE_NAMES],
        "winsor_lo": [round(float(lo[f]), 6) for f in ea.FEATURE_NAMES],
        "winsor_hi": [round(float(hi[f]), 6) for f in ea.FEATURE_NAMES],
        "window_days": ea.CFG.T_OBS_DAYS,
        "radius_km": ea.CFG.RADIUS_KM,
        "min_foreshocks": ea.CFG.MIN_FORESHOCKS,
        "energy_coeffs": list(ea.CFG.ENERGY_COEFFS),
        "mag_bin": ea.CFG.MAG_BIN,
        "background_days": ea.CFG.BACKGROUND_DAYS,
        "climatology": round(clim, 4),
        "climatology_rmse": round(float(np.sqrt(clim_mse)), 4),
        "n_train": int(len(idx_trval)),
        "n_test": int(len(idx_test)),
        "models": models,
        "examples": examples,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    # The vectors exist to check the browser's reimplementation, not to be
    # downloaded by every visitor, so they live outside the published folder.
    VECTORS_OUT.write_text(json.dumps({"vectors": vectors}, separators=(",", ":")))
    print(f"\nWrote {OUT}  ({OUT.stat().st_size / 1024:,.0f} KB)")
    print(f"  {len(examples)} worked examples")
    print(f"Wrote {VECTORS_OUT}  ({VECTORS_OUT.stat().st_size / 1024:,.0f} KB), "
          f"{len(vectors)} verification vectors")

    export_catalogue(cat_sorted)


def export_catalogue(cat_sorted) -> None:
    """Ship the cleaned catalogue so the browser can compute regional context.

    Four of the 22 features count the days since the last large regional
    earthquake, and the beta statistic needs a background rate over the
    preceding year. Neither can be derived from the handful of events a user
    types into a form, so the page needs the surrounding record to work at all.

    Packed as four parallel flat arrays rather than an array of objects: same
    numbers, roughly a fifth of the bytes, and the browser reads it straight
    into typed arrays.
    """
    origin = cat_sorted["datetime"].iloc[0]
    t_days = (cat_sorted["datetime"] - origin).dt.total_seconds().to_numpy() / 86400.0
    payload = {
        "origin": origin.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n": int(len(cat_sorted)),
        "t": np.round(t_days, 8).tolist(),
        "lat": np.round(cat_sorted["Latitude"].to_numpy(float), 5).tolist(),
        "lon": np.round(cat_sorted["Longitude"].to_numpy(float), 5).tolist(),
        "mag": np.round(cat_sorted["Magnitude"].to_numpy(float), 2).tolist(),
    }
    CATALOGUE_OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {CATALOGUE_OUT}  ({CATALOGUE_OUT.stat().st_size / 1024:,.0f} KB), "
          f"{payload['n']:,} events")


def window_events(cat_sorted, row, ea) -> list:
    """The raw events inside one mainshock's observation window.

    Returned in the same shape the web form collects: days before the mainshock,
    magnitude, latitude, longitude, depth.
    """
    origin = cat_sorted["datetime"].iloc[0]
    t_days = (cat_sorted["datetime"] - origin).dt.total_seconds().to_numpy() / 86400.0
    t_end = (row["MainshockTime"] - origin).total_seconds() / 86400.0
    lo = np.searchsorted(t_days, t_end - ea.CFG.T_OBS_DAYS, side="left")
    hi = np.searchsorted(t_days, t_end, side="left")
    idx = np.arange(lo, hi)
    if idx.size:
        near = ea.haversine_km(row["MainshockLat"], row["MainshockLon"],
                               cat_sorted["Latitude"].to_numpy()[idx],
                               cat_sorted["Longitude"].to_numpy()[idx]) <= ea.CFG.RADIUS_KM
        idx = idx[near]
    out = []
    for i in idx:
        out.append({
            "before": round(float(t_end - t_days[i]), 6),
            "mag": round(float(cat_sorted["Magnitude"].iloc[i]), 2),
            "lat": round(float(cat_sorted["Latitude"].iloc[i]), 4),
            "lon": round(float(cat_sorted["Longitude"].iloc[i]), 4),
            "depth": round(float(cat_sorted["Depth"].iloc[i]), 1),
        })
    return out


if __name__ == "__main__":
    main()
