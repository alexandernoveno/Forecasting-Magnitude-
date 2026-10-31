#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export trained models to JSON so the landing page can run them in the browser.

    python export_model_bundle.py

Writes model_bundle.json and catalogue.json at the repository root, which is
also the GitHub Pages site root. Imports earthquake_analysis.py rather than
re-deriving anything, so the exported models are the same objects the paper
reports, fitted on the same combined training and validation partitions.

The bundle carries the three models the study objectives name, and only those:

    Extra Trees        best on the test partition
    Random Forest      the tree ensemble the methodology names
    LSTM               the recurrent network the methodology names

The other thirteen forecasters stay in the paper's comparison tables, where
they belong, and are not shipped to the browser.

It also carries the preprocessing constants (log flags, training medians,
winsorising bounds, scaler statistics), the active-fault geometry, the
evidence panels the page displays, and a set of verification vectors. The
vectors are the whole point of shipping this file: the browser recomputes the
27 features from raw events in JavaScript, and a mismatch against the Python
values is silent unless something checks. `verify_bundle.cjs` checks.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "model_bundle.json"
CATALOGUE_OUT = ROOT / "catalogue.json"
VECTORS_OUT = ROOT / "verification_vectors.json"   # development asset, not shipped
SIGFIG = 17        # exact float64 round-trip, for anything whose scale is not
                   # known in advance: split thresholds, stored feature values,
                   # winsor bounds. See tree_to_dict for why decimal places are
                   # the wrong unit, and why 12 significant figures was still
                   # enough to flip a split in a depth-8 forest.
VALUE_ROUND = 6    # leaf values: averaged over hundreds of trees
WEIGHT_ROUND = 9   # linear and LSTM weights


def load_analysis():
    spec = importlib.util.spec_from_file_location("ea", ROOT / "earthquake_analysis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sig(value, digits=None):
    """Round to significant figures, which is scale independent."""
    return float(f"%.{digits or SIGFIG}g" % float(value))


def tree_to_dict(tree):
    """Flat arrays beat nested objects here: same information, a third the bytes.

    Thresholds are kept to significant figures, not decimal places. Rounding
    x7_mlk to 9 decimals collapsed its splits onto 0.0, and because that
    feature really does range from 1e-27 to 0.18 the browser then met an exact
    tie at `x <= t` and took the other branch from the one scikit-learn took.
    Leaf values are magnitudes, so decimals are the right unit for those.
    """
    t = tree.tree_
    return {
        "l": t.children_left.astype(int).tolist(),
        "r": t.children_right.astype(int).tolist(),
        "f": t.feature.astype(int).tolist(),
        "t": [sig(v) for v in t.threshold],
        "v": np.round(t.value.reshape(-1), VALUE_ROUND).tolist(),
    }


def best_rf_params(ea) -> dict:
    """The Random Forest the analysis actually chose.

    These were hardcoded here, and the hyperparameter grid moved underneath
    them when the data set changed, so the page was serving a forest the paper
    never fitted. Read the grid's own winner instead.
    """
    grid = pd.read_csv(ea.CFG.TABLE_DIR / "t34_rf_grid.csv").iloc[0]
    depth = grid["max_depth"]
    features = grid["max_features"]
    return {
        "n_estimators": int(grid["n_estimators"]),
        "max_depth": None if pd.isna(depth) else int(float(depth)),
        "min_samples_leaf": int(grid["min_samples_leaf"]),
        "max_features": features if isinstance(features, str) else float(features),
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
    rf_params = best_rf_params(ea)
    rf = RandomForestRegressor(random_state=ea.CFG.SEED, n_jobs=-1, **rf_params).fit(X, y)
    # Must match the Extra Trees entry in tabular_estimators exactly, or the
    # page would report a score the analysis never produced.
    et = ExtraTreesRegressor(n_estimators=200, max_depth=10,
                             random_state=ea.CFG.SEED, n_jobs=-1).fit(X, y)

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
            "mse": round(float(np.mean(err ** 2)), 4),
            "mae": round(float(np.mean(np.abs(err))), 4),
            "r2": round(1 - ss_res / ss_tot, 4),
            "bias": round(float(np.mean(err)), 4),
        }

    clim = float(y.mean())
    clim_mse = float(np.mean((clim - y_test) ** 2))

    def skill(pred):
        return round(100 * (1 - float(np.mean((pred - y_test) ** 2)) / clim_mse), 1)

    preds = {
        "random_forest": rf.predict(X_test),
        "extra_trees": et.predict(X_test),
        "lstm": lstm.predict(seq_te),
    }
    for key, pred in preds.items():
        print(f"  {key:18s} RMSE {score(pred)['rmse']:.4f}  skill {skill(pred):+.1f}%")

    models = {
        "extra_trees": {
            "label": "Extra Trees",
            "family": "Tree ensemble",
            "input": "features",
            "note": "Best on the test partition. 200 fully randomised trees, "
                    "depth 10. Splits are drawn at random rather than optimised, "
                    "which is what keeps it from overfitting 100 training sequences.",
            "kind": "forest",
            "trees": [tree_to_dict(t) for t in et.estimators_],
            **score(preds["extra_trees"]), "skill": skill(preds["extra_trees"]),
        },
        "random_forest": {
            "label": "Random Forest",
            "family": "Tree ensemble",
            "input": "features",
            "note": (f"{rf_params['n_estimators']} trees, "
                     + (f"depth {rf_params['max_depth']}"
                        if rf_params.get("max_depth") else "grown to purity")
                     + f", {rf_params['max_features']} features per split. "
                       "Settings chosen by the grid search in the paper."),
            "kind": "forest",
            "trees": [tree_to_dict(t) for t in rf.estimators_],
            **score(preds["random_forest"]), "skill": skill(preds["random_forest"]),
        },
        "lstm": {
            "label": "LSTM",
            "family": "Recurrent network",
            "input": "sequence",
            "note": (f"Reads the raw event stream, {ea.CFG.SEQ_LEN} events deep, "
                     "rather than the engineered features. Named in the study "
                     "objectives; scores below the climatology baseline here."),
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
    vectors = []
    cat_sorted = catalogue.sort_values("datetime", kind="mergesort").reset_index(drop=True)

    for k in picks:
        row = sequences.iloc[k]
        events = window_events(cat_sorted, row, ea)
        vec = {
            "events": events,
            "t_end_days": round(float((row["MainshockTime"]
                                       - cat_sorted["datetime"].iloc[0]).total_seconds()
                                      / 86400.0), 8),
            "epicentre": [round(float(row["MainshockLat"]), 4),
                          round(float(row["MainshockLon"]), 4)],
            # Significant figures, not decimal places: x7_mlk runs from 1e-27
            # to 0.18, so six decimals would flatten most of it to zero and the
            # replay would be fed different numbers from the ones scikit-learn
            # scored.
            "features": [sig(row[f]) if np.isfinite(row[f]) else None
                         for f in ea.FEATURE_NAMES],
            "expect": {key: round(float(preds[key][list(idx_test).index(k)]), 6)
                       for key in preds},
            "actual": round(float(row["Target"]), 2),
        }
        vectors.append(vec)

    payload = {
        "generated_from": "earthquake_analysis.py",
        "seed": ea.CFG.SEED,
        "features": ea.FEATURE_NAMES,
        "log_features": list(ea.LOG_FEATURES),
        # Significant figures again: a winsor bound rounded to six decimals
        # clamps a feature to a slightly different number from the one the
        # model was fitted against, which can flip a split.
        "median": [sig(medians[f]) for f in ea.FEATURE_NAMES],
        "winsor_lo": [sig(lo[f]) for f in ea.FEATURE_NAMES],
        "winsor_hi": [sig(hi[f]) for f in ea.FEATURE_NAMES],
        "window_days": ea.CFG.T_OBS_DAYS,
        "radius_km": ea.CFG.RADIUS_KM,
        "min_foreshocks": ea.CFG.MIN_FORESHOCKS,
        "energy_coeffs": list(ea.CFG.ENERGY_COEFFS),
        "mag_bin": ea.CFG.MAG_BIN,
        "background_days": ea.CFG.BACKGROUND_DAYS,
        "core_features": list(ea.CORE_FEATURE_NAMES),
        "fault_features": list(ea.FAULT_FEATURE_NAMES),
        "sources": source_points(catalogue),
        "occurrence": occurrence_block(ea),
        "evidence": evidence_block(ea),
        "seed": seed_sequence(cat_sorted, sequences, idx_test, ea),
        "climatology": round(clim, 4),
        "climatology_rmse": round(float(np.sqrt(clim_mse)), 4),
        "n_train": int(len(idx_trval)),
        "n_test": int(len(idx_test)),
        "models": models,
        "feature_names": list(ea.FEATURE_NAMES),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    # The vectors exist to check the browser's reimplementation, not to be
    # downloaded by every visitor, so they live outside the published folder.
    VECTORS_OUT.write_text(json.dumps({"vectors": vectors}, separators=(",", ":")))
    print(f"\nWrote {OUT}  ({OUT.stat().st_size / 1024:,.0f} KB)")
    print(f"Wrote {VECTORS_OUT}  ({VECTORS_OUT.stat().st_size / 1024:,.0f} KB), "
          f"{len(vectors)} verification vectors")

    export_catalogue(cat_sorted)
    stamp_asset_versions()


def export_catalogue(cat_sorted) -> None:
    """Ship the cleaned catalogue so the browser can compute regional context.

    Four of the 27 features count the days since the last large regional
    earthquake, and the beta statistic needs a background rate over the
    preceding year. Neither can be derived from the handful of events a user
    types into a form, so the page needs the surrounding record to work at all.

    Packed as four parallel flat arrays rather than an array of objects: same
    numbers, roughly a fifth of the bytes. Times carry eight decimals because
    the browser rebuilds absolute event times by subtracting from them, and at
    four decimals a mainshock's own record lands a few seconds before itself,
    which collapses every elapsed-time feature to zero. Coordinates carry five,
    about a metre, so events stay on the correct side of a radius test.
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


def stamp_asset_versions() -> None:
    """Re-sync every static asset reference in the page against the real files.

    Two jobs that both have to happen on every build or they silently rot.

    Versioning: index.html, the scripts and the figures are all served with
    max-age=600, so a returning visitor can run yesterday's JavaScript or look
    at yesterday's chart. A content hash in the query string makes each build a
    distinct URL, which is the only dependable way to retire a cached asset.
    Deriving it from the bytes means it cannot drift from what shipped.

    Dimensions: the width and height attributes reserve space before an image
    loads, so a stale pair causes exactly the layout shift they exist to
    prevent. Regenerating a figure changes its pixel size, so they are read back
    from the files rather than trusted.
    """
    import hashlib
    import re
    import shutil
    import struct

    page = ROOT / "index.html"
    if not page.exists():
        return
    html = page.read_text()
    notes = []

    # The pipeline writes figures into outputs/; the site serves figures/. Copy
    # across whatever the page actually references, so adding an <img> to the
    # page is the only step needed to publish a new chart.
    served = ROOT / "figures"
    served.mkdir(exist_ok=True)
    for name in sorted(set(re.findall(r'src="figures/([^"?]+)"', html))):
        built = ROOT / "outputs" / "figures" / name
        if built.exists():
            shutil.copy2(built, served / name)

    for name in ("forecast.js", "app.js"):
        target = ROOT / name
        if not target.exists():
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:10]
        pattern = re.compile(r'src="' + re.escape(name) + r'(?:\?v=[0-9a-f]+)?"')
        html, n = pattern.subn(f'src="{name}?v={digest}"', html)
        if n:
            notes.append(f"{name}={digest}")

    def refresh_image(match):
        src = match.group("src")
        target = ROOT / src
        if not target.exists():
            return match.group(0)
        raw = target.read_bytes()
        width, height = struct.unpack(">II", raw[16:24])
        digest = hashlib.sha256(raw).hexdigest()[:10]
        notes.append(f"{src.split('/')[-1]}={width}x{height}")
        return (f'src="{src}?v={digest}" width="{width}" height="{height}"')

    # width and height may be absent on a newly added <img>; they are written
    # in either way, because their whole purpose is to reserve the space before
    # the image arrives.
    html, images = re.subn(
        r'src="(?P<src>figures/[^"?]+)(?:\?v=[0-9a-f]+)?"'
        r'(?:\s+width="\d+"\s+height="\d+")?',
        refresh_image, html)

    page.write_text(html)
    print(f"Synced {images} images and stamped assets: " + ", ".join(notes))


def occurrence_block(ea) -> dict:
    """Occurrence rates and measured skill, read back from the analysis output.

    Only the historical conditional rates are shipped. The machine learning
    probability was built and scored and beat the base rate in one cell of nine,
    by 3.4% Brier skill with a fold-to-fold spread several times that, so the
    page reports the rates and states what the model achieved rather than
    dressing a coin flip up as a forecast.
    """
    import csv
    path = ea.CFG.TABLE_DIR / "t34_occurrence_skill.csv"
    intervals = ea.CFG.TABLE_DIR / "t35_occurrence_intervals.csv"
    if not path.exists():
        return {}
    cells = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            def num(key):
                try:
                    return round(float(row[key]), 3)
                except (TypeError, ValueError):
                    return None
            cells.append({
                "radius": int(float(row["Radius (km)"])),
                "threshold": float(row["Threshold"].split("≥")[-1]),
                "anchors": int(float(row["Anchors"])),
                "positives": int(float(row["Positives"])),
                "rate": num("Historical rate (%)"),
                "auc": num("M ROC AUC"),
                "bss": num("M Brier skill (%)"),
                "verdict": row["Verdict"],
            })
    # Attach the confidence intervals so the page can state its uncertainty
    # rather than quoting a bare percentage.
    if intervals.exists():
        conf = int(round((1 - ea.CFG.ALPHA) * 100))
        with open(intervals, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                r = int(float(row["Radius (km)"]))
                t = float(row["Threshold"].split("≥")[-1])
                for cell in cells:
                    if cell["radius"] == r and abs(cell["threshold"] - t) < 1e-9:
                        cell["ci"] = row[f"Wilson {conf}% CI"]
                        cell["moe"] = round(float(row["Margin of error (pp)"]), 2)
                        cell["block_ci"] = row[f"Year-block {conf}% CI"]
                        try:
                            cell["block_moe"] = round(float(row["Block MoE (pp)"]), 2)
                        except (TypeError, ValueError):
                            cell["block_moe"] = None

    # The deployable occurrence models, where one earned its place. Without
    # these the page can only quote a fixed historical rate, which looks broken:
    # the probability never moves no matter what events are entered.
    models = {}
    model_path = ea.CFG.TABLE_DIR / "occurrence_models.json"
    if model_path.exists():
        models = json.loads(model_path.read_text())

    return {
        "confidence": int(round((1 - ea.CFG.ALPHA) * 100)),
        "models": models,
        "feature_names": list(ea.FEATURE_NAMES),
        "horizon_days": ea.CFG.HORIZON_DAYS,
        "lookback_days": ea.CFG.T_OBS_DAYS,
        "thresholds": list(ea.CFG.OCC_THRESHOLDS),
        "radii": [int(r) for r in ea.CFG.OCC_RADII],
        "cells": cells,
    }


FAULTS_IN = ROOT / "data" / "active_faults.json"


def source_points(catalogue) -> dict:
    """The active-fault vertices the page measures distances against.

    The page cannot rerun a QGIS fault layer, so it picks the nearest of these
    for coordinates a visitor types in. The authors supplied the layer's own
    1,015 vertices, which is a superset of the 797 the catalogue's nearest-source
    column resolves to; recomputing every catalogue event against the fuller set
    moves the distance by a median of 0.06 km and by more than 1 km for 1.7% of
    events, so the two are the same layer at different sampling densities. The
    supplied set is used here because a visitor's own coordinates have no
    catalogue row to read a distance from.
    """
    if FAULTS_IN.exists():
        data = json.loads(FAULTS_IN.read_text())
        pts = {(round(a, 6), round(o, 6))
               for trace in data["traces"] for a, o in trace}
        if "SrcLat" in catalogue.columns:
            pts |= set(map(tuple, np.round(
                catalogue[["SrcLat", "SrcLon"]].drop_duplicates().to_numpy(float), 6)))
        ordered = sorted(pts)
        return {"lat": [a for a, _ in ordered], "lon": [o for _, o in ordered],
                "traces": data["traces"]}
    if "SrcLat" not in catalogue.columns:
        return {"lat": [], "lon": [], "traces": []}
    pts = catalogue[["SrcLat", "SrcLon"]].drop_duplicates()
    return {"lat": np.round(pts["SrcLat"].to_numpy(float), 6).tolist(),
            "lon": np.round(pts["SrcLon"].to_numpy(float), 6).tolist(),
            "traces": []}


def _table(name):
    """One of the pipeline's CSV tables, or None if it was never produced."""
    path = ROOT / "outputs" / "tables" / f"{name}.csv"
    return pd.read_csv(path) if path.exists() else None


def evidence_block(ea) -> dict:
    """The numbers the page quotes, read from the tables that produced them.

    Every headline on the landing page used to be typed in by hand, and when
    the data set changed the page went on reporting the old figure. An
    evaluator caught exactly that: a 23.6% improvement in the copy against
    11.4% in the results. Nothing here is typed twice any more.
    """
    out = {}

    board = _table("t39_leaderboard")
    if board is not None:
        keep = ("Extra Trees", "Random Forest", "LSTM",
                "Climatology (training mean)")
        sub = board[board["Model"].isin(keep)]
        out["leaderboard"] = [
            {"model": r["Model"], "rmse": round(float(r["RMSE"]), 4),
             "mse": round(float(r["MSE"]), 4), "mae": round(float(r["MAE"]), 4),
             "r2": round(float(r["R²"]), 4),
             "ci": str(r["95% CI for RMSE"]),
             "skill": round(float(r["Skill vs. climatology (%)"]), 1),
             "within": round(float(r["% within ±0.3"]), 1),
             "baseline": r["Model"].startswith("Climatology")}
            for _, r in sub.iterrows()]
        out["n_models_compared"] = int(len(board))
        out["n_beating_baseline"] = int(
            (board["Skill vs. climatology (%)"] > 0).sum())

    band = _table("t41c_magnitude_band")
    if band is not None:
        out["bands"] = [
            {"band": r["Observed band"], "n": int(r["n"]), "model": r["Model"],
             "observed": round(float(r["Mean observed"]), 2),
             "forecast": round(float(r["Mean forecast"]), 2),
             "bias": round(float(r["Bias (forecast − observed)"]), 2),
             "rmse": round(float(r["RMSE"]), 3)}
            for _, r in band.iterrows()]

    support = _table("t41d_training_support")
    if support is not None:
        out["support"] = [
            {"band": r["Magnitude band"], "train": int(r["Training n"]),
             "val": int(r["Validation n"]), "test": int(r["Test n"]),
             "total": int(r["Total"])}
            for _, r in support.iterrows()]

    ablation = _table("t41f_fault_ablation")
    if ablation is not None:
        out["ablation"] = [{"quantity": r["Quantity"], "value": str(r["Value"])}
                           for _, r in ablation.iterrows()]

    etas = _table("t41g_etas")
    if etas is not None:
        col = next((c for c in etas.columns if c.startswith("Skill vs.")), None)
        out["etas"] = [{"model": r["Model"], "rmse": round(float(r["RMSE"]), 4),
                        "skill": round(float(r[col]), 1) if col else None}
                       for _, r in etas.iterrows()]

    spread = _table("t41e_ensemble_spread")
    if spread is not None and not spread.empty:
        col = next((c for c in spread.columns if c.startswith("Observed at or below")),
                   None)
        if col:
            out["spread"] = [
                {"model": r["Model"], "band": r["Band"], "n": int(r["n"]),
                 "mean": round(float(r["Mean forecast"]), 2),
                 "upper": round(float(r[[c for c in spread.columns
                                         if c.startswith("Tree p")][0]]), 2),
                 "observed": round(float(r["Observed"]), 2),
                 "covered": round(float(r[col]), 1)}
                for _, r in spread.iterrows()]

    shap = _table("t44b_shap_global")
    if shap is not None:
        out["shap"] = [
            {"feature": r["Feature"], "mean_abs": round(float(r["Mean |SHAP|"]), 4),
             "mean": round(float(r["Mean SHAP"]), 4),
             "lo": round(float(r["Min SHAP"]), 4),
             "hi": round(float(r["Max SHAP"]), 4),
             "share": round(float(r["Share of explained movement (%)"]), 1)}
            for _, r in shap.head(10).iterrows()]
        out["shap_total"] = round(float(shap["Mean |SHAP|"].sum()), 3)

    cases = _table("t44c_shap_cases")
    if cases is not None and not cases.empty:
        blocks, current = [], None
        for _, r in cases.iterrows():
            if isinstance(r["Case"], str) and r["Case"].strip():
                current = {"title": r["Case"], "rows": []}
                blocks.append(current)
            if current is None:
                continue
            current["rows"].append(
                {"feature": r["Feature"],
                 "value": (None if pd.isna(r["Feature value"])
                           else round(float(r["Feature value"]), 3)),
                 "shap": round(float(r["SHAP contribution"]), 3),
                 "running": round(float(r["Running forecast"]), 3)})
        out["shap_cases"] = blocks[:1]

    audit = _table("t02_cleaning_audit")
    dec = _table("t25_decluster_summary")
    prof = _table("t29_sequence_profile")
    if audit is not None and dec is not None and prof is not None:
        num = lambda v: int(str(v).replace(",", ""))
        raw = num(audit.iloc[0]["Records before"])
        clean = num(audit.iloc[-1]["Records retained"])
        dependent = num(dec.loc[dec["Declustering stage"]
                                .str.contains("Dependent"), "n"].iloc[0])
        find = lambda key: num(prof.loc[prof["Quantity"].str.contains(key),
                                        "Value"].iloc[0])
        out["cleaning"] = [
            {"label": "Raw PHIVOLCS records", "n": raw, "note": ""},
            {"label": "Duplicate origins collapsed", "n": clean,
             "note": f"{raw - clean:,} records were one earthquake reported twice"},
            {"label": "Independent events", "n": clean - dependent,
             "note": f"{dependent:,} dependent events removed by Maeda Eq. 1 to 3: "
                     "aftershocks and swarm members, not precursors"},
            {"label": "Candidate mainshocks M 5.0 and above",
             "n": find("Candidate"),
             "note": f"{clean - dependent - find('Candidate'):,} independent events "
                     "below the study threshold"},
            {"label": "Forecast sequences", "n": find("retained"),
             "note": f"{find('Candidate') - find('retained'):,} windows rejected: "
                     "too few events, or holding an earthquake as large as the "
                     "mainshock they were supposed to precede"},
        ]

    scales = _table("t03b_magnitude_selection")
    if scales is not None:
        out["scales"] = [
            {"rank": int(r["Preference rank"]), "scale": r["Scale"],
             "measures": r["Measures"],
             "short": ea.MAGNITUDE_SCALE_SHORT.get(r["Scale"], ""),
             "reported": int(r["Events reporting it"]),
             "adopted": int(r["Events where it was adopted"]),
             "pct": round(float(r["% of catalogue adopted"]), 1)}
            for _, r in scales.iterrows()]

    windows = _table("t24_maeda_windows")
    if windows is not None:
        out["maeda_windows"] = [
            {"mpre": float(r["Precursor magnitude (Mpre)"]),
             "l_km": round(float(r["Spatial window L (km)"]), 2),
             "ta_days": round(float(r["Temporal window ta (days)"]), 2),
             "cutoff": round(float(r["Magnitude cut-off (Mpre − Md)"]), 1)}
            for _, r in windows.iterrows()]

    dictionary = _table("t28_feature_dictionary")
    if dictionary is not None:
        cols = {c.lower(): c for c in dictionary.columns}
        out["features"] = [
            {"name": r[cols.get("feature", dictionary.columns[0])],
             "category": r.get(cols.get("category", ""), ""),
             "description": r.get(cols.get("description", ""), "")}
            for _, r in dictionary.iterrows()]

    return out


def seed_sequence(cat_sorted, sequences, idx_test, ea) -> dict:
    """One real sequence, in the shape the form collects, to open the page with.

    Previously the panel opened on a dropdown of recorded sequences whose
    epicentre and foreshock list came from different places; one of them put an
    epicentre 600 km from its own foreshocks. The dropdown is gone at the
    authors' request, so one sequence is built here from the catalogue itself
    and both halves necessarily agree.

    The median sequence of the test partition is chosen rather than the most
    dramatic: a reader should arrive at a typical case, not a cherry-picked one.
    """
    pos = list(idx_test)[len(idx_test) // 2]
    row = sequences.iloc[pos]
    events = window_events(cat_sorted, row, ea)
    end = pd.Timestamp(row["MainshockTime"])
    stamp = lambda t: pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M")
    return {
        "when": stamp(end),
        "lat": round(float(row["MainshockLat"]), 4),
        "lon": round(float(row["MainshockLon"]), 4),
        "actual": round(float(row["Target"]), 2),
        "events": [{"at": stamp(end - pd.Timedelta(days=float(e["before"]))),
                    "mag": e["mag"], "lat": e["lat"], "lon": e["lon"],
                    "depth": e["depth"]}
                   for e in sorted(events, key=lambda e: -e["before"])],
    }


def window_events(cat_sorted, row, ea) -> list:
    """The raw events inside one mainshock's observation window.

    Returned in the same shape the web form collects: days before the mainshock,
    magnitude, latitude, longitude, depth.
    """
    origin = cat_sorted["datetime"].iloc[0]
    t_days = (cat_sorted["datetime"] - origin).dt.total_seconds().to_numpy() / 86400.0
    t_end = (row["MainshockTime"] - origin).total_seconds() / 86400.0
    # Bracket the window on the timestamps themselves. Converting to days first
    # cost a float ulp, because Timedelta.total_seconds() on a scalar and
    # .dt.total_seconds() on a column do not always land on the same float, and
    # one ulp was enough for searchsorted to keep the mainshock's own record as
    # the first event of its own window. It did that in 12 of 199 sequences,
    # every one of them reported as a foreshock equal in size to its mainshock.
    stamps = cat_sorted["datetime"].to_numpy()
    end = np.datetime64(row["MainshockTime"])
    start = end - np.timedelta64(int(ea.CFG.T_OBS_DAYS * 86400 * 1000), "ms")
    lo = int(np.searchsorted(stamps, start, side="left"))
    hi = int(np.searchsorted(stamps, end, side="left"))
    idx = np.arange(lo, hi)
    if idx.size:
        near = ea.haversine_km(row["MainshockLat"], row["MainshockLon"],
                               cat_sorted["Latitude"].to_numpy()[idx],
                               cat_sorted["Longitude"].to_numpy()[idx]) <= ea.CFG.RADIUS_KM
        idx = idx[near]
    has_fault = "SrcDistKm" in cat_sorted.columns
    out = []
    for i in idx:
        event = {
            "before": round(float(t_end - t_days[i]), 8),
            "mag": round(float(cat_sorted["Magnitude"].iloc[i]), 2),
            "lat": round(float(cat_sorted["Latitude"].iloc[i]), 4),
            "lon": round(float(cat_sorted["Longitude"].iloc[i]), 4),
            "depth": round(float(cat_sorted["Depth"].iloc[i]), 1),
        }
        if has_fault:
            event["dist"] = round(float(cat_sorted["SrcDistKm"].iloc[i]), 6)
        # The event's own origin time and magnitude scale, carried rather than
        # reconstructed. Subtracting a rounded `before` from the mainshock time
        # lands a few microseconds off and will not match the catalogue index.
        event["when"] = cat_sorted["datetime"].iloc[i].isoformat(sep=" ")
        event["scale"] = str(cat_sorted["MagScale"].iloc[i])
        out.append(event)
    return out


if __name__ == "__main__":
    main()
