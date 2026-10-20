"""Independent verification of the dataset and the forecasts.

Run this to check three claims without retraining anything:

  1. No foreshock in the data set is larger than the mainshock it precedes.
  2. The models shipped to the website reproduce the paper's predictions.
  3. The forecasts for the held-out test partition match the recorded
     magnitudes to the accuracy the paper reports.

It reads only files that ship with the repository and needs numpy, pandas and
openpyxl. No scikit-learn, no training, no raw catalogue. Exit status is 0 when
every check passes and 1 otherwise, so it can be run unattended.

    python3 verify_forecasts.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def beside(*candidates):
    """First candidate that exists, so this runs from the repository or from a
    flat folder handed to a reviewer."""
    for name in candidates:
        if (ROOT / name).exists():
            return ROOT / name
    return ROOT / candidates[0]


DATASET = beside("outputs/Foreshock_Sequences.xlsx", "Foreshock_Sequences.xlsx")
BUNDLE = beside("model_bundle.json")
VECTORS = beside("verification_vectors.json")
REPORT = beside("outputs/tables", ".") / "verification_forecasts.csv"

PRED_TOL = 1e-5          # a replayed prediction should match to six decimals
RF_TOL = PRED_TOL        # no looser than the rest, now that the float32 cast matches
failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# --------------------------------------------------------------------------- #
# The model, reimplemented from the exported bundle. These three functions are
# the whole prediction path the website runs; if they disagree with `expect`,
# the shipped model is not the paper's model.
# --------------------------------------------------------------------------- #
def preprocess(raw, bundle):
    """Signed log10 on the heavy-tailed features, impute, then winsorise."""
    log_set = set(bundle["log_features"])
    out = []
    for i, value in enumerate(raw):
        v = value
        name = bundle["features"][i]
        if name in log_set and v is not None and np.isfinite(v):
            v = np.sign(v) * np.log10(1 + abs(v))
        if v is None or not np.isfinite(v):
            v = bundle["median"][i]
        out.append(min(max(v, bundle["winsor_lo"][i]), bundle["winsor_hi"][i]))
    return out


def run_tree(tree, x):
    node = 0
    while tree["l"][node] != -1:
        node = tree["l"][node] if x[tree["f"][node]] <= tree["t"][node] else tree["r"][node]
    return tree["v"][node]


def predict_features(model, x):
    if model["kind"] == "forest":
        # scikit-learn casts X to float32 before walking a tree, so a value
        # within a float32 ulp of a split threshold takes the other branch
        # unless the same cast is applied here. The linear model is fitted in
        # float64 and must not be cast.
        xf = np.asarray(x, np.float32).astype(float)
        return sum(run_tree(t, xf) for t in model["trees"]) / len(model["trees"])
    if model["kind"] == "linear":
        acc = model["intercept"]
        for i, xi in enumerate(x):
            acc += model["coef"][i] * ((xi - model["mean"][i]) / model["scale"][i])
        return acc
    raise ValueError(f"not a feature model: {model['kind']}")


def build_sequence(events, lat, lon, model):
    """The LSTM's input tensor, mirroring DataBundle.sequence."""
    L, C = model["seq_len"], 5
    tensor = [[0.0] * C for _ in range(L)]
    taken = events[max(0, len(events) - L):]
    times = [-e["before"] for e in taken]
    for i, e in enumerate(taken):
        gap_hours = 0.0 if i == 0 else (times[i] - times[i - 1]) * 24
        tensor[L - len(taken) + i] = [e["mag"], e["depth"], gap_hours,
                                      e["lat"] - lat, e["lon"] - lon]
    for row in tensor:
        row[2] = float(np.log1p(max(row[2], 0.0)))
        for c in range(C):
            v = min(max(row[c], model["seq_lo"][c]), model["seq_hi"][c])
            row[c] = (v - model["seq_mean"][c]) / model["seq_scale"][c]
    return np.asarray(tensor, float)


def predict_lstm(model, tensor):
    H = model["units"]
    W = np.asarray(model["W"], float)
    b = np.asarray(model["b"], float)
    h = np.zeros(H)
    c = np.zeros(H)
    sigmoid = lambda v: 1.0 / (1.0 + np.exp(-np.clip(v, -60, 60)))
    for step in tensor:
        gates = np.concatenate([step, h]) @ W + b
        i_ = sigmoid(gates[:H])
        f_ = sigmoid(gates[H:2 * H])
        o_ = sigmoid(gates[2 * H:3 * H])
        g_ = np.tanh(gates[3 * H:])
        c = f_ * c + i_ * g_
        h = o_ * np.tanh(c)
    return float(model["by"] + h @ np.asarray(model["Wy"], float))


def predict_all(vec, bundle):
    x = preprocess(vec["features"], bundle)
    out = {}
    for key, model in bundle["models"].items():
        if model["input"] == "features":
            out[key] = predict_features(model, x)
        else:
            lat, lon = vec["epicentre"]
            out[key] = predict_lstm(model, build_sequence(vec["events"], lat, lon, model))
    return out


# --------------------------------------------------------------------------- #
def check_dataset():
    print("\n1. Data set: is any foreshock larger than its mainshock?")
    mains = pd.read_excel(DATASET, sheet_name="Mainshocks")
    fores = pd.read_excel(DATASET, sheet_name="Foreshocks")

    joined = fores.merge(mains[["Sequence ID", "Recorded mainshock magnitude"]],
                         on="Sequence ID", how="left", validate="many_to_one")
    check("every foreshock belongs to a listed mainshock",
          int(joined["Recorded mainshock magnitude"].isna().sum()) == 0,
          f"{int(joined['Recorded mainshock magnitude'].isna().sum())} orphans")

    over = joined["Magnitude"] > joined["Recorded mainshock magnitude"] + 1e-9
    check("no foreshock exceeds its mainshock", not bool(over.any()),
          f"{int(over.sum())} violations in {len(joined):,} foreshock records")
    equal = (joined["Magnitude"] - joined["Recorded mainshock magnitude"]).abs() <= 1e-9
    print(f"         {int(equal.sum())} foreshocks equal their mainshock, which the "
          f"definition allows; {len(joined) - int(equal.sum()):,} are strictly smaller")

    counted = fores.groupby("Sequence ID").size()
    declared = mains.set_index("Sequence ID")["Foreshocks in window"]
    counted = counted.reindex(declared.index).fillna(0).astype(int)
    check("declared foreshock counts match the rows present",
          bool(counted.equals(declared)),
          f"{int((counted != declared).sum())} sequences disagree")
    check("every window holds at least 3 foreshocks", bool(declared.min() >= 3),
          f"minimum is {int(declared.min())}")
    check("every foreshock falls inside the 14-day window",
          bool(fores["Days before mainshock"].between(0, 14, inclusive="both").all()),
          f"range {fores['Days before mainshock'].min():.3f} "
          f"to {fores['Days before mainshock'].max():.3f} days")
    check("every mainshock reaches M 5.0",
          bool(mains["Recorded mainshock magnitude"].min() >= 5.0),
          f"minimum is {mains['Recorded mainshock magnitude'].min()}")
    print(f"         {len(mains):,} mainshocks, {len(fores):,} foreshock records, "
          f"partitions {dict(mains['Partition'].value_counts())}")
    return mains


def check_models(bundle, vectors):
    print("\n2. Models: do the shipped models reproduce the paper's predictions?")
    worst = {}
    for vec in vectors:
        got = predict_all(vec, bundle)
        for key, value in got.items():
            diff = abs(value - vec["expect"][key])
            worst[key] = max(worst.get(key, 0.0), diff)
    for key, diff in worst.items():
        tol = RF_TOL if key == "random_forest" else PRED_TOL
        check(f"{bundle['models'][key]['label']} replays to within {tol:g}",
              diff <= tol, f"worst difference {diff:.2e}")
    print(f"         {len(vectors) * len(worst):,} predictions recomputed from the "
          "exported weights")


def check_forecasts(bundle, vectors):
    print("\n3. Forecasts: how close are they to the recorded magnitudes?")
    actual = np.array([v["actual"] for v in vectors], float)
    largest = np.array([max(e["mag"] for e in v["events"]) for v in vectors], float)
    preds = {k: np.array([predict_all(v, bundle)[k] for v in vectors], float)
             for k in bundle["models"]}

    climatology = float(bundle["climatology"])
    base = float(np.sqrt(np.mean((actual - climatology) ** 2)))
    rows = []
    print(f"\n  {'model':<16}{'RMSE':>8}{'paper':>8}{'MAE':>8}{'skill %':>9}"
          f"{'within 0.3':>12}{'below max':>11}")
    print(f"  {'Climatology':<16}{base:>8.3f}{bundle['climatology_rmse']:>8.3f}"
          f"{np.mean(np.abs(actual - climatology)):>8.3f}{0.0:>9.1f}"
          f"{100 * np.mean(np.abs(actual - climatology) <= 0.3):>11.1f}%{'':>11}")
    for key, p in preds.items():
        model = bundle["models"][key]
        rmse = float(np.sqrt(np.mean((p - actual) ** 2)))
        skill = 100 * (1 - rmse ** 2 / base ** 2)
        below = 100 * float(np.mean(p < largest - 1e-9))
        print(f"  {model['label']:<16}{rmse:>8.3f}{model['rmse']:>8.3f}"
              f"{np.mean(np.abs(p - actual)):>8.3f}{skill:>9.1f}"
              f"{100 * np.mean(np.abs(p - actual) <= 0.3):>11.1f}%{below:>10.1f}%")
        check(f"{model['label']} scores what the paper reports",
              abs(rmse - model["rmse"]) <= 5e-4,
              f"recomputed {rmse:.4f} against {model['rmse']:.4f} published")
        rows.append((model["label"], rmse, skill))

    best = bundle["models"]["extra_trees"]
    p = preds["extra_trees"]
    check("the leading model never forecasts below the largest foreshock",
          bool((p >= largest - 1e-9).all()),
          f"{int((p < largest - 1e-9).sum())} of {len(p)} forecasts fall below it")

    out = pd.DataFrame({"Largest foreshock": largest,
                        "Recorded mainshock": actual,
                        **{bundle["models"][k]["label"]: np.round(v, 3)
                           for k, v in preds.items()}})
    out["Extra Trees error"] = np.round(out[best["label"]] - actual, 3)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(REPORT, index=False)
    print(f"\n  Per-sequence comparison written to {REPORT.name}")


def main() -> int:
    for path in (DATASET, BUNDLE, VECTORS):
        if not path.exists():
            print(f"missing {path}")
            return 1
    bundle = json.loads(BUNDLE.read_text())
    vectors = json.loads(VECTORS.read_text())["vectors"]

    print("Verification of the foreshock data set and the trained forecasters")
    print(f"  bundle built from {bundle['generated_from']}, "
          f"{bundle['n_train']} training and {bundle['n_test']} test sequences")
    check_dataset()
    check_models(bundle, vectors)
    check_forecasts(bundle, vectors)

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s): " + "; ".join(failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
