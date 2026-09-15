#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 STATISTICAL ANALYSIS AND MACHINE LEARNING PIPELINE
 A Machine Learning Model for Forecasting Mainshock Magnitudes
 Using PHIVOLCS Foreshock Data
================================================================================

One self-contained script. It reads the PHIVOLCS workbook, performs every
statistical analysis the study requires, trains and compares thirteen
forecasting models, and writes all results to a single Microsoft Word document
in APA 7th-edition table format, ready for a paper presentation.

    USAGE
    -----
    python earthquake_analysis.py
    python earthquake_analysis.py --no-models      # statistics only, ~15 s
    python earthquake_analysis.py --no-figures
    python earthquake_analysis.py --quick          # smaller grids, faster
    python earthquake_analysis.py --excel "Other File.xlsx"

    REQUIREMENTS
    ------------
    pandas  numpy  scipy  scikit-learn  statsmodels  openpyxl
    python-docx  matplotlib

    TensorFlow and PyTorch are OPTIONAL.  The recurrent and convolutional
    networks fall back to NumPy implementations contained in this file, so the
    script runs identically on a machine with neither installed.

    OUTPUT
    ------
    outputs/Statistical_Analysis_Tables.docx   all tables + figures, APA format
    outputs/tables/*.csv                       every table as raw numbers
    outputs/figures/*.png                      300 dpi, greyscale-safe

    CONTENTS
    --------
    Part  1   Configuration
    Part  2   Utilities and number formatting
    Part  3   Data loading and cleaning
    Part  4   Descriptive statistics
    Part  5   Inferential statistics
    Part  6   Gutenberg-Richter analysis
    Part  7   Maeda's declustering method
    Part  8   Feature engineering (the 22 features)
    Part  9   Neural networks in NumPy (LSTM, GRU, 1D-CNN)
    Part 10   The model zoo and rolling-origin validation
    Part 11   Evaluation and model comparison
    Part 12   Figures
    Part 13   APA 7 Word export
    Part 14   Main pipeline
================================================================================
"""
from __future__ import annotations

import argparse
import itertools
import math
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingRegressor,
                              HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             cohen_kappa_score, confusion_matrix, f1_score,
                             precision_recall_fscore_support, precision_score,
                             recall_score, roc_auc_score)
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


# =============================================================================
# PART 1.  CONFIGURATION
# -----------------------------------------------------------------------------
# Every threshold the study depends on lives here, so a reviewer can see -- and
# a researcher can change -- the assumptions in one place.
# =============================================================================
class CFG:
    # ---- Paths ----------------------------------------------------------- #
    ROOT = Path(__file__).resolve().parent
    DATA_XLSX = ROOT / "Earthquake Data Sets NEW.xlsx"
    DATA_SHEET = 0
    OUT_DIR = ROOT / "outputs"
    TABLE_DIR = OUT_DIR / "tables"
    FIGURE_DIR = OUT_DIR / "figures"
    DOCX_PATH = OUT_DIR / "Statistical_Analysis_Tables.docx"

    # ---- Reproducibility ------------------------------------------------- #
    SEED = 42

    # ---- Catalogue cleaning ---------------------------------------------- #
    LAT_BOUNDS = (0.0, 25.0)          # Philippine region bounding box
    LON_BOUNDS = (110.0, 140.0)
    DEPTH_BOUNDS = (0.0, 750.0)       # km
    MAG_BOUNDS = (0.0, 10.0)
    DUPLICATE_TIME_TOL_S = 1.0        # same origin time to within a second ...
    DUPLICATE_DIST_TOL_KM = 1.0       # ... and a kilometre is one event twice

    # Distance to the nearest active fault, supplied per event in the workbook
    # (mapped in QGIS, measured with the Haversine formula). The loader
    # recomputes it as a data check; this is the tolerance for agreement.
    SOURCE_DISTANCE_TOL_KM = 1.0
    EARTH_RADIUS_PAPER = 6371.0       # the radius the methodology specifies

    # Order of preference when collapsing Ml / mb / Ms / Mw into one scale.
    # Mw is physically preferred; the rest follow decreasing saturation
    # resistance.  "hierarchy" takes the first available scale as reported;
    # "converted" applies the orthogonal regressions estimated from this
    # catalogue's own co-recorded pairs (see MAGNITUDE_POLICY note in Table 5).
    MAGNITUDE_PREFERENCE = ("Mw", "Ms", "Mb", "Ml")
    MAGNITUDE_POLICY = "hierarchy"

    # ---- Maeda's method -- Hirose et al. (2021), Equations 1-3 ------------ #
    MAEDA_L_SLOPE = 0.5               # log10(L) <= 0.5*Mpre - 1.8
    MAEDA_L_INTERCEPT = -1.8
    MAEDA_T_OFFSET = 0.3              # log10(ta + 0.3) <= (0.17 + 0.85*(M-4))/1.3
    MAEDA_T_A = 0.17
    MAEDA_T_B = 0.85
    MAEDA_T_C = 1.3
    MAEDA_MD = 1.0                    # Ma < Mpre - Md removes only small events

    # ---- Sequence construction ------------------------------------------- #
    MAINSHOCK_MIN_MAG = 5.0           # an event must reach this to be a target
    T_OBS_DAYS = 14.0                 # the study's short-term window
    RADIUS_KM = 100.0                 # spatial radius of the observation window
    MIN_FORESHOCKS = 3                # sparser windows cannot support a b-value
    BACKGROUND_DAYS = 365.0           # reference interval for the beta statistic

    # --- Occurrence forecasting ------------------------------------------- #
    # The magnitude model answers "how large, given that one follows". This
    # answers the other half of Objective 2: whether one follows at all, inside
    # the two-week window the Scope section commits to.
    HORIZON_DAYS = 14.0               # the forecast horizon, looking forward
    OCC_THRESHOLDS = (5.0, 6.0, 7.0)  # "an earthquake of at least this size"
    OCC_RADII = (50.0, 100.0, 200.0)  # ... within this distance of the anchor
    OCC_THIN_DAYS = 1.0               # anchors closer than this are one anchor
    OCC_MIN_POSITIVES = 25            # below this a rate is reported, not modelled

    MAG_CLASS_EDGES = (5.0, 6.0, 7.0, 10.0)
    MAG_CLASS_LABELS = ("Moderate (5.0-5.9)", "Strong (6.0-6.9)", "Major (>=7.0)")
    DEPTH_CLASS_EDGES = (0.0, 70.0, 300.0, 750.0)
    DEPTH_CLASS_LABELS = ("Shallow (<70 km)", "Intermediate (70-300 km)",
                          "Deep (>300 km)")

    # ---- Seismic energy --------------------------------------------------- #
    # The thesis (Table 1) writes Energy = sqrt( sum 10^(12 + 1.8*Mi) ).
    # Wang et al. (2023) and the classical Gutenberg-Richter energy relation
    # use (11.8, 1.5).  The thesis form is the default so the reported numbers
    # match the written methodology; change this to reproduce the literature.
    ENERGY_COEFFS = (12.0, 1.8)

    # ---- Gutenberg-Richter ------------------------------------------------ #
    MAG_BIN = 0.1                     # catalogue magnitudes reported to 0.1
    GFT_TARGET_R = 90.0               # goodness-of-fit level, Wiemer & Wyss (2000)
    MC_MIN_EVENTS = 25

    # ---- Model training --------------------------------------------------- #
    SPLIT_FRACTIONS = (0.60, 0.20, 0.20)   # chronological, never shuffled
    CV_FOLDS = 5                            # rolling-origin validation folds

    RF_GRID = {
        "n_estimators": [300, 600],
        "max_depth": [None, 8, 16],
        "min_samples_leaf": [1, 2, 4],
        "max_features": ["sqrt", 0.5],
    }
    RF_GRID_QUICK = {
        "n_estimators": [300],
        "max_depth": [None, 8],
        "min_samples_leaf": [1, 2],
        "max_features": ["sqrt"],
    }

    # Sequence models (LSTM / GRU / CNN) operate on the raw event stream.
    SEQ_LEN = 10                      # most recent foreshocks fed to the net
    NN_UNITS = 32
    NN_EPOCHS = 300
    NN_LR = 0.01
    NN_PATIENCE = 40
    CNN_FILTERS = 24
    CNN_KERNEL = 3

    # ---- Reporting -------------------------------------------------------- #
    ALPHA = 0.05
    BOOTSTRAP_N = 2000
    LANDIS_KOCH = ((0.00, "None beyond chance"), (0.20, "Slight"), (0.40, "Fair"),
                   (0.60, "Moderate"), (0.80, "Substantial"), (1.01, "Almost perfect"))


for _d in (CFG.OUT_DIR, CFG.TABLE_DIR, CFG.FIGURE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# PART 2.  UTILITIES AND NUMBER FORMATTING
# =============================================================================
EARTH_RADIUS_KM = 6371.0088
LOG10_E = np.log10(np.e)
# The workbook has appeared in two shapes. The 2026 revision adds the nearest
# active fault: its coordinates and the distance to it. Both are read here so a
# re-run against either file produces the same catalogue columns, with the
# source fields simply absent in the older one.
RAW_COLUMNS_BASE = ["No", "Year", "Month", "Day", "Hour", "Minute", "Second",
                    "Latitude", "Longitude", "Depth", "Ml", "Mb", "Ms", "Mw"]
RAW_COLUMNS_SOURCE = ["No", "Year", "Month", "Day", "Hour", "Minute", "Second",
                      "Latitude", "Longitude", "SrcLat", "SrcLon", "SrcDistKm",
                      "Depth", "Ml", "Mb", "Ms", "Mw"]
MAG_COLUMNS = ["Ml", "Mb", "Ms", "Mw"]
SOURCE_COLUMNS = ["SrcLat", "SrcLon", "SrcDistKm"]


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km; accepts scalars or broadcastable arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def fmt_p(p) -> str:
    """APA p-value: no leading zero, three decimals, '< .001' at the floor."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"{p:.3f}".replace("0.", ".", 1)


def fmt_num(value, decimals: int = 2, strip_zero: bool = False) -> str:
    """Format one cell, rendering missing data as an em dash.

    `strip_zero` drops the leading zero for statistics bounded by +/-1
    (correlations, proportions, kappa), as APA requires.
    """
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, np.integer):
        value = int(value)
    if isinstance(value, (bool, np.bool_)):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if math.isnan(value):
            return "—"
        if math.isinf(value):
            return "∞" if value > 0 else "−∞"
        if value != 0 and (abs(value) < 10 ** -decimals or abs(value) >= 1e6):
            text = f"{value:.{max(decimals, 2)}e}"
        else:
            text = f"{value:,.{decimals}f}"
        return re.sub(r"^(-?)0\.", r"\1.", text) if strip_zero else text
    return str(value)


def format_frame(df, decimals=2, p_columns=(), strip_zero_columns=(), int_columns=()):
    """String-valued copy of `df`, ready to be written into a Word table.

    `decimals` accepts an int for every column, or a dict of column -> int.
    """
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        d = decimals.get(col, 2) if isinstance(decimals, dict) else decimals
        if col in p_columns:
            out[col] = df[col].map(fmt_p)
        elif col in int_columns:
            out[col] = df[col].map(
                lambda v: "—" if pd.isna(v) else f"{int(round(float(v))):,}")
        else:
            strip = col in strip_zero_columns
            out[col] = df[col].map(lambda v, d=d, s=strip: fmt_num(v, d, s))
    return out


def describe_series(series) -> dict:
    """Full descriptive battery with a confidence interval for the mean."""
    x = pd.to_numeric(series, errors="coerce").dropna().to_numpy()
    n = x.size
    if n == 0:
        return {"n": 0}
    sd = x.std(ddof=1) if n > 1 else np.nan
    se = sd / np.sqrt(n) if n > 1 else np.nan
    crit = stats.t.ppf(1 - CFG.ALPHA / 2, n - 1) if n > 1 else np.nan
    return {
        "n": n, "M": x.mean(), "SD": sd, "SE": se,
        "95% CI LL": x.mean() - crit * se if n > 1 else np.nan,
        "95% CI UL": x.mean() + crit * se if n > 1 else np.nan,
        "Mdn": np.median(x), "Min": x.min(), "Max": x.max(),
        "Range": x.max() - x.min(),
        "Q1": np.percentile(x, 25), "Q3": np.percentile(x, 75),
        "IQR": np.percentile(x, 75) - np.percentile(x, 25),
        "Skew": stats.skew(x, bias=False) if n > 2 else np.nan,
        "Kurt": stats.kurtosis(x, bias=False) if n > 3 else np.nan,
    }


def effect_label(value: float) -> str:
    """Cohen's benchmarks for a variance-explained effect size."""
    if not np.isfinite(value):
        return "—"
    if value < .01:
        return "Negligible"
    if value < .06:
        return "Small"
    if value < .14:
        return "Medium"
    return "Large"


def r_label(r: float) -> str:
    """Cohen's benchmarks for a correlation."""
    if not np.isfinite(r):
        return "—"
    if r < .10:
        return "Negligible"
    if r < .30:
        return "Small"
    if r < .50:
        return "Medium"
    return "Large"


def kappa_label(k: float) -> str:
    """Landis & Koch benchmarks, as listed in the thesis methodology."""
    if not np.isfinite(k):
        return "—"
    if k < 0:
        return "Poor (worse than chance)"
    for upper, name in CFG.LANDIS_KOCH:
        if k <= upper:
            return name
    return "Almost perfect"


# =============================================================================
# PART 3.  DATA LOADING AND CLEANING
# -----------------------------------------------------------------------------
# The workbook carries a two-row banner (grouped headings on one row, field
# names on the next) and repeats the field-name row inside the data block, so
# the sheet is read without a header and every row that fails to parse as a
# year is dropped.  Each cleaning decision is logged to an audit trail that
# becomes a Word table -- a reviewer can see exactly what each rule removed.
# =============================================================================
class CleaningAudit:
    """Ordered record of how many events each cleaning rule removed."""

    def __init__(self):
        self.rows = []

    def log(self, step, before, after, note=""):
        self.rows.append({"Step": step, "Records before": before,
                          "Removed": before - after, "Records retained": after,
                          "Note": note})

    def to_frame(self):
        return pd.DataFrame(self.rows)


def read_raw(path=None, sheet=None) -> pd.DataFrame:
    """Return the sheet as numeric columns, banner and in-body headers stripped."""
    path = Path(path) if path else CFG.DATA_XLSX
    sheet = CFG.DATA_SHEET if sheet is None else sheet
    if not path.exists():
        raise SystemExit(f"Data file not found: {path}")
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    # Data rows are the ones whose first two cells parse as an event number and
    # a year, which drops the banner and any header repeated inside the block
    # without depending on how many banner rows this edition happens to have.
    year = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
    number = pd.to_numeric(raw.iloc[:, 0], errors="coerce")
    data = raw[year.notna() & number.notna()].copy()

    columns = RAW_COLUMNS_SOURCE if data.shape[1] >= len(RAW_COLUMNS_SOURCE) else RAW_COLUMNS_BASE
    data = data.iloc[:, :len(columns)]
    data.columns = columns
    return data.apply(pd.to_numeric, errors="coerce").reset_index(drop=True)


def _build_datetime(df) -> pd.Series:
    """Compose an origin time, tolerating out-of-range hour/minute/second fields.

    Some legacy PHIVOLCS rows carry an hour of 24-27 (a local-time carry-over).
    Rather than discarding the event, the date is taken as a day floor and the
    whole clock added back as a timedelta, rolling the extra hours into the
    following day.
    """
    base = pd.to_datetime(dict(year=df["Year"], month=df["Month"], day=df["Day"]),
                          errors="coerce")
    offset = (pd.to_timedelta(df["Hour"].fillna(0), unit="h")
              + pd.to_timedelta(df["Minute"].fillna(0), unit="m")
              + pd.to_timedelta(df["Second"].fillna(0), unit="s"))
    return base + offset


def _orthogonal_regression(x, y) -> dict:
    """Major-axis (orthogonal) regression of y on x.

    Ordinary least squares assumes an error-free predictor, which is wrong for
    magnitude-scale conversion where both scales carry comparable uncertainty;
    the major axis is the standard remedy in seismological practice.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size < 10:
        return {}
    sx, sy = x.std(ddof=1), y.std(ddof=1)
    sxy = np.cov(x, y, ddof=1)[0, 1]
    if sxy == 0:
        return {}
    slope = (sy**2 - sx**2 + np.sqrt((sy**2 - sx**2) ** 2 + 4 * sxy**2)) / (2 * sxy)
    intercept = y.mean() - slope * x.mean()
    resid = y - (slope * x + intercept)
    return {"n": x.size, "slope": slope, "intercept": intercept,
            "r": float(np.corrcoef(x, y)[0, 1]),
            "see": float(resid.std(ddof=2)) if x.size > 2 else np.nan}


def magnitude_conversions(df) -> pd.DataFrame:
    """Orthogonal regressions between every co-recorded pair of magnitude scales.

    These quantify how far the four scales can legitimately be pooled.  Pairs
    the catalogue rarely co-reports (notably Mw against anything) produce a
    small n, and the table reports that rather than hiding it.
    """
    rows = []
    for i, a in enumerate(MAG_COLUMNS):
        for b in MAG_COLUMNS[i + 1:]:
            pair = df[[a, b]].dropna()
            fit = _orthogonal_regression(pair[a].to_numpy(), pair[b].to_numpy())
            if not fit:
                rows.append({"Predictor": a, "Response": b, "n": len(pair),
                             "Slope": np.nan, "Intercept": np.nan, "r": np.nan,
                             "SEE": np.nan, "Usable": "No (n < 10)"})
                continue
            rows.append({"Predictor": a, "Response": b, "n": fit["n"],
                         "Slope": fit["slope"], "Intercept": fit["intercept"],
                         "r": fit["r"], "SEE": fit["see"],
                         "Usable": "Yes" if fit["n"] >= 50 else "Indicative only (n < 50)"})
    return pd.DataFrame(rows)


def _preferred_magnitude(df):
    """First available scale in the configured preference order."""
    mag = pd.Series(np.nan, index=df.index, dtype=float)
    scale = pd.Series(pd.NA, index=df.index, dtype="object")
    for name in CFG.MAGNITUDE_PREFERENCE:
        take = mag.isna() & df[name].notna()
        mag.loc[take] = df.loc[take, name]
        scale.loc[take] = name
    return mag, scale


def _converted_magnitude(df, relations):
    """Homogenise to an Mw-equivalent using the catalogue's own relations.

    Where no usable relation to Mw exists the value falls back to the preferred
    scale unchanged, and the returned scale label records that.
    """
    mag, scale = _preferred_magnitude(df)
    usable = relations[relations["Usable"] == "Yes"]
    for source in ("Ms", "Mb", "Ml"):
        rel = usable[(usable["Predictor"] == source) & (usable["Response"] == "Mw")]
        if rel.empty:
            continue
        slope, intercept = float(rel.iloc[0]["Slope"]), float(rel.iloc[0]["Intercept"])
        take = df["Mw"].isna() & df[source].notna() & (scale == source)
        mag.loc[take] = slope * df.loc[take, source] + intercept
        scale.loc[take] = f"{source}->Mw"
    return mag, scale


def _drop_duplicates(df) -> pd.DataFrame:
    """Collapse near-identical origins, keeping the larger reported magnitude."""
    t = (df["datetime"].astype("int64") / 1e9).to_numpy()
    lat, lon = df["Latitude"].to_numpy(), df["Longitude"].to_numpy()
    mag = df["Magnitude"].to_numpy()
    keep = np.ones(len(df), dtype=bool)
    for i in range(len(df)):
        if not keep[i]:
            continue
        j = i + 1
        while j < len(df) and (t[j] - t[i]) <= CFG.DUPLICATE_TIME_TOL_S:
            if keep[j] and haversine_km(lat[i], lon[i], lat[j], lon[j]) <= CFG.DUPLICATE_DIST_TOL_KM:
                if mag[j] > mag[i]:
                    keep[i] = False
                    break
                keep[j] = False
            j += 1
    return df[keep]


def load_catalogue(path=None, policy=None):
    """Return `(clean_catalogue, audit_frame, conversion_relations)`.

    The catalogue is sorted by origin time and carries the working columns
    `datetime`, `Magnitude`, `MagScale`, `Latitude`, `Longitude`, `Depth`, plus
    the depth and magnitude class factors used downstream.
    """
    policy = policy or CFG.MAGNITUDE_POLICY
    audit = CleaningAudit()

    df = read_raw(path)
    n0 = len(df)
    audit.log("Records extracted from workbook", n0, n0,
              "Banner and repeated header rows removed")

    df["datetime"] = _build_datetime(df)
    before, df = len(df), df[df["datetime"].notna()]
    audit.log("Valid origin date/time", before, len(df),
              "Year/month/day must form a real calendar date")

    before = len(df)
    df = df[df["Latitude"].between(*CFG.LAT_BOUNDS)
            & df["Longitude"].between(*CFG.LON_BOUNDS)]
    audit.log("Epicentre inside study region", before, len(df),
              f"lat {CFG.LAT_BOUNDS[0]}-{CFG.LAT_BOUNDS[1]}, "
              f"lon {CFG.LON_BOUNDS[0]}-{CFG.LON_BOUNDS[1]}")

    before = len(df)
    df = df[df["Depth"].between(*CFG.DEPTH_BOUNDS)]
    audit.log("Hypocentral depth in range", before, len(df),
              f"0-{CFG.DEPTH_BOUNDS[1]:.0f} km")

    before = len(df)
    df = df[df[MAG_COLUMNS].notna().any(axis=1)]
    audit.log("At least one reported magnitude", before, len(df),
              "Ml, mb, Ms or Mw present")

    relations = magnitude_conversions(df)
    mag, scale = (_converted_magnitude(df, relations) if policy == "converted"
                  else _preferred_magnitude(df))
    df = df.assign(Magnitude=mag, MagScale=scale)

    before = len(df)
    df = df[df["Magnitude"].between(*CFG.MAG_BOUNDS)]
    audit.log("Working magnitude in range", before, len(df),
              f"policy = '{policy}', preference "
              f"{' > '.join(CFG.MAGNITUDE_PREFERENCE)}")

    if set(SOURCE_COLUMNS).issubset(df.columns):
        before = len(df)
        df = df[df[SOURCE_COLUMNS].notna().all(axis=1) & (df["SrcDistKm"] >= 0)]
        audit.log("Nearest active fault recorded", before, len(df),
                  "Source coordinates and distance present and non-negative")

    df = df.sort_values("datetime", kind="mergesort").reset_index(drop=True)
    before = len(df)
    df = _drop_duplicates(df)
    audit.log("Duplicate origins collapsed", before, len(df),
              f"within {CFG.DUPLICATE_TIME_TOL_S:.0f} s and "
              f"{CFG.DUPLICATE_DIST_TOL_KM:.0f} km")

    df["DepthClass"] = pd.cut(df["Depth"], bins=CFG.DEPTH_CLASS_EDGES,
                              labels=CFG.DEPTH_CLASS_LABELS, include_lowest=True)
    df["MagClass"] = pd.cut(df["Magnitude"], bins=CFG.MAG_CLASS_EDGES,
                            labels=CFG.MAG_CLASS_LABELS, right=False)
    df["Year"] = df["datetime"].dt.year
    df["Decade"] = (df["Year"] // 10) * 10
    return df.reset_index(drop=True), audit.to_frame(), relations


# =============================================================================
# PART 4.  DESCRIPTIVE STATISTICS
# =============================================================================
def source_distance_check(df) -> pd.DataFrame:
    """Recompute the supplied fault distance and report the agreement.

    The workbook carries a distance to the nearest active fault, mapped in QGIS
    and measured with the Haversine formula. It is used as given, because it is
    the authors' own measurement against their fault layer, but a value that
    cannot be reproduced from the two coordinate pairs beside it would be a
    transcription error worth catching rather than modelling.
    """
    recomputed = haversine_km(df["Latitude"], df["Longitude"],
                              df["SrcLat"], df["SrcLon"])
    diff = (recomputed - df["SrcDistKm"]).abs()
    within = diff <= CFG.SOURCE_DISTANCE_TOL_KM
    d = describe_series(df["SrcDistKm"])
    return pd.DataFrame([
        {"Quantity": "Events with a nearest-fault distance", "Value": f"{len(df):,}"},
        {"Quantity": "Distinct fault source points", "Value": f"{df[['SrcLat', 'SrcLon']].drop_duplicates().shape[0]:,}"},
        {"Quantity": "Distance, M (SD) in km", "Value": f"{d['M']:.2f} ({d['SD']:.2f})"},
        {"Quantity": "Distance, median in km", "Value": f"{d['Mdn']:.2f}"},
        {"Quantity": "Distance range in km", "Value": f"{d['Min']:.2f} to {d['Max']:.2f}"},
        {"Quantity": "Events within 25 km of a fault", "Value": f"{int((df['SrcDistKm'] <= 25).sum()):,} ({100 * (df['SrcDistKm'] <= 25).mean():.1f}%)"},
        {"Quantity": "Median recomputation difference in km", "Value": f"{diff.median():.4f}"},
        {"Quantity": "Maximum recomputation difference in km", "Value": f"{diff.max():.3f}"},
        {"Quantity": f"Agreement within {CFG.SOURCE_DISTANCE_TOL_KM:.0f} km",
         "Value": f"{int(within.sum()):,} of {len(df):,} ({100 * within.mean():.2f}%)"},
    ])


def catalogue_overview(df, raw_n) -> pd.DataFrame:
    """One-row-per-attribute summary of what the working catalogue contains."""
    years = (df["datetime"].max() - df["datetime"].min()).days / 365.25
    rows = [
        ("Records in source workbook", f"{raw_n:,}"),
        ("Events retained after cleaning", f"{len(df):,}"),
        ("Retention rate", f"{100 * len(df) / raw_n:.1f}%"),
        ("First event", df["datetime"].min().strftime("%d %b %Y %H:%M:%S")),
        ("Last event", df["datetime"].max().strftime("%d %b %Y %H:%M:%S")),
        ("Temporal span", f"{years:.1f} years"),
        ("Mean annual event rate", f"{len(df) / years:,.1f} events/year"),
        ("Latitude range (°N)", f"{df['Latitude'].min():.2f} to {df['Latitude'].max():.2f}"),
        ("Longitude range (°E)", f"{df['Longitude'].min():.2f} to {df['Longitude'].max():.2f}"),
        ("Depth range (km)", f"{df['Depth'].min():.1f} to {df['Depth'].max():.1f}"),
        ("Working magnitude range", f"{df['Magnitude'].min():.1f} to {df['Magnitude'].max():.1f}"),
        ("Events M ≥ 5.0", f"{(df['Magnitude'] >= 5.0).sum():,}"),
        ("Events M ≥ 6.0", f"{(df['Magnitude'] >= 6.0).sum():,}"),
        ("Events M ≥ 7.0", f"{(df['Magnitude'] >= 7.0).sum():,}"),
    ]
    return pd.DataFrame(rows, columns=["Catalogue attribute", "Value"])


def magnitude_scale_profile(df) -> pd.DataFrame:
    """Availability and distribution of each reported magnitude scale.

    The four scales are not interchangeable and are not reported for the same
    events; this table is the evidence for how the working scale was chosen.
    """
    used = df["MagScale"].value_counts()
    rows = []
    for col in MAG_COLUMNS:
        d = describe_series(df[col])
        rows.append({"Magnitude scale": col, "n reported": d.get("n", 0),
                     "% of catalogue": 100 * d.get("n", 0) / len(df),
                     "n adopted as working scale": int(used.get(col, 0)),
                     "M": d.get("M", np.nan), "SD": d.get("SD", np.nan),
                     "Mdn": d.get("Mdn", np.nan), "Min": d.get("Min", np.nan),
                     "Max": d.get("Max", np.nan), "Skew": d.get("Skew", np.nan),
                     "Kurt": d.get("Kurt", np.nan)})
    return pd.DataFrame(rows)


def scale_coverage(df) -> pd.DataFrame:
    """How often the scales are co-reported -- the limit on any homogenisation."""
    flags = df[MAG_COLUMNS].notna()
    combo = flags.apply(
        lambda r: " + ".join(c for c, v in zip(MAG_COLUMNS, r) if v) or "none", axis=1)
    counts = combo.value_counts()
    return pd.DataFrame({"Scales reported together": counts.index,
                         "n events": counts.to_numpy(),
                         "% of catalogue": 100 * counts.to_numpy() / len(df)})


def parameter_descriptives(df, columns=None):
    labels = {"Magnitude": "Magnitude (working scale)", "Depth": "Focal depth (km)",
              "Latitude": "Latitude (deg N)", "Longitude": "Longitude (deg E)",
              "SrcDistKm": "Distance to nearest fault (km)"}
    if columns is None:
        columns = ["Magnitude", "Depth", "Latitude", "Longitude"]
        if "SrcDistKm" in df.columns:
            columns.append("SrcDistKm")
    return pd.DataFrame([{"Variable": labels.get(c, c), **describe_series(df[c])}
                         for c in columns])


def magnitude_bins(df):
    """Bin edges that start at the catalogue's own reporting threshold.

    PHIVOLCS publishes its bulletin from M 4.0 upward, so the conventional
    "micro" and "minor" classes are empty by construction.  Carrying empty
    classes into a chi-square or a percentage column is misleading, so the
    lowest occupied half-unit sets the floor.
    """
    floor = np.floor(df["Magnitude"].min() * 2) / 2
    edges = sorted({e for e in [floor, floor + 0.5, 5.0, 5.5, 6.0, 7.0, 10.0]
                    if e >= floor})
    labels = [f"≥ {lo:.1f} (Major)" if hi >= 10 else f"{lo:.1f}–{hi - 0.1:.1f}"
              for lo, hi in zip(edges[:-1], edges[1:])]
    return edges, labels


def _frequency(series, label) -> pd.DataFrame:
    counts = series.value_counts(dropna=False).sort_index()
    out = pd.DataFrame({label: [str(i) for i in counts.index],
                        "f": counts.to_numpy(),
                        "%": 100 * counts.to_numpy() / counts.sum()})
    out["Cumulative %"] = out["%"].cumsum()
    return out


def frequency_by_magnitude_class(df) -> pd.DataFrame:
    edges, labels = magnitude_bins(df)
    binned = pd.cut(df["Magnitude"], bins=edges, labels=labels, right=False)
    out = _frequency(binned, "Magnitude class")
    out["Mdn depth (km)"] = (df.groupby(binned, observed=False)["Depth"]
                             .median().reindex(labels).to_numpy())
    return out


def frequency_by_decade(df) -> pd.DataFrame:
    g = df.groupby("Decade")
    return pd.DataFrame({
        "Decade": [f"{int(d)}s" for d in g.size().index],
        "f": g.size().to_numpy(), "%": 100 * g.size().to_numpy() / len(df),
        "M (magnitude)": g["Magnitude"].mean().to_numpy(),
        "SD": g["Magnitude"].std(ddof=1).to_numpy(),
        "Max": g["Magnitude"].max().to_numpy(),
        "Mdn depth (km)": g["Depth"].median().to_numpy(),
        "f (M ≥ 6.0)": g["Magnitude"].apply(lambda s: int((s >= 6).sum())).to_numpy()})


def frequency_by_depth_class(df) -> pd.DataFrame:
    out = _frequency(df["DepthClass"], "Depth class")
    g = df.groupby("DepthClass", observed=False)["Magnitude"]
    order = list(CFG.DEPTH_CLASS_LABELS)
    out["M (magnitude)"] = g.mean().reindex(order).to_numpy()
    out["SD"] = g.std(ddof=1).reindex(order).to_numpy()
    out["Max"] = g.max().reindex(order).to_numpy()
    return out


def crosstab_magnitude_depth(df):
    """Observed counts (with row %) of magnitude class by depth class."""
    edges, labels = magnitude_bins(df)
    mag = pd.cut(df["Magnitude"], bins=edges, labels=labels, right=False)
    observed = (pd.crosstab(mag, df["DepthClass"], dropna=False)
                .reindex(index=labels, columns=list(CFG.DEPTH_CLASS_LABELS))
                .fillna(0).astype(int))
    display = observed.copy().astype(object)
    for i in observed.index:
        total = observed.loc[i].sum()
        for j in observed.columns:
            pct = 100 * observed.loc[i, j] / total if total else 0
            display.loc[i, j] = f"{observed.loc[i, j]:,} ({pct:.1f}%)"
    display["Total"] = [f"{observed.loc[i].sum():,}" for i in observed.index]
    display = display.reset_index()
    display.columns = ["Magnitude class"] + list(display.columns[1:])
    return observed, display


def annual_series(df) -> pd.DataFrame:
    """Per-year counts and maxima -- the input to the temporal trend tests."""
    g = df.groupby("Year")
    return pd.DataFrame({
        "Year": g.size().index.astype(int), "Count": g.size().to_numpy(),
        "MaxMag": g["Magnitude"].max().to_numpy(),
        "MeanMag": g["Magnitude"].mean().to_numpy(),
        "CountM6": g["Magnitude"].apply(lambda s: int((s >= 6).sum())).to_numpy()})


# =============================================================================
# PART 5.  INFERENTIAL STATISTICS
# -----------------------------------------------------------------------------
# Every test reports an effect size alongside the p-value.  With n in the tens
# of thousands, significance is close to guaranteed and the effect size is the
# only part of the result that carries meaning -- a point the write-up should
# make explicitly.
# =============================================================================
def normality_tests(df, columns, max_shapiro=5000, seed=CFG.SEED) -> pd.DataFrame:
    """Shapiro-Wilk, D'Agostino-Pearson and Kolmogorov-Smirnov per variable.

    Shapiro-Wilk is undefined above 5,000 observations, so it runs on a random
    subsample of that size and the table says so.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for col in columns:
        x = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy()
        n = x.size
        sample = x if n <= max_shapiro else rng.choice(x, max_shapiro, replace=False)
        try:
            sw_w, sw_p = stats.shapiro(sample)
        except Exception:
            sw_w, sw_p = np.nan, np.nan
        k2, k2_p = stats.normaltest(x) if n > 7 else (np.nan, np.nan)
        ks_d, ks_p = stats.kstest((x - x.mean()) / x.std(ddof=1), "norm")
        rows.append({"Variable": col, "n": n, "Shapiro–Wilk W": sw_w, "p (S–W)": sw_p,
                     "D'Agostino K²": k2, "p (K²)": k2_p, "K–S D": ks_d, "p (K–S)": ks_p,
                     "Skewness": stats.skew(x, bias=False),
                     "Kurtosis": stats.kurtosis(x, bias=False),
                     "Decision at α = .05": ("Reject normality"
                                             if (np.isnan(sw_p) or sw_p < CFG.ALPHA)
                                             else "Retain normality")})
    return pd.DataFrame(rows)


def correlation_matrix(df, columns, method="pearson") -> pd.DataFrame:
    """Lower-triangular r matrix with significance stars; diagonal left blank."""
    data = df[list(columns)].apply(pd.to_numeric, errors="coerce").dropna()
    fn = stats.pearsonr if method == "pearson" else stats.spearmanr
    out = pd.DataFrame("", index=list(columns), columns=list(columns), dtype=object)
    for i, a in enumerate(columns):
        for j, b in enumerate(columns):
            if j > i:
                out.loc[a, b] = ""
            elif i == j:
                out.loc[a, b] = "—"
            else:
                r, p = fn(data[a], data[b])
                star = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""
                out.loc[a, b] = f"{r:.3f}".replace("0.", ".", 1) + star
    out.insert(0, "Variable", [f"{i + 1}. {c}" for i, c in enumerate(columns)])
    out.columns = ["Variable"] + [str(i + 1) for i in range(len(columns))]
    return out.reset_index(drop=True)


def correlation_detail(df, columns) -> pd.DataFrame:
    """Every pair with Pearson r, Spearman rho, p, n and a magnitude label."""
    data = df[list(columns)].apply(pd.to_numeric, errors="coerce").dropna()
    rows = []
    for a, b in itertools.combinations(columns, 2):
        r, rp = stats.pearsonr(data[a], data[b])
        rho, sp = stats.spearmanr(data[a], data[b])
        rows.append({"Variable pair": f"{a} – {b}", "n": len(data), "Pearson r": r,
                     "p (r)": rp, "Spearman ρ": rho, "p (ρ)": sp, "r²": r ** 2,
                     "Strength (Cohen)": r_label(abs(r))})
    return pd.DataFrame(rows)


def _welch_anova(groups):
    """Welch's heteroscedastic F with its Satterthwaite denominator df."""
    n = np.array([g.size for g in groups], float)
    m = np.array([g.mean() for g in groups])
    v = np.array([g.var(ddof=1) for g in groups])
    w = n / v
    m_bar = (w * m).sum() / w.sum()
    k = len(groups)
    lam = (((1 - w / w.sum()) ** 2) / (n - 1)).sum()
    f = ((w * (m - m_bar) ** 2).sum() / (k - 1)) / (1 + 2 * (k - 2) / (k**2 - 1) * lam)
    df2 = (k**2 - 1) / (3 * lam)
    return f, df2, stats.f.sf(f, k - 1, df2)


def group_comparison(df, value, group):
    """Descriptives per group plus omnibus ANOVA / Welch / Kruskal-Wallis.

    All three omnibus tests are reported because the catalogue violates both
    normality and homogeneity of variance; Welch and Kruskal-Wallis are the
    defensible ones and the classical F is included only for comparison.
    """
    data = df[[value, group]].dropna()
    grouped = list(data.groupby(group, observed=True))
    groups = [g[value].to_numpy() for _, g in grouped]
    names = [str(k) for k, _ in grouped]

    desc = pd.DataFrame({"Group": names, "n": [g.size for g in groups],
                         "M": [g.mean() for g in groups],
                         "SD": [g.std(ddof=1) for g in groups],
                         "Mdn": [np.median(g) for g in groups],
                         "Min": [g.min() for g in groups],
                         "Max": [g.max() for g in groups]})

    f_stat, f_p = stats.f_oneway(*groups)
    w_f, w_df2, w_p = _welch_anova(groups)
    h_stat, h_p = stats.kruskal(*groups)
    lev_stat, lev_p = stats.levene(*groups, center="median")

    pooled = np.concatenate(groups)
    n_total, k, grand = pooled.size, len(groups), pooled.mean()
    ss_between = sum(g.size * (g.mean() - grand) ** 2 for g in groups)
    ss_total = ((pooled - grand) ** 2).sum()
    eta2 = ss_between / ss_total
    omega2 = ((ss_between - (k - 1) * (ss_total - ss_between) / (n_total - k))
              / (ss_total + (ss_total - ss_between) / (n_total - k)))
    epsilon2 = (h_stat - k + 1) / (n_total - k)

    tests = pd.DataFrame([
        {"Test": "Levene (median-centred)", "Statistic": lev_stat,
         "df": f"{k - 1}, {n_total - k}", "p": lev_p, "Effect size": np.nan,
         "Effect size index": "—",
         "Interpretation": "Variances unequal" if lev_p < CFG.ALPHA else "Variances homogeneous"},
        {"Test": "One-way ANOVA", "Statistic": f_stat, "df": f"{k - 1}, {n_total - k}",
         "p": f_p, "Effect size": eta2, "Effect size index": "η²",
         "Interpretation": effect_label(eta2)},
        {"Test": "Welch's ANOVA", "Statistic": w_f, "df": f"{k - 1}, {w_df2:.1f}",
         "p": w_p, "Effect size": omega2, "Effect size index": "ω²",
         "Interpretation": effect_label(omega2)},
        {"Test": "Kruskal–Wallis H", "Statistic": h_stat, "df": str(k - 1), "p": h_p,
         "Effect size": epsilon2, "Effect size index": "ε²",
         "Interpretation": effect_label(epsilon2)}])
    return desc, tests


def _cliffs_delta(a, b, max_n=4000, seed=CFG.SEED) -> float:
    """Non-parametric effect size; subsampled when the cross-product is large."""
    rng = np.random.default_rng(seed)
    if a.size > max_n:
        a = rng.choice(a, max_n, replace=False)
    if b.size > max_n:
        b = rng.choice(b, max_n, replace=False)
    greater = (a[:, None] > b[None, :]).sum()
    less = (a[:, None] < b[None, :]).sum()
    return (greater - less) / (a.size * b.size)


def dunn_posthoc(df, value, group) -> pd.DataFrame:
    """Dunn's test on rank sums with a Bonferroni-adjusted p, plus Cliff's delta.

    Implemented here rather than pulled from scikit-posthocs so the script has
    no dependency outside the SciPy stack.
    """
    data = df[[value, group]].dropna()
    data = data.assign(_rank=stats.rankdata(data[value]))
    grouped = data.groupby(group, observed=True)
    names = [str(k) for k in grouped.groups]
    n = grouped.size().to_numpy().astype(float)
    mean_rank = grouped["_rank"].mean().to_numpy()
    N = len(data)

    _, tie_counts = np.unique(data[value], return_counts=True)
    ties = (tie_counts ** 3 - tie_counts).sum()
    sigma2 = (N * (N + 1) / 12) - ties / (12 * (N - 1))

    comparisons = list(itertools.combinations(range(len(names)), 2))
    rows = []
    for i, j in comparisons:
        z = (mean_rank[i] - mean_rank[j]) / np.sqrt(sigma2 * (1 / n[i] + 1 / n[j]))
        p = 2 * stats.norm.sf(abs(z))
        p_adj = min(1.0, p * len(comparisons))
        a = data.loc[data[group].astype(str) == names[i], value].to_numpy()
        b = data.loc[data[group].astype(str) == names[j], value].to_numpy()
        rows.append({"Comparison": f"{names[i]} vs. {names[j]}",
                     "Mean rank difference": mean_rank[i] - mean_rank[j], "z": z,
                     "p": p, "p (Bonferroni)": p_adj, "Cliff's δ": _cliffs_delta(a, b),
                     "Decision": "Significant" if p_adj < CFG.ALPHA else "Not significant"})
    return pd.DataFrame(rows)


def chi_square_independence(observed):
    """Pearson chi-square with Cramér's V and a standardised-residual table.

    Rows or columns with a zero margin are dropped first: they contribute a zero
    expected frequency, for which the statistic is undefined.
    """
    observed = observed.loc[observed.sum(axis=1) > 0, observed.sum(axis=0) > 0]
    chi2, p, dof, expected = stats.chi2_contingency(observed.to_numpy())
    n = observed.to_numpy().sum()
    v = np.sqrt(chi2 / (n * (min(observed.shape) - 1)))
    small = 0.1 / np.sqrt(max(dof, 1))
    label = ("Negligible" if v < small else "Small" if v < 2 * small
             else "Medium" if v < 4 * small else "Large")
    result = pd.DataFrame([{
        "Test": "Pearson χ² test of independence", "χ²": chi2, "df": dof, "N": int(n),
        "p": p, "Cramér's V": v, "Effect size": label,
        "Decision at α = .05": "Reject independence" if p < CFG.ALPHA else "Retain independence"}])

    resid = ((observed.to_numpy() - expected)
             / np.sqrt(expected
                       * (1 - observed.sum(axis=1).to_numpy()[:, None] / n)
                       * (1 - observed.sum(axis=0).to_numpy()[None, :] / n)))
    resid_df = pd.DataFrame(resid, index=observed.index,
                            columns=observed.columns).round(2).reset_index()
    resid_df.columns = ["Magnitude class"] + list(resid_df.columns[1:])
    return result, resid_df


def mann_kendall(x) -> dict:
    """Mann-Kendall trend test with the standard tie correction."""
    x = np.asarray(x, float)
    n = x.size
    s = int(sum(np.sign(x[j] - x[i]) for i in range(n - 1) for j in range(i + 1, n)))
    _, counts = np.unique(x, return_counts=True)
    var_s = (n * (n - 1) * (2 * n + 5)
             - (counts * (counts - 1) * (2 * counts + 5)).sum()) / 18
    z = ((s - 1) if s > 0 else (s + 1) if s < 0 else 0) / np.sqrt(var_s)
    return {"S": s, "Z": z, "p": 2 * stats.norm.sf(abs(z)),
            "tau": s / (0.5 * n * (n - 1)), "n": n}


def sens_slope(t, x) -> float:
    """Theil-Sen median slope, robust to the outliers a seismic series is full of."""
    t, x = np.asarray(t, float), np.asarray(x, float)
    slopes = [(x[j] - x[i]) / (t[j] - t[i])
              for i in range(len(t) - 1) for j in range(i + 1, len(t)) if t[j] != t[i]]
    return float(np.median(slopes)) if slopes else np.nan


def trend_table(annual) -> pd.DataFrame:
    """Mann-Kendall plus Sen's slope for each annual series."""
    labels = {"Count": "Annual event count", "MaxMag": "Annual maximum magnitude",
              "MeanMag": "Annual mean magnitude",
              "CountM6": "Annual count of M ≥ 6.0 events"}
    rows = []
    for name, label in labels.items():
        mk = mann_kendall(annual[name].to_numpy())
        rows.append({"Series": label, "n (years)": mk["n"], "Mann–Kendall S": mk["S"],
                     "Z": mk["Z"], "Kendall's τ": mk["tau"], "p": mk["p"],
                     "Sen's slope (per year)": sens_slope(annual["Year"].to_numpy(),
                                                          annual[name].to_numpy()),
                     "Trend": (("Increasing" if mk["Z"] > 0 else "Decreasing")
                               if mk["p"] < CFG.ALPHA else "No trend")})
    return pd.DataFrame(rows)


def era_comparison(df, split_year=1980) -> pd.DataFrame:
    """Independent-samples comparison of magnitude before and after `split_year`.

    The split marks the modernisation of the PHIVOLCS network; a difference here
    is at least as likely to reflect detection capability as real seismicity,
    and the Note on the table says so.
    """
    early = df.loc[df["Year"] < split_year, "Magnitude"].dropna().to_numpy()
    late = df.loc[df["Year"] >= split_year, "Magnitude"].dropna().to_numpy()
    t_stat, t_p = stats.ttest_ind(early, late, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(early, late, alternative="two-sided")
    pooled_sd = np.sqrt(((early.size - 1) * early.var(ddof=1)
                         + (late.size - 1) * late.var(ddof=1))
                        / (early.size + late.size - 2))
    return pd.DataFrame([
        {"Statistic": f"n (pre-{split_year})", "Value": f"{early.size:,}"},
        {"Statistic": f"M (pre-{split_year})",
         "Value": f"{early.mean():.3f} (SD = {early.std(ddof=1):.3f})"},
        {"Statistic": f"n ({split_year}–present)", "Value": f"{late.size:,}"},
        {"Statistic": f"M ({split_year}–present)",
         "Value": f"{late.mean():.3f} (SD = {late.std(ddof=1):.3f})"},
        {"Statistic": "Welch's t", "Value": f"{t_stat:.3f}"},
        {"Statistic": "p (Welch's t)", "Value": fmt_p(t_p)},
        {"Statistic": "Cohen's d", "Value": f"{(early.mean() - late.mean()) / pooled_sd:.3f}"},
        {"Statistic": "Mann–Whitney U", "Value": f"{u_stat:,.0f}"},
        {"Statistic": "p (Mann–Whitney)", "Value": fmt_p(u_p)},
        {"Statistic": "Rank-biserial correlation",
         "Value": f"{1 - 2 * u_stat / (early.size * late.size):.3f}"}])


# =============================================================================
# PART 6.  GUTENBERG-RICHTER ANALYSIS
# -----------------------------------------------------------------------------
# Two estimators are carried side by side throughout, because the thesis's
# feature table requires both: least-squares regression on the cumulative
# frequency-magnitude distribution, and the Aki-Utsu maximum-likelihood
# estimator.
# =============================================================================
def fmd(magnitudes, bin_width=CFG.MAG_BIN):
    """Return `(bins, incremental_counts, cumulative_counts)`."""
    m = np.asarray(magnitudes, float)
    m = m[np.isfinite(m)]
    if m.size == 0:
        return np.array([]), np.array([]), np.array([])
    lo = np.floor(m.min() / bin_width) * bin_width
    hi = np.ceil(m.max() / bin_width) * bin_width
    bins = np.round(np.arange(lo, hi + bin_width, bin_width), 5)
    inc, _ = np.histogram(m, bins=np.append(bins - bin_width / 2,
                                            bins[-1] + bin_width / 2))
    return bins, inc, inc[::-1].cumsum()[::-1]


def mc_maxc(magnitudes, bin_width=CFG.MAG_BIN) -> float:
    """Maximum-curvature Mc: the mode of the incremental FMD, plus the +0.2
    correction that Woessner and Wiemer (2005) found necessary."""
    bins, inc, _ = fmd(magnitudes, bin_width)
    return float(bins[int(np.argmax(inc))] + 0.2) if bins.size else np.nan


def b_value_mle(magnitudes, mc, bin_width=CFG.MAG_BIN) -> dict:
    """Aki-Utsu maximum-likelihood b with the Shi and Bolt (1982) standard error."""
    m = np.asarray(magnitudes, float)
    m = m[np.isfinite(m) & (m >= mc - bin_width / 2)]
    n = m.size
    if n < 2:
        return {"b": np.nan, "b_se": np.nan, "a": np.nan, "n": n, "mean_mag": np.nan}
    mean_mag = m.mean()
    denom = mean_mag - (mc - bin_width / 2)
    b = LOG10_E / denom if denom > 0 else np.nan
    b_se = 2.30 * b ** 2 * np.sqrt(((m - mean_mag) ** 2).sum() / (n * (n - 1)))
    return {"b": b, "b_se": b_se, "a": np.log10(n) + b * mc, "n": n,
            "mean_mag": mean_mag}


def b_value_lsq(magnitudes, mc, bin_width=CFG.MAG_BIN) -> dict:
    """Least-squares fit of log10 N(>=M) = a - b*M above Mc.

    Bins holding no events are dropped before the fit; log10(0) is undefined and
    silently propagating it as -inf is a classic way to destroy a b-value.
    """
    empty = {"b": np.nan, "b_se": np.nan, "a": np.nan, "n": 0, "r2": np.nan,
             "std_gr": np.nan, "n_events": 0}
    bins, _, cum = fmd(magnitudes, bin_width)
    if bins.size == 0:
        return empty
    keep = (bins >= mc - bin_width / 2) & (cum > 0)
    x, y = bins[keep], np.log10(cum[keep])
    if x.size < 3:
        return {**empty, "n": x.size}
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (intercept + slope * x)
    ss_res, ss_tot = (resid ** 2).sum(), ((y - y.mean()) ** 2).sum()
    return {"b": -slope, "a": intercept, "n": x.size,
            "b_se": np.sqrt(ss_res / (x.size - 2) / ((x - x.mean()) ** 2).sum()),
            "r2": 1 - ss_res / ss_tot if ss_tot > 0 else np.nan,
            "std_gr": np.sqrt(ss_res / (x.size - 1)),
            "n_events": int(cum[keep][0])}


def mc_goodness_of_fit(magnitudes, target_r=CFG.GFT_TARGET_R, bin_width=CFG.MAG_BIN):
    """Wiemer and Wyss (2000) goodness-of-fit Mc.

    Returns `(mc, achieved_R)`.  If no cut-off reaches `target_r`, the cut-off
    with the best R is returned so the caller always has a usable value, and the
    achieved R makes the shortfall visible.
    """
    bins, inc, _ = fmd(magnitudes, bin_width)
    if bins.size == 0:
        return np.nan, np.nan
    best = (np.nan, -np.inf)
    for mc in bins[:-2]:
        est = b_value_mle(magnitudes, mc, bin_width)
        if not np.isfinite(est["b"]) or est["n"] < CFG.MC_MIN_EVENTS:
            continue
        keep = bins >= mc - bin_width / 2
        synth = 10 ** (est["a"] - est["b"] * bins[keep])
        synth_inc = -np.diff(np.append(synth, 0))
        obs_inc = inc[keep]
        if obs_inc.sum() == 0:
            continue
        r = 100 * (1 - np.abs(obs_inc - synth_inc).sum() / obs_inc.sum())
        if r >= target_r:
            return float(mc), float(r)
        if r > best[1]:
            best = (float(mc), float(r))
    return best


def gr_summary(df, group_column=None) -> pd.DataFrame:
    """Mc / a / b for the whole catalogue, or one row per level of a grouping."""
    groups = ([("Full catalogue", df)] if group_column is None
              else [(str(k), g) for k, g in df.groupby(group_column, observed=True)])
    rows = []
    for name, g in groups:
        m = g["Magnitude"].dropna().to_numpy()
        if m.size < CFG.MC_MIN_EVENTS:
            rows.append({"Subset": name, "N events": m.size, "Mc (MAXC)": np.nan,
                         "Mc (GFT)": np.nan, "GFT R (%)": np.nan, "N ≥ Mc": 0,
                         "b (MLE)": np.nan, "SE b (MLE)": np.nan, "a (MLE)": np.nan,
                         "b (LSQ)": np.nan, "SE b (LSQ)": np.nan, "a (LSQ)": np.nan,
                         "R² (LSQ)": np.nan})
            continue
        mc_max = mc_maxc(m)
        mc_gft, r_gft = mc_goodness_of_fit(m)
        mc = mc_gft if np.isfinite(mc_gft) else mc_max
        mle, lsq = b_value_mle(m, mc), b_value_lsq(m, mc)
        rows.append({"Subset": name, "N events": m.size, "Mc (MAXC)": mc_max,
                     "Mc (GFT)": mc_gft, "GFT R (%)": r_gft, "N ≥ Mc": mle["n"],
                     "b (MLE)": mle["b"], "SE b (MLE)": mle["b_se"], "a (MLE)": mle["a"],
                     "b (LSQ)": lsq["b"], "SE b (LSQ)": lsq["b_se"], "a (LSQ)": lsq["a"],
                     "R² (LSQ)": lsq["r2"]})
    return pd.DataFrame(rows)


# =============================================================================
# PART 7.  MAEDA'S DECLUSTERING METHOD
# -----------------------------------------------------------------------------
# Implements the three equations reproduced in the thesis methodology:
#   (1)  log10(L)        <=  0.5*Mpre - 1.8                   spatial window, km
#   (2)  log10(ta + 0.3) <= (0.17 + 0.85*(Mpre - 4.0)) / 1.3  temporal window, d
#   (3)  Ma < Mpre - Md,  Md = 1.0                            magnitude cut-off
# An event is removed when it falls inside the space-time window of an earlier,
# retained event AND is at least Md units smaller.  Equation 3 is what keeps the
# method from deleting the very mainshocks the study is trying to forecast.
# =============================================================================
def maeda_radius_km(magnitude):
    """Equation 1 -- spatial search radius for a precursor of this magnitude."""
    return 10 ** (CFG.MAEDA_L_SLOPE * np.asarray(magnitude, float)
                  + CFG.MAEDA_L_INTERCEPT)


def maeda_days(magnitude):
    """Equation 2 -- temporal search window for a precursor of this magnitude."""
    exponent = ((CFG.MAEDA_T_A + CFG.MAEDA_T_B * (np.asarray(magnitude, float) - 4.0))
                / CFG.MAEDA_T_C)
    return 10 ** exponent - CFG.MAEDA_T_OFFSET


def decluster(df):
    """Return `(catalogue_with_flags, summary_frame)`.

    The catalogue gains a boolean `IsDependent` column and an `AnchorIndex`
    naming the event that claimed each dependent record, so a reviewer can audit
    any individual removal.
    """
    data = df.sort_values("datetime", kind="mergesort").reset_index(drop=True)
    t_days = ((data["datetime"] - data["datetime"].iloc[0])
              .dt.total_seconds().to_numpy() / 86400.0)
    lat, lon = data["Latitude"].to_numpy(), data["Longitude"].to_numpy()
    mag = data["Magnitude"].to_numpy()
    radius = maeda_radius_km(mag)
    duration = np.clip(maeda_days(mag), 0, None)

    n = len(data)
    dependent = np.zeros(n, dtype=bool)
    anchor = np.full(n, -1, dtype=np.int64)
    for i in range(n):
        if dependent[i]:
            continue                      # a dependent event never anchors a window
        stop = np.searchsorted(t_days, t_days[i] + duration[i], side="right")
        if stop <= i + 1:
            continue
        j = np.arange(i + 1, stop)
        j = j[~dependent[j]]
        j = j[mag[j] < (mag[i] - CFG.MAEDA_MD)] if j.size else j
        if j.size == 0:
            continue
        hit = j[haversine_km(lat[i], lon[i], lat[j], lon[j]) <= radius[i]]
        dependent[hit] = True
        anchor[hit] = i

    data["IsDependent"] = dependent
    data["AnchorIndex"] = anchor
    retained = int((~dependent).sum())
    summary = pd.DataFrame([
        {"Declustering stage": "Events entering Maeda's method", "n": n, "% of input": 100.0},
        {"Declustering stage": "Dependent events removed (Eq. 1–3)",
         "n": int(dependent.sum()), "% of input": 100 * dependent.sum() / n},
        {"Declustering stage": "Independent events retained", "n": retained,
         "% of input": 100 * retained / n},
        {"Declustering stage": "Retained events M ≥ 5.0",
         "n": int((~dependent & (mag >= 5.0)).sum()),
         "% of input": 100 * (~dependent & (mag >= 5.0)).sum() / n},
        {"Declustering stage": "Retained events M ≥ 6.0",
         "n": int((~dependent & (mag >= 6.0)).sum()),
         "% of input": 100 * (~dependent & (mag >= 6.0)).sum() / n},
        {"Declustering stage": "Retained events M ≥ 7.0",
         "n": int((~dependent & (mag >= 7.0)).sum()),
         "% of input": 100 * (~dependent & (mag >= 7.0)).sum() / n}])
    return data, summary


def maeda_window_reference(magnitudes=(4.0, 5.0, 6.0, 7.0, 8.0)) -> pd.DataFrame:
    """The space-time windows Equations 1 and 2 imply, as a reference table."""
    m = np.asarray(magnitudes, float)
    return pd.DataFrame({"Precursor magnitude (Mpre)": m,
                         "Spatial window L (km)": maeda_radius_km(m),
                         "Temporal window ta (days)": maeda_days(m),
                         "Magnitude cut-off (Mpre − Md)": m - CFG.MAEDA_MD})


def decluster_effect(before, after) -> pd.DataFrame:
    """Side-by-side descriptive comparison of the raw and declustered catalogues."""
    rows = []
    for label, frame in (("Full catalogue", before), ("Declustered catalogue", after)):
        m = frame["Magnitude"].dropna()
        rows.append({"Catalogue": label, "N": len(frame), "M": m.mean(),
                     "SD": m.std(ddof=1), "Mdn": m.median(), "Min": m.min(),
                     "Max": m.max(), "n (M ≥ 5.0)": int((m >= 5.0).sum()),
                     "n (M ≥ 6.0)": int((m >= 6.0).sum()),
                     "Mdn depth (km)": frame["Depth"].median()})
    return pd.DataFrame(rows)


# =============================================================================
# PART 8.  FEATURE ENGINEERING -- THE 22 FEATURES
# -----------------------------------------------------------------------------
# Each mainshock contributes one record built from the events inside its
# observation window: everything within RADIUS_KM of the epicentre during the
# T_OBS_DAYS immediately before it.  The window closes strictly before the
# mainshock origin time, so the target never leaks into its own predictors.
# =============================================================================
# The 22 features of Table 1, exactly as the methodology specifies them.
CORE_FEATURE_NAMES = ["NO", "Mag_max", "Mag_mean", "b_lsq", "a_lsq", "b_std_lsq",
                      "std_gr_lsq", "b_mlk", "a_mlk", "b_std_mlk", "std_gr_mlk",
                      "dM_lsq", "dM_mlk", "Energy", "x7_lsq", "x7_mlk", "zvalue",
                      "beta", "T_elaps6", "T_elaps65", "T_elaps7", "T_elaps75"]

# Distance to the nearest active fault is named in Data Collection as a selected
# parameter but has no row in Table 1, so it is carried as a clearly separate
# group. Every one of these is computed from the foreshocks alone: the
# mainshock's own distance to a fault is a property of the event being
# forecast, and using it would leak the answer into the predictors.
FAULT_FEATURE_NAMES = ["Dist_min", "Dist_mean", "Dist_std", "Dist_wmean", "Dist_trend"]

FEATURE_NAMES = CORE_FEATURE_NAMES + FAULT_FEATURE_NAMES

FEATURE_DESCRIPTIONS = {
    "NO": "Number of earthquakes in the observation window",
    "Mag_max": "Maximum magnitude in the observation window",
    "Mag_mean": "Mean magnitude in the observation window",
    "b_lsq": "b-value by least-squares regression",
    "a_lsq": "a-value by least-squares regression",
    "b_std_lsq": "Standard deviation of b_lsq",
    "std_gr_lsq": "Deviation from the Gutenberg–Richter law (LSQ)",
    "b_mlk": "b-value by maximum likelihood (Aki–Utsu)",
    "a_mlk": "a-value by maximum likelihood",
    "b_std_mlk": "Standard deviation of b_mlk",
    "std_gr_mlk": "Deviation from the Gutenberg–Richter law (MLE)",
    "dM_lsq": "Magnitude deficit from a_lsq and b_lsq",
    "dM_mlk": "Magnitude deficit from a_mlk and b_mlk",
    "Energy": "Square root of the summed seismic energy release",
    "x7_lsq": "Probability of occurrence derived from b_lsq",
    "x7_mlk": "Probability of occurrence derived from b_mlk",
    "zvalue": "Seismic rate change (z statistic)",
    "beta": "Seismic rate change (β statistic)",
    "T_elaps6": "Days since the last M 6.0 earthquake",
    "T_elaps65": "Days since the last M 6.5 earthquake",
    "T_elaps7": "Days since the last M 7.0 earthquake",
    "T_elaps75": "Days since the last M 7.5 earthquake",
    "Dist_min": "Closest approach to an active fault in the observation window",
    "Dist_mean": "Mean distance to the nearest active fault",
    "Dist_std": "Standard deviation of the fault distances",
    "Dist_wmean": "Fault distance weighted by released energy",
    "Dist_trend": "Change in fault distance across the window, km per day"}

FEATURE_CATEGORIES = {
    **{k: "Basic statistics" for k in ("NO", "Mag_max", "Mag_mean")},
    **{k: "Gutenberg–Richter law" for k in ("b_lsq", "a_lsq", "b_std_lsq", "std_gr_lsq",
                                            "b_mlk", "a_mlk", "b_std_mlk", "std_gr_mlk")},
    **{k: "Energy and magnitude deficit" for k in ("dM_lsq", "dM_mlk", "Energy")},
    **{k: "Activity-rate change and probability" for k in ("x7_lsq", "x7_mlk",
                                                           "zvalue", "beta")},
    **{k: "Time elapsed" for k in ("T_elaps6", "T_elaps65", "T_elaps7", "T_elaps75")},
    **{k: "Distance to nearest fault" for k in FAULT_FEATURE_NAMES}}


def _energy(mags) -> float:
    """Energy = sqrt( sum 10^(c0 + c1*Mi) ), computed in log space.

    The naive form overflows a float64 at the top of the magnitude range, and
    the resulting `inf` would quietly poison the whole feature column.
    """
    c0, c1 = CFG.ENERGY_COEFFS
    exponents = c0 + c1 * mags
    peak = exponents.max()
    return float(10.0 ** ((peak + np.log10(np.sum(10.0 ** (exponents - peak)))) / 2.0))


def _z_value(times, t_start, t_end) -> float:
    """Habermann z: change in daily rate between the two halves of the window."""
    mid = (t_start + t_end) / 2
    halves = []
    for lo, hi in ((t_start, mid), (mid, t_end)):
        days = max(int(round(hi - lo)), 1)
        counts = np.histogram(times, bins=np.linspace(lo, hi, days + 1))[0].astype(float)
        halves.append((counts.mean(),
                       counts.var(ddof=1) if counts.size > 1 else 0.0, counts.size))
    (r1, s1, n1), (r2, s2, n2) = halves
    denom = np.sqrt(s1 / max(n1, 1) + s2 / max(n2, 1))
    return float((r1 - r2) / denom) if denom > 0 else 0.0


def _beta(n_window, n_background, delta) -> float:
    """β statistic: observed window count against a Poisson background rate."""
    denom = np.sqrt(n_background * delta * (1 - delta))
    return float((n_window - n_background * delta) / denom) if denom > 0 else 0.0


def _days_since(prior_times, prior_mags, t_now, threshold, span) -> float:
    """Days since the last event at or above `threshold`.

    When the region has no such event on record the value is censored at the
    catalogue span rather than left missing, which is the honest encoding of
    "at least this long" for a tree model.
    """
    hit = prior_times[prior_mags >= threshold]
    return float(t_now - hit[-1]) if hit.size else float(span)


def _gr_deviation(mags, a, b) -> float:
    """RMS departure of the observed cumulative FMD from the fitted GR line."""
    if not (np.isfinite(a) and np.isfinite(b)):
        return np.nan
    bins, _, cum = fmd(mags)
    keep = cum > 0
    if keep.sum() < 2:
        return np.nan
    resid = np.log10(cum[keep]) - (a - b * bins[keep])
    return float(np.sqrt((resid ** 2).sum() / (keep.sum() - 1)))


def _fault_features(dists, mags, times) -> dict:
    """Fault-distance statistics for one observation window.

    The weighted mean uses released energy rather than magnitude directly, so a
    single large foreshock pulls the summary toward its own distance the way it
    dominates the actual stress transfer. The trend is a least-squares slope in
    km per day: negative means the sequence is migrating toward the fault.
    """
    n = dists.size
    if n == 0:
        return {name: np.nan for name in FAULT_FEATURE_NAMES}
    weights = 10.0 ** (1.5 * mags)          # energy proportional weighting
    total = weights.sum()
    if n >= 3 and np.ptp(times) > 0:
        # Closed-form least-squares slope rather than polyfit. polyfit solves
        # this through an SVD, which lands a few parts in a million away from
        # the direct computation and puts the browser's reimplementation out of
        # agreement for no gain on a straight line fit.
        t_bar, d_bar = times.mean(), dists.mean()
        s_tt = ((times - t_bar) ** 2).sum()
        trend = float(((times - t_bar) * (dists - d_bar)).sum() / s_tt) if s_tt > 0 else 0.0
    else:
        trend = 0.0
    return {
        "Dist_min": float(dists.min()),
        "Dist_mean": float(dists.mean()),
        "Dist_std": float(dists.std(ddof=1)) if n > 1 else 0.0,
        "Dist_wmean": float((weights * dists).sum() / total) if total > 0 else float(dists.mean()),
        "Dist_trend": trend,
    }


def _window_features(mags, times, t_start, t_end, n_background) -> dict:
    """The 18 window-derived features; the four T_elaps come from the caller."""
    n = mags.size
    mag_max, mag_mean = float(mags.max()), float(mags.mean())
    mc = mc_maxc(mags) if n >= 5 else float(mags.min())
    lsq, mle = b_value_lsq(mags, mc), b_value_mle(mags, mc)

    # b_std by the Shi and Bolt form, which the thesis gives for both estimators.
    spread = (np.sqrt(((mags - mag_mean) ** 2).sum() / (n * (n - 1)))
              if n > 1 else np.nan)
    b_l, b_m = lsq["b"], mle["b"]
    return {
        "NO": float(n), "Mag_max": mag_max, "Mag_mean": mag_mean,
        "b_lsq": b_l, "a_lsq": lsq["a"],
        "b_std_lsq": 2.3 * b_l ** 2 * spread if np.isfinite(b_l) else np.nan,
        "std_gr_lsq": lsq["std_gr"],
        "b_mlk": b_m, "a_mlk": mle["a"],
        "b_std_mlk": 2.3 * b_m ** 2 * spread if np.isfinite(b_m) else np.nan,
        "std_gr_mlk": _gr_deviation(mags, mle["a"], b_m),
        "dM_lsq": mag_max - lsq["a"] / b_l if np.isfinite(b_l) and b_l != 0 else np.nan,
        "dM_mlk": mag_max - mle["a"] / b_m if np.isfinite(b_m) and b_m != 0 else np.nan,
        "Energy": _energy(mags),
        # x7 = e^(-3b / log10 e) == 10^(-3b): the Gutenberg-Richter probability
        # of an event three magnitude units above the reference level.
        "x7_lsq": float(10.0 ** (-3 * b_l)) if np.isfinite(b_l) else np.nan,
        "x7_mlk": float(10.0 ** (-3 * b_m)) if np.isfinite(b_m) else np.nan,
        "zvalue": _z_value(times, t_start, t_end),
        "beta": _beta(n, n_background, (t_end - t_start) / CFG.BACKGROUND_DAYS)}


def build_sequences(declustered, full=None) -> pd.DataFrame:
    """One feature row per mainshock.

    `declustered` supplies the mainshock targets.  The observation windows are
    read from `full` (the pre-declustering catalogue) when given, because
    Maeda's method strips small dependent events and those are exactly the
    precursory activity the features are meant to measure.
    """
    source = (full if full is not None else declustered)
    source = source.sort_values("datetime", kind="mergesort").reset_index(drop=True)
    origin = source["datetime"].iloc[0]
    to_days = lambda s: (s - origin).dt.total_seconds().to_numpy() / 86400.0

    src_t = to_days(source["datetime"])
    src_lat, src_lon = source["Latitude"].to_numpy(), source["Longitude"].to_numpy()
    src_mag = source["Magnitude"].to_numpy()
    has_fault = "SrcDistKm" in source.columns
    src_dist = source["SrcDistKm"].to_numpy() if has_fault else None
    span = src_t[-1] - src_t[0]

    flags = declustered.get("IsDependent", pd.Series(False, index=declustered.index))
    mains = (declustered[~flags & (declustered["Magnitude"] >= CFG.MAINSHOCK_MIN_MAG)]
             .sort_values("datetime").reset_index(drop=True))
    main_t = to_days(mains["datetime"])

    records = []
    skipped = {"too few foreshocks": 0, "outside catalogue start": 0}
    for k in range(len(mains)):
        t_end = main_t[k]
        t_start = t_end - CFG.T_OBS_DAYS
        if t_start < src_t[0]:
            skipped["outside catalogue start"] += 1
            continue
        lo = np.searchsorted(src_t, t_start, side="left")
        hi = np.searchsorted(src_t, t_end, side="left")   # strictly before the target
        idx = np.arange(lo, hi)
        if idx.size:
            idx = idx[haversine_km(mains["Latitude"][k], mains["Longitude"][k],
                                   src_lat[idx], src_lon[idx]) <= CFG.RADIUS_KM]
        if idx.size < CFG.MIN_FORESHOCKS:
            skipped["too few foreshocks"] += 1
            continue

        # Background count: same radius, the year preceding the window.
        bidx = np.arange(np.searchsorted(src_t, t_end - CFG.BACKGROUND_DAYS, "left"), hi)
        if bidx.size:
            bidx = bidx[haversine_km(mains["Latitude"][k], mains["Longitude"][k],
                                     src_lat[bidx], src_lon[bidx]) <= CFG.RADIUS_KM]
        # Elapsed-time features use the regional history before the window opens.
        prior = np.arange(0, hi)
        prior = prior[haversine_km(mains["Latitude"][k], mains["Longitude"][k],
                                   src_lat[prior], src_lon[prior]) <= CFG.RADIUS_KM]

        feats = _window_features(src_mag[idx], src_t[idx], t_start, t_end,
                                 max(bidx.size, 1))
        if has_fault:
            feats.update(_fault_features(src_dist[idx], src_mag[idx], src_t[idx]))
        else:
            feats.update({name: np.nan for name in FAULT_FEATURE_NAMES})
        for name, threshold in (("T_elaps6", 6.0), ("T_elaps65", 6.5),
                                ("T_elaps7", 7.0), ("T_elaps75", 7.5)):
            feats[name] = _days_since(src_t[prior], src_mag[prior], t_end,
                                      threshold, span)
        records.append({"MainshockTime": mains["datetime"][k],
                        "MainshockYear": mains["datetime"][k].year,
                        "MainshockLat": mains["Latitude"][k],
                        "MainshockLon": mains["Longitude"][k],
                        "MainshockDepth": mains["Depth"][k],
                        "Target": float(mains["Magnitude"][k]), **feats})

    out = pd.DataFrame(records)
    if out.empty:
        return out
    out["TargetClass"] = pd.cut(out["Target"], bins=CFG.MAG_CLASS_EDGES,
                                labels=CFG.MAG_CLASS_LABELS, right=False)
    out = out.sort_values("MainshockTime").reset_index(drop=True)
    out.attrs["skipped"] = skipped
    out.attrs["n_mainshocks"] = len(mains)
    return out



# =============================================================================
# PART 8b.  OCCURRENCE FORECASTING
# -----------------------------------------------------------------------------
# The magnitude model answers "how large, if one follows". It assumes an
# earthquake happens. The Scope section commits to something else as well: the
# probability that one occurs at all inside a two-week window. That cannot be
# learned from the sequence data set, because every sequence there ends in a
# mainshock and so every label is positive. It needs anchors where nothing
# followed, which is what this part builds.
#
# An anchor is a moment and a place with enough recent activity to compute the
# features: the operational question is not "will an earthquake strike a random
# point" but "we are seeing tremors here, what now". The label looks FORWARD
# from the anchor over HORIZON_DAYS, which is the reverse of the magnitude
# model's backward-looking observation window.
# =============================================================================
def build_occurrence_dataset(full, independent, radius, horizon=None, thin_days=None):
    """Anchors with look-back features and forward-looking occurrence labels.

    `full` supplies the activity the features are computed from; `independent`
    supplies the labels, so an aftershock of an event that already happened does
    not count as a fresh occurrence. Anchors within `thin_days` and half a
    radius of one already kept are dropped: a single swarm would otherwise
    contribute fifty near-identical rows and dominate both training and score.
    """
    horizon = CFG.HORIZON_DAYS if horizon is None else horizon
    thin_days = CFG.OCC_THIN_DAYS if thin_days is None else thin_days

    src = full.sort_values("datetime", kind="mergesort").reset_index(drop=True)
    ind = independent.sort_values("datetime", kind="mergesort").reset_index(drop=True)
    origin = src["datetime"].iloc[0]
    to_days = lambda s: (s - origin).dt.total_seconds().to_numpy() / 86400.0

    t = to_days(src["datetime"])
    lat, lon = src["Latitude"].to_numpy(), src["Longitude"].to_numpy()
    mag = src["Magnitude"].to_numpy()
    dist = src["SrcDistKm"].to_numpy() if "SrcDistKm" in src.columns else None
    span = t[-1] - t[0]

    it = to_days(ind["datetime"])
    ilat, ilon = ind["Latitude"].to_numpy(), ind["Longitude"].to_numpy()
    imag = ind["Magnitude"].to_numpy()

    kept_t, kept_lat, kept_lon = [], [], []
    rows, skipped = [], 0

    for i in range(len(src)):
        t_end = t[i]
        t_start = t_end - CFG.T_OBS_DAYS
        if t_start < t[0] or t_end + horizon > t[-1]:
            continue

        lo = np.searchsorted(t, t_start, "left")
        idx = np.arange(lo, i)
        if idx.size:
            idx = idx[haversine_km(lat[i], lon[i], lat[idx], lon[idx]) <= radius]
        if idx.size < CFG.MIN_FORESHOCKS:
            continue

        # Thinning. Walk back only as far as the separation allows.
        crowded = False
        for j in range(len(kept_t) - 1, -1, -1):
            if t_end - kept_t[j] > thin_days:
                break
            if haversine_km(lat[i], lon[i], kept_lat[j], kept_lon[j]) <= radius / 2:
                crowded = True
                break
        if crowded:
            skipped += 1
            continue
        kept_t.append(t_end); kept_lat.append(lat[i]); kept_lon.append(lon[i])

        blo = np.searchsorted(t, t_end - CFG.BACKGROUND_DAYS, "left")
        bidx = np.arange(blo, i)
        if bidx.size:
            bidx = bidx[haversine_km(lat[i], lon[i], lat[bidx], lon[bidx]) <= radius]

        prior = np.arange(0, i)
        prior = prior[haversine_km(lat[i], lon[i], lat[prior], lon[prior]) <= radius]

        feats = _window_features(mag[idx], t[idx], t_start, t_end, max(bidx.size, 1))
        if dist is not None:
            feats.update(_fault_features(dist[idx], mag[idx], t[idx]))
        else:
            feats.update({n: np.nan for n in FAULT_FEATURE_NAMES})
        for name, threshold in (("T_elaps6", 6.0), ("T_elaps65", 6.5),
                                ("T_elaps7", 7.0), ("T_elaps75", 7.5)):
            feats[name] = _days_since(t[prior], mag[prior], t_end, threshold, span)

        # Forward window, from the independent catalogue.
        flo = np.searchsorted(it, t_end, "right")
        fhi = np.searchsorted(it, t_end + horizon, "right")
        fwd = np.arange(flo, fhi)
        if fwd.size:
            fwd = fwd[haversine_km(lat[i], lon[i], ilat[fwd], ilon[fwd]) <= radius]
        largest = float(imag[fwd].max()) if fwd.size else 0.0

        record = {"AnchorTime": src["datetime"].iloc[i], "AnchorLat": lat[i],
                  "AnchorLon": lon[i], "t_end": t_end,
                  "LargestAhead": largest, **feats}
        for threshold in CFG.OCC_THRESHOLDS:
            record[f"y{threshold:g}"] = int(largest >= threshold)
        rows.append(record)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("AnchorTime").reset_index(drop=True)
        out.attrs["thinned"] = skipped
        out.attrs["radius"] = radius
        out.attrs["horizon"] = horizon
    return out


def occurrence_profile(datasets) -> pd.DataFrame:
    """Anchor counts and observed base rates for every radius and threshold."""
    rows = []
    for radius, data in datasets.items():
        row = {"Radius (km)": radius, "Anchors": len(data),
               "Thinned out": data.attrs.get("thinned", 0),
               "Period": f"{data['AnchorTime'].min():%b %Y} to {data['AnchorTime'].max():%b %Y}"}
        for threshold in CFG.OCC_THRESHOLDS:
            y = data[f"y{threshold:g}"]
            row[f"P(M ≥ {threshold:g}) observed"] = 100 * y.mean()
            row[f"n positive (M ≥ {threshold:g})"] = int(y.sum())
        rows.append(row)
    return pd.DataFrame(rows)


def fit_occurrence_models(datasets, seed=CFG.SEED, folds=CFG.CV_FOLDS, verbose=True):
    """Train, calibrate and honestly score one probability model per cell.

    Evaluation is rolling-origin rather than a single chronological split. With
    four to thirty positives in a test block, one split produces an AUC that
    swings from .13 to .80 on the same cell, and reporting whichever one came up
    would be reporting noise. Every cell is scored across folds and judged on
    the mean.

    A cell is only called modelled when the calibrated probability actually
    beats quoting the historical base rate: a positive mean Brier skill score
    and a mean ROC AUC above .55. Anything else falls back to the base rate,
    which is a real conditional frequency and an honest answer, rather than
    dressing a coin flip up as a forecast.
    """
    from sklearn.calibration import CalibratedClassifierCV

    results, fitted = [], {}
    for radius, data in datasets.items():
        logged = DataBundle._log_transform(
            data[FEATURE_NAMES].replace([np.inf, -np.inf], np.nan))
        n = len(data)
        block = n // (folds + 1)

        for threshold in CFG.OCC_THRESHOLDS:
            y = data[f"y{threshold:g}"].to_numpy(int)
            overall_rate = float(y.mean())
            aucs, bsss, tested = [], [], 0

            for f in range(folds):
                tr = np.arange(0, block * (f + 1))
                te = np.arange(block * (f + 1), min(block * (f + 2), n))
                if te.size < 20 or y[tr].sum() < CFG.OCC_MIN_POSITIVES:
                    continue
                if len(np.unique(y[te])) < 2:
                    continue

                fill = logged.iloc[tr].median(numeric_only=True).fillna(0.0)
                lo = logged.iloc[tr].quantile(WINSOR_QUANTILES[0])
                hi = logged.iloc[tr].quantile(WINSOR_QUANTILES[1])
                M = logged.fillna(fill).clip(lower=lo, upper=hi, axis=1).to_numpy(float)

                cut = int(0.8 * len(tr))
                forest = RandomForestClassifier(
                    n_estimators=300, max_depth=8, min_samples_leaf=4,
                    class_weight="balanced_subsample", random_state=seed, n_jobs=-1)
                forest.fit(M[tr[:cut]], y[tr[:cut]])
                calibrated = CalibratedClassifierCV(forest, method="sigmoid", cv="prefit")
                calibrated.fit(M[tr[cut:]], y[tr[cut:]])
                prob = calibrated.predict_proba(M[te])[:, 1]

                brier = float(np.mean((prob - y[te]) ** 2))
                ref = float(np.mean((y[tr].mean() - y[te]) ** 2))
                aucs.append(float(roc_auc_score(y[te], prob)))
                bsss.append(100 * (1 - brier / ref) if ref > 0 else np.nan)
                tested += te.size
                fitted[(radius, threshold)] = {
                    "model": calibrated, "fill": fill, "lo": lo, "hi": hi,
                    "prob": prob, "y": y[te]}

            if not aucs:
                results.append({
                    "Radius (km)": radius, "Threshold": f"M ≥ {threshold:g}",
                    "Anchors": n, "Positives": int(y.sum()),
                    "Historical rate (%)": 100 * overall_rate, "Folds scored": 0,
                    "M ROC AUC": np.nan, "SD AUC": np.nan,
                    "M Brier skill (%)": np.nan, "SD Brier skill": np.nan,
                    "Verdict": "Too few events to model"})
                fitted.pop((radius, threshold), None)
                continue

            mean_auc = float(np.mean(aucs))
            mean_bss = float(np.nanmean(bsss))
            skilful = mean_bss > 0 and mean_auc > 0.55
            results.append({
                "Radius (km)": radius, "Threshold": f"M ≥ {threshold:g}",
                "Anchors": n, "Positives": int(y.sum()),
                "Historical rate (%)": 100 * overall_rate, "Folds scored": len(aucs),
                "M ROC AUC": mean_auc, "SD AUC": float(np.std(aucs, ddof=1)) if len(aucs) > 1 else np.nan,
                "M Brier skill (%)": mean_bss,
                "SD Brier skill": float(np.nanstd(bsss, ddof=1)) if len(bsss) > 1 else np.nan,
                "Verdict": "Model beats the base rate" if skilful else "No skill beyond the base rate"})
            if not skilful:
                fitted.pop((radius, threshold), None)
            if verbose:
                print(f"      R={radius:3.0f} km  M>={threshold:g}  rate {100*overall_rate:5.1f}%  "
                      f"AUC {mean_auc:.3f}  BSS {mean_bss:+6.1f}%  "
                      f"{'skilful' if skilful else 'no skill'}")
    return pd.DataFrame(results), fitted



def wilson_interval(successes, trials, z=1.959963985):
    """Wilson score interval for a proportion.

    Wald's interval, the textbook p +/- z*sqrt(p(1-p)/n), is unusable here: at
    the M 7.0 rate of roughly 0.4% it produces a lower bound below zero and its
    coverage collapses when the count is small. Wilson stays inside [0, 1],
    holds its nominal coverage down to single-digit counts, and is asymmetric in
    the direction the data actually supports.
    """
    if trials <= 0:
        return np.nan, np.nan, np.nan
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = (z / denom) * np.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return max(0.0, centre - half), min(1.0, centre + half), half


def block_bootstrap_rate(flags, years, n_boot=CFG.BOOTSTRAP_N, seed=CFG.SEED):
    """Resample whole years, not individual anchors.

    Wilson assumes independent trials. These anchors are not independent: they
    are overlapping space-time windows cut from one catalogue, and a single
    productive swarm supplies many of them. Resampling years keeps each year's
    anchors together, so the interval reflects how much genuinely independent
    information the record holds rather than how many rows were extracted.
    """
    flags = np.asarray(flags, int)
    years = np.asarray(years)
    unique = np.unique(years)
    if unique.size < 3:
        return np.nan, np.nan
    groups = [flags[years == y] for y in unique]
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        pooled = np.concatenate([groups[i] for i in pick])
        draws[b] = pooled.mean() if pooled.size else np.nan
    return float(np.nanpercentile(draws, 2.5)), float(np.nanpercentile(draws, 97.5))


def occurrence_intervals(datasets, alpha=CFG.ALPHA) -> pd.DataFrame:
    """Every occurrence rate with its confidence interval and margin of error.

    Two intervals are given because they answer different questions. Wilson is
    the standard interval for a proportion and is what a reader will expect.
    The year-block interval drops the independence assumption that Wilson needs
    and is the wider, more defensible one; where they diverge, quote the block
    interval.
    """
    conf = int(round((1 - alpha) * 100))
    rows = []
    for radius, data in datasets.items():
        years = data["AnchorTime"].dt.year.to_numpy()
        for threshold in CFG.OCC_THRESHOLDS:
            flags = data[f"y{threshold:g}"].to_numpy(int)
            n, k = flags.size, int(flags.sum())
            lo, hi, half = wilson_interval(k, n)
            blo, bhi = block_bootstrap_rate(flags, years)
            rows.append({
                "Radius (km)": radius,
                "Threshold": f"M ≥ {threshold:g}",
                "n anchors": n,
                "n occurred": k,
                "Rate (%)": 100 * k / n if n else np.nan,
                f"Wilson {conf}% CI": f"{100 * lo:.1f} to {100 * hi:.1f}",
                "Margin of error (pp)": 100 * half,
                f"Year-block {conf}% CI": (f"{100 * blo:.1f} to {100 * bhi:.1f}"
                                           if np.isfinite(blo) else "—"),
                "Block MoE (pp)": (100 * (bhi - blo) / 2 if np.isfinite(blo) else np.nan),
            })
    return pd.DataFrame(rows)

def reliability_table(prob, y, bins=5) -> pd.DataFrame:
    """Observed frequency against forecast probability, the calibration check.

    A probability is only meaningful if, across the occasions it says 20%, the
    thing happens about a fifth of the time. Discrimination scores cannot tell
    you that; this can.
    """
    prob = np.asarray(prob, float)
    y = np.asarray(y, int)
    edges = np.linspace(0, max(prob.max(), 1e-9), bins + 1)
    rows = []
    for k in range(bins):
        lo, hi = edges[k], edges[k + 1]
        sel = (prob >= lo) & (prob < hi if k < bins - 1 else prob <= hi)
        if sel.sum() == 0:
            continue
        rows.append({"Forecast band": f"{100*lo:.0f} to {100*hi:.0f}%",
                     "n": int(sel.sum()),
                     "Mean forecast (%)": 100 * float(prob[sel].mean()),
                     "Observed rate (%)": 100 * float(y[sel].mean()),
                     "Difference (pp)": 100 * float(y[sel].mean() - prob[sel].mean())})
    return pd.DataFrame(rows)

def feature_dictionary() -> pd.DataFrame:
    """The 22 features with their category and description, for the paper."""
    return pd.DataFrame([{"#": i + 1, "Feature": n, "Category": FEATURE_CATEGORIES[n],
                          "Description": FEATURE_DESCRIPTIONS[n]}
                         for i, n in enumerate(FEATURE_NAMES)])


def feature_descriptives(seq) -> pd.DataFrame:
    """Descriptives for each engineered feature, plus its missing-value count."""
    rows = []
    for name in FEATURE_NAMES:
        x = pd.to_numeric(seq[name], errors="coerce")
        v = x.dropna().to_numpy()
        rows.append({"Feature": name, "n valid": v.size, "n missing": int(x.isna().sum()),
                     "M": v.mean() if v.size else np.nan,
                     "SD": v.std(ddof=1) if v.size > 1 else np.nan,
                     "Mdn": np.median(v) if v.size else np.nan,
                     "Min": v.min() if v.size else np.nan,
                     "Max": v.max() if v.size else np.nan,
                     "Skew": stats.skew(v, bias=False) if v.size > 2 else np.nan})
    return pd.DataFrame(rows)


def target_feature_correlations(seq) -> pd.DataFrame:
    """Univariate association of each feature with the mainshock magnitude."""
    rows = []
    for name in FEATURE_NAMES:
        pair = seq[[name, "Target"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) < 10 or pair[name].nunique() < 2:
            rows.append({"Feature": name, "n": len(pair), "Pearson r": np.nan,
                         "p (r)": np.nan, "Spearman ρ": np.nan, "p (ρ)": np.nan,
                         "Strength": "—"})
            continue
        r, rp = stats.pearsonr(pair[name], pair["Target"])
        rho, sp = stats.spearmanr(pair[name], pair["Target"])
        rows.append({"Feature": name, "n": len(pair), "Pearson r": r, "p (r)": rp,
                     "Spearman ρ": rho, "p (ρ)": sp, "Strength": r_label(abs(r))})
    return (pd.DataFrame(rows).sort_values("Pearson r", key=lambda s: s.abs(),
                                           ascending=False).reset_index(drop=True))


# =============================================================================
# PART 9.  NEURAL NETWORKS IN NUMPY -- LSTM, GRU, 1D-CNN
# -----------------------------------------------------------------------------
# The study needs sequence models that run wherever the rest of the script runs.
# Keras and PyTorch are used when they import cleanly (see `sequence_backend`);
# these are the fallbacks that keep the thesis reproducible on a machine with
# neither, and they are small enough to audit -- forward pass, backward pass
# through time, and Adam.
# =============================================================================
def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


class _SeqNet:
    """Shared training loop: minibatch Adam, gradient clipping, early stopping.

    Subclasses supply `_init_params`, `_forward` and `_backward`.  Everything
    else -- the optimiser, the validation loop, restoring the best weights --
    is identical across the three architectures, so it lives here once.
    """

    name = "Sequence network"

    def __init__(self, units=CFG.NN_UNITS, epochs=CFG.NN_EPOCHS, learning_rate=CFG.NN_LR,
                 patience=CFG.NN_PATIENCE, seed=CFG.SEED, batch_size=32, grad_clip=5.0):
        self.units = units
        self.epochs = epochs
        self.lr = learning_rate
        self.patience = patience
        self.seed = seed
        self.batch_size = batch_size
        self.grad_clip = grad_clip
        self.history_ = []

    # -- optimiser ---------------------------------------------------------- #
    def _reset_optimiser(self):
        self.m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.t = 0

    def _adam_step(self, grads):
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        norm = np.sqrt(sum((g ** 2).sum() for g in grads.values()))
        scale = min(1.0, self.grad_clip / (norm + 1e-12))
        for k, g in grads.items():
            g = g * scale
            self.m[k] = b1 * self.m[k] + (1 - b1) * g
            self.v[k] = b2 * self.v[k] + (1 - b2) * g ** 2
            self.p[k] -= (self.lr * (self.m[k] / (1 - b1 ** self.t))
                          / (np.sqrt(self.v[k] / (1 - b2 ** self.t)) + eps))

    # -- training ----------------------------------------------------------- #
    def fit(self, X, y, X_val=None, y_val=None):
        X = np.asarray(X, float)
        y = np.asarray(y, float).reshape(-1, 1)
        self._init_params(X.shape[2])
        self._reset_optimiser()

        rng = np.random.default_rng(self.seed)
        best_loss, best_params, stale = np.inf, None, 0
        for epoch in range(self.epochs):
            order = rng.permutation(len(X))
            for start in range(0, len(X), self.batch_size):
                batch = order[start:start + self.batch_size]
                if batch.size < 2:
                    continue
                xb, yb = X[batch], y[batch]
                pred, cache = self._forward(xb)
                self._adam_step(self._backward(xb, pred, yb, cache))

            train_loss = float(np.mean((self._forward(X)[0] - y) ** 2))
            if X_val is not None and len(X_val):
                target = np.asarray(y_val, float).reshape(-1, 1)
                val_loss = float(np.mean((self.predict(X_val).reshape(-1, 1) - target) ** 2))
            else:
                val_loss = train_loss
            self.history_.append({"epoch": epoch + 1, "train_mse": train_loss,
                                  "val_mse": val_loss})
            if val_loss < best_loss - 1e-6:
                best_loss, stale = val_loss, 0
                best_params = {k: v.copy() for k, v in self.p.items()}
            else:
                stale += 1
                if stale >= self.patience:
                    break
        if best_params is not None:
            self.p = best_params
        self.best_val_mse_ = best_loss
        self.epochs_run_ = len(self.history_)
        self.n_parameters_ = sum(v.size for v in self.p.values())
        return self

    def predict(self, X):
        return self._forward(np.asarray(X, float))[0].ravel()


class NumpyLSTM(_SeqNet):
    """Single-layer LSTM regressor, trained by backpropagation through time."""

    name = "LSTM"

    def _init_params(self, n_features):
        rng = np.random.default_rng(self.seed)
        h = self.units
        scale = 1.0 / np.sqrt(n_features + h)
        self.p = {"W": rng.normal(0, scale, (n_features + h, 4 * h)),
                  "b": np.zeros(4 * h),
                  "Wy": rng.normal(0, 1.0 / np.sqrt(h), (h, 1)),
                  "by": np.zeros(1)}
        # The forget gate starts open; without this bias an LSTM this small
        # spends most of its budget learning not to erase its own state.
        self.p["b"][h:2 * h] = 1.0

    def _forward(self, X):
        B, T, _ = X.shape
        h_dim = self.units
        h = np.zeros((B, h_dim))
        c = np.zeros((B, h_dim))
        cache = []
        for step in range(T):
            z = np.concatenate([X[:, step, :], h], axis=1)
            gates = z @ self.p["W"] + self.p["b"]
            i = _sigmoid(gates[:, :h_dim])
            f = _sigmoid(gates[:, h_dim:2 * h_dim])
            o = _sigmoid(gates[:, 2 * h_dim:3 * h_dim])
            g = np.tanh(gates[:, 3 * h_dim:])
            c_prev = c
            c = f * c_prev + i * g
            tanh_c = np.tanh(c)
            h = o * tanh_c
            cache.append((z, i, f, o, g, c_prev, tanh_c))
        return h @ self.p["Wy"] + self.p["by"], (cache, h)

    def _backward(self, X, y_pred, y_true, cache):
        steps, h_last = cache
        B, T, n_feat = X.shape
        h_dim = self.units
        grads = {k: np.zeros_like(v) for k, v in self.p.items()}

        dy = 2.0 * (y_pred - y_true) / B          # d(MSE)/d(y_pred)
        grads["Wy"] = h_last.T @ dy
        grads["by"] = dy.sum(axis=0)

        dh = dy @ self.p["Wy"].T
        dc = np.zeros((B, h_dim))
        for step in reversed(range(T)):
            z, i, f, o, g, c_prev, tanh_c = steps[step]
            do = dh * tanh_c
            dc = dc + dh * o * (1 - tanh_c ** 2)
            di, dg, df = dc * g, dc * i, dc * c_prev
            dc_prev = dc * f
            dgates = np.concatenate([di * i * (1 - i), df * f * (1 - f),
                                     do * o * (1 - o), dg * (1 - g ** 2)], axis=1)
            grads["W"] += z.T @ dgates
            grads["b"] += dgates.sum(axis=0)
            dh = (dgates @ self.p["W"].T)[:, n_feat:]
            dc = dc_prev
        return grads


class NumpyGRU(_SeqNet):
    """Gated recurrent unit -- the LSTM's cheaper cousin.

    Two gates instead of three and no separate cell state, so roughly 25% fewer
    parameters.  On short sequences and a few hundred training examples -- this
    study's exact situation -- that reduction often matters more than the
    LSTM's extra expressiveness.
    """

    name = "GRU"

    def _init_params(self, n_features):
        rng = np.random.default_rng(self.seed)
        h = self.units
        scale = 1.0 / np.sqrt(n_features + h)
        self.p = {"Wzr": rng.normal(0, scale, (n_features + h, 2 * h)),
                  "bzr": np.zeros(2 * h),
                  "Wh": rng.normal(0, scale, (n_features + h, h)),
                  "bh": np.zeros(h),
                  "Wy": rng.normal(0, 1.0 / np.sqrt(h), (h, 1)),
                  "by": np.zeros(1)}

    def _forward(self, X):
        B, T, _ = X.shape
        h_dim = self.units
        h = np.zeros((B, h_dim))
        cache = []
        for step in range(T):
            x_t = X[:, step, :]
            cat1 = np.concatenate([x_t, h], axis=1)
            gates = cat1 @ self.p["Wzr"] + self.p["bzr"]
            z = _sigmoid(gates[:, :h_dim])          # update gate
            r = _sigmoid(gates[:, h_dim:])          # reset gate
            cat2 = np.concatenate([x_t, r * h], axis=1)
            h_hat = np.tanh(cat2 @ self.p["Wh"] + self.p["bh"])
            h_prev = h
            h = (1 - z) * h_prev + z * h_hat
            cache.append((cat1, cat2, z, r, h_hat, h_prev))
        return h @ self.p["Wy"] + self.p["by"], (cache, h)

    def _backward(self, X, y_pred, y_true, cache):
        steps, h_last = cache
        B, T, n_feat = X.shape
        grads = {k: np.zeros_like(v) for k, v in self.p.items()}

        dy = 2.0 * (y_pred - y_true) / B
        grads["Wy"] = h_last.T @ dy
        grads["by"] = dy.sum(axis=0)
        dh = dy @ self.p["Wy"].T

        for step in reversed(range(T)):
            cat1, cat2, z, r, h_hat, h_prev = steps[step]
            dz = dh * (h_hat - h_prev)
            dh_hat_pre = dh * z * (1 - h_hat ** 2)
            grads["Wh"] += cat2.T @ dh_hat_pre
            grads["bh"] += dh_hat_pre.sum(axis=0)

            dcat2 = dh_hat_pre @ self.p["Wh"].T
            d_rh = dcat2[:, n_feat:]                 # gradient wrt (r * h_prev)
            dr = d_rh * h_prev

            dgates = np.concatenate([dz * z * (1 - z), dr * r * (1 - r)], axis=1)
            grads["Wzr"] += cat1.T @ dgates
            grads["bzr"] += dgates.sum(axis=0)

            # h_prev is reached three ways: the carry term, the reset gate, and
            # the gate pre-activations. All three contributions must be summed.
            dh = (dh * (1 - z) + d_rh * r
                  + (dgates @ self.p["Wzr"].T)[:, n_feat:])
        return grads


class NumpyCNN1D(_SeqNet):
    """Temporal 1D convolution with global max pooling.

    A convolutional net reads the foreshock stream as a set of local patterns
    -- a burst of three events, a magnitude step -- rather than as a state
    carried forward in time.  It trains far faster than a recurrent net and,
    on short sequences, frequently matches one; including it tests whether the
    task actually needs recurrence at all.
    """

    name = "1D-CNN"

    def __init__(self, filters=CFG.CNN_FILTERS, kernel=CFG.CNN_KERNEL, **kwargs):
        super().__init__(**kwargs)
        self.filters = filters
        self.kernel = kernel

    def _init_params(self, n_features):
        rng = np.random.default_rng(self.seed)
        fan_in = self.kernel * n_features
        self.p = {"Wc": rng.normal(0, 1.0 / np.sqrt(fan_in),
                                   (fan_in, self.filters)),
                  "bc": np.zeros(self.filters),
                  "Wy": rng.normal(0, 1.0 / np.sqrt(self.filters), (self.filters, 1)),
                  "by": np.zeros(1)}

    def _windows(self, X):
        """im2col: (B, T, F) -> (B, P, kernel*F) of overlapping time windows."""
        B, T, F = X.shape
        k = min(self.kernel, T)
        P = T - k + 1
        return np.stack([X[:, p:p + k, :].reshape(B, -1) for p in range(P)], axis=1), P

    def _forward(self, X):
        cols, P = self._windows(X)                  # (B, P, k*F)
        pre = cols @ self.p["Wc"] + self.p["bc"]    # (B, P, filters)
        act = np.maximum(pre, 0.0)                  # ReLU
        argmax = act.argmax(axis=1)                 # (B, filters) -- pooled position
        B = X.shape[0]
        rows = np.arange(B)[:, None]
        pooled = act[rows, argmax, np.arange(self.filters)[None, :]]
        return pooled @ self.p["Wy"] + self.p["by"], (cols, pre, argmax, pooled)

    def _backward(self, X, y_pred, y_true, cache):
        cols, pre, argmax, pooled = cache
        B = X.shape[0]
        grads = {k: np.zeros_like(v) for k, v in self.p.items()}

        dy = 2.0 * (y_pred - y_true) / B
        grads["Wy"] = pooled.T @ dy
        grads["by"] = dy.sum(axis=0)

        dpooled = dy @ self.p["Wy"].T                # (B, filters)
        # Only the pooled position of each filter receives gradient, and only
        # when its pre-activation survived the ReLU.
        dpre = np.zeros_like(pre)
        rows = np.arange(B)[:, None]
        filt = np.arange(self.filters)[None, :]
        gate = (pre[rows, argmax, filt] > 0).astype(float)
        dpre[rows, argmax, filt] = dpooled * gate

        grads["Wc"] = np.einsum("bpk,bpf->kf", cols, dpre)
        grads["bc"] = dpre.sum(axis=(0, 1))
        return grads


SEQUENCE_NETS = {"LSTM": NumpyLSTM, "GRU": NumpyGRU, "1D-CNN": NumpyCNN1D}

_BACKEND_CACHE = None


def sequence_backend() -> str:
    """Report which deep-learning backend this environment can actually run.

    Both probes run in a throwaway subprocess.  A framework whose NumPy interop
    is broken still imports successfully, so the probe has to exercise it -- and
    importing a half-broken framework into this process leaves it in
    `sys.modules`, where joblib's worker processes pick it up and print its
    import traceback on every parallel job.
    """
    global _BACKEND_CACHE
    if _BACKEND_CACHE is not None:
        return _BACKEND_CACHE
    probes = {"tensorflow": "import numpy, tensorflow as tf; tf.keras.layers.LSTM(2)",
              "pytorch": "import numpy, torch; torch.from_numpy(numpy.zeros(2))"}
    _BACKEND_CACHE = "numpy"
    for name, code in probes.items():
        try:
            if subprocess.run([sys.executable, "-c", code], capture_output=True,
                              timeout=60).returncode == 0:
                _BACKEND_CACHE = name
                break
        except Exception:
            continue
    return _BACKEND_CACHE


# =============================================================================
# PART 10.  THE MODEL ZOO AND ROLLING-ORIGIN VALIDATION
# -----------------------------------------------------------------------------
# Sixteen forecasters across four families, all scored on the same sequences:
#
#   Baselines   Climatology, Persistence
#   Tabular ML  Random Forest, Extra Trees, Gradient Boosting, Histogram GB,
#               Support Vector Regression, k-Nearest Neighbours, Elastic Net,
#               Multilayer Perceptron
#   Sequence    LSTM, GRU, 1D-CNN                      (raw foreshock stream)
#   Classical   ARIMA, ARIMAX                          (order-indexed series)
#
# Splitting is strictly chronological everywhere.  A random shuffle would let a
# model learn from the future of its own test set, which is the single most
# common way a seismic forecasting result turns out to be an artefact.
# =============================================================================
def chronological_split(seq, fractions=CFG.SPLIT_FRACTIONS):
    """Split an already time-sorted frame into train / validation / test."""
    n = len(seq)
    n_train = int(round(fractions[0] * n))
    n_val = int(round(fractions[1] * n))
    return (seq.iloc[:n_train], seq.iloc[n_train:n_train + n_val],
            seq.iloc[n_train + n_val:])


def split_summary(train, val, test) -> pd.DataFrame:
    total = len(train) + len(val) + len(test)
    rows = []
    for label, part in (("Training", train), ("Validation", val), ("Test", test)):
        rows.append({
            "Partition": label, "n sequences": len(part),
            "% of total": 100 * len(part) / total,
            "Period covered": f"{part['MainshockTime'].min():%b %Y} – "
                              f"{part['MainshockTime'].max():%b %Y}",
            "M (target)": part["Target"].mean(), "SD": part["Target"].std(ddof=1),
            "Min": part["Target"].min(), "Max": part["Target"].max(),
            "n (M ≥ 6.0)": int((part["Target"] >= 6.0).sum())})
    return pd.DataFrame(rows)


def class_distribution(train, val, test) -> pd.DataFrame:
    """Class counts per partition -- the evidence for the imbalance caveat."""
    rows = []
    for label in CFG.MAG_CLASS_LABELS:
        row = {"Magnitude class": label}
        for name, part in (("Training", train), ("Validation", val), ("Test", test)):
            count = int((part["TargetClass"].astype(str) == label).sum())
            row[f"{name} f"] = count
            row[f"{name} %"] = 100 * count / len(part) if len(part) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def build_event_sequences(seq, catalogue, seq_len=CFG.SEQ_LEN):
    """Per-mainshock tensors of its last `seq_len` foreshocks.

    Each timestep carries five channels: magnitude, depth, hours since the prior
    event, and the epicentral offset in latitude and longitude.  Short windows
    are left-padded with zeros so every sequence has the same length.
    """
    cat = catalogue.sort_values("datetime", kind="mergesort").reset_index(drop=True)
    origin = cat["datetime"].iloc[0]
    t_days = (cat["datetime"] - origin).dt.total_seconds().to_numpy() / 86400.0
    lat, lon = cat["Latitude"].to_numpy(), cat["Longitude"].to_numpy()
    mag, depth = cat["Magnitude"].to_numpy(), cat["Depth"].to_numpy()

    tensors = np.zeros((len(seq), seq_len, 5), dtype=float)
    for k, (_, row) in enumerate(seq.iterrows()):
        t_end = (row["MainshockTime"] - origin).total_seconds() / 86400.0
        lo = np.searchsorted(t_days, t_end - CFG.T_OBS_DAYS, side="left")
        hi = np.searchsorted(t_days, t_end, side="left")
        idx = np.arange(lo, hi)
        if idx.size:
            near = haversine_km(row["MainshockLat"], row["MainshockLon"],
                                lat[idx], lon[idx]) <= CFG.RADIUS_KM
            idx = idx[near][-seq_len:]
        if idx.size == 0:
            continue
        gaps = np.diff(np.concatenate([[t_days[idx[0]]], t_days[idx]])) * 24.0
        block = np.column_stack([mag[idx], depth[idx], gaps,
                                 lat[idx] - row["MainshockLat"],
                                 lon[idx] - row["MainshockLon"]])
        tensors[k, seq_len - block.shape[0]:, :] = block
    return tensors


# Features whose natural scale is multiplicative rather than additive.  Energy
# spans roughly ten orders of magnitude across the catalogue and x7 is a
# probability that can fall below 1e-4; on their raw scale they dominate any
# distance, kernel or gradient computation and leave the tree ensembles
# unaffected, so the transform costs nothing and fixes a great deal.
LOG_FEATURES = ("Energy", "x7_lsq", "x7_mlk", "T_elaps6", "T_elaps65",
                "T_elaps7", "T_elaps75",
                # Fault distances run from 0.18 km to 617 km, three and a half
                # orders of magnitude, so they get the same treatment.
                "Dist_min", "Dist_mean", "Dist_std", "Dist_wmean")
WINSOR_QUANTILES = (0.01, 0.99)


class DataBundle:
    """Everything the model zoo needs, with fold-local preprocessing.

    Imputation, winsorising and scaling are refitted inside every fold from that
    fold's training rows only.  Fitting them once on the whole data set is a
    subtle and very common leak: the test rows would contribute to the median,
    the clipping bounds and the standard deviation used to transform them.
    """

    def __init__(self, sequences, catalogue):
        self.seq = sequences.reset_index(drop=True)
        self.y = self.seq["Target"].to_numpy(float)
        self.raw_tab = self.seq[FEATURE_NAMES].replace([np.inf, -np.inf], np.nan)
        self.tab = self._log_transform(self.raw_tab)
        self.tensors = build_event_sequences(self.seq, catalogue)
        self.times = self.seq["MainshockTime"].to_numpy()

    @staticmethod
    def _log_transform(frame):
        """Signed log10 for the multiplicative features; identity elsewhere.

        `log10(1 + |x|)` keeps the transform defined at zero and monotone, so a
        tree ensemble splits on exactly the same ordering it would have used on
        the raw values.
        """
        out = frame.copy()
        for name in LOG_FEATURES:
            if name in out.columns:
                out[name] = np.sign(out[name]) * np.log10(1.0 + out[name].abs())
        return out

    def tabular(self, train_idx, test_idx):
        """Imputed and winsorised feature matrices, bounds from training rows.

        Several features are heavy-tailed by construction: the magnitude deficit
        diverges as the fitted b-value approaches zero, which a sparse window can
        produce.  Clipping at the training 1st and 99th percentiles bounds those
        excursions without discarding the sequence.  The clip is monotone, so it
        changes nothing for the tree ensembles and keeps the linear, kernel and
        neural models from being driven by a single pathological window.
        """
        train = self.tab.iloc[train_idx]
        fill = train.median(numeric_only=True).fillna(0.0)
        lo = train.quantile(WINSOR_QUANTILES[0])
        hi = train.quantile(WINSOR_QUANTILES[1])
        prepare = lambda part: (part.fillna(fill).clip(lower=lo, upper=hi, axis=1)
                                .to_numpy(float))
        return prepare(train), prepare(self.tab.iloc[test_idx])

    def sequence(self, train_idx, test_idx):
        """Channel-standardised tensors, scaler and clip fitted on training rows.

        The inter-event-gap channel is log-transformed first: gaps range from
        seconds to a fortnight, and standardising that raw would hand the network
        one channel with a range a hundred times the others.
        """
        tr, te = self.tensors[train_idx].copy(), self.tensors[test_idx].copy()
        for block in (tr, te):
            block[:, :, 2] = np.log1p(np.clip(block[:, :, 2], 0, None))
        flat = tr.reshape(-1, tr.shape[2])
        lo = np.percentile(flat, 100 * WINSOR_QUANTILES[0], axis=0)
        hi = np.percentile(flat, 100 * WINSOR_QUANTILES[1], axis=0)
        scaler = StandardScaler().fit(np.clip(flat, lo, hi))

        def prepare(t):
            shape = t.shape
            clipped = np.clip(t.reshape(-1, shape[2]), lo, hi)
            return scaler.transform(clipped).reshape(shape)

        return prepare(tr), prepare(te)


# --------------------------------------------------------------------------- #
# Tabular estimators
# --------------------------------------------------------------------------- #
def tabular_estimators(seed=CFG.SEED, rf_params=None):
    """Return `{name: (estimator, family, hyperparameter_summary)}`.

    Distance- and gradient-based learners are wrapped in a scaling pipeline;
    tree ensembles are scale-invariant and are left alone.
    """
    rf_params = rf_params or {"n_estimators": 600, "max_depth": None,
                              "min_samples_leaf": 1, "max_features": "sqrt"}
    scaled = lambda est: Pipeline([("scale", StandardScaler()), ("model", est)])
    return {
        "Random Forest": (
            RandomForestRegressor(random_state=seed, n_jobs=-1, **rf_params),
            "Tree ensemble (bagging)",
            ", ".join(f"{k}={v}" for k, v in rf_params.items())),
        # Depth is capped so the fitted forest can be shipped to the browser for
        # the interactive panel. Unrestricted it reaches 13 MB of JSON and scores
        # 0.4904; at depth 10 it is 1.7 MB and scores 0.4922, a difference an
        # order of magnitude inside the bootstrap interval on this test set.
        "Extra Trees": (
            ExtraTreesRegressor(n_estimators=200, max_depth=10, random_state=seed, n_jobs=-1),
            "Tree ensemble (bagging)",
            "n_estimators=200, max_depth=10, fully randomised splits"),
        "Gradient Boosting": (
            GradientBoostingRegressor(n_estimators=400, learning_rate=0.05,
                                      max_depth=3, subsample=0.8, random_state=seed),
            "Tree ensemble (boosting)",
            "n_estimators=400, lr=0.05, max_depth=3, subsample=0.8"),
        "Histogram GB": (
            HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05,
                                          max_depth=6, random_state=seed),
            "Tree ensemble (boosting)", "max_iter=400, lr=0.05, max_depth=6"),
        "Support Vector Regression": (
            scaled(SVR(kernel="rbf", C=10.0, gamma="scale", epsilon=0.05)),
            "Kernel method", "RBF kernel, C=10, ε=0.05, standardised inputs"),
        "k-Nearest Neighbours": (
            scaled(KNeighborsRegressor(n_neighbors=10, weights="distance")),
            "Instance based", "k=10, distance weighting, standardised inputs"),
        "Elastic Net": (
            scaled(ElasticNet(alpha=0.05, l1_ratio=0.5, max_iter=10000,
                              random_state=seed)),
            "Regularised linear", "α=0.05, L1 ratio=0.5"),
        "Ridge Regression": (
            scaled(Ridge(alpha=5.0, random_state=seed)),
            "Regularised linear", "α=5.0"),
        "Multilayer Perceptron": (
            scaled(MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1.0, max_iter=3000,
                                early_stopping=True, validation_fraction=0.2,
                                n_iter_no_change=40, random_state=seed)),
            "Feed-forward network",
            "hidden=(64, 32), α=1.0, early stopping on a 20% inner split"),
    }


def tune_random_forest(Xtr, ytr, Xva, yva, grid=None, seed=CFG.SEED):
    """Grid search scored on the validation split, not by cross-validation.

    k-fold would shuffle time back together; the held-out development set is the
    only honest way to tune a chronologically split model.
    """
    grid = grid or CFG.RF_GRID
    keys = list(grid)
    best, trials = None, []
    for values in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, values))
        model = RandomForestRegressor(random_state=seed, n_jobs=-1, **params)
        model.fit(Xtr, ytr)
        rmse = float(np.sqrt(np.mean((model.predict(Xva) - yva) ** 2)))
        trials.append({**params, "Validation RMSE": rmse})
        if best is None or rmse < best[0]:
            best = (rmse, params, model)
    return (best[2], best[1],
            pd.DataFrame(trials).sort_values("Validation RMSE").reset_index(drop=True))


def fit_random_forest_classifier(Xtr, ytr_class, params, seed=CFG.SEED):
    """Classifier mirroring the tuned regressor, with balanced class weights.

    Major events are rare; without the weighting the forest maximises accuracy
    by never predicting the class the study exists to detect.
    """
    keep = {k: v for k, v in params.items()
            if k in {"n_estimators", "max_depth", "min_samples_leaf", "max_features"}}
    model = RandomForestClassifier(random_state=seed, n_jobs=-1,
                                   class_weight="balanced_subsample", **keep)
    return model.fit(Xtr, ytr_class)


def feature_importance_table(model, X, y, seed=CFG.SEED, n_repeats=20) -> pd.DataFrame:
    """Impurity importance beside permutation importance.

    Impurity importance is biased toward high-cardinality continuous features,
    so the permutation values measured on held-out data are the ones to trust;
    both are reported because the thesis cites the built-in metric by name.
    """
    perm = permutation_importance(model, X, y, n_repeats=n_repeats,
                                  random_state=seed, n_jobs=-1)
    table = pd.DataFrame({"Feature": FEATURE_NAMES,
                          "Impurity importance": model.feature_importances_,
                          "Permutation importance": perm.importances_mean,
                          "SD (permutation)": perm.importances_std})
    table = table.sort_values("Permutation importance", ascending=False).reset_index(drop=True)
    table.insert(0, "Rank", np.arange(1, len(table) + 1))
    table["Cumulative impurity %"] = (table["Impurity importance"].cumsum()
                                      / table["Impurity importance"].sum() * 100)
    return table


# --------------------------------------------------------------------------- #
# Classical time-series estimators
# --------------------------------------------------------------------------- #
def _fit_arima(y_train, n_ahead, exog_train=None, exog_test=None, max_order=2):
    """Small ARIMA / ARIMAX grid selected by AIC, forecast `n_ahead` steps.

    The mainshock series is indexed by event order, not by clock time: these
    events are irregularly spaced, so the "lag" an AR term refers to is one
    mainshock, not one day.  That is a real limitation of applying ARIMA here
    and the table note says so.
    """
    from statsmodels.tsa.arima.model import ARIMA
    best = (np.inf, None)
    for p, d, q in itertools.product(range(max_order + 1), range(2),
                                     range(max_order + 1)):
        if p == 0 and q == 0:
            continue
        try:
            fit = ARIMA(y_train, order=(p, d, q), exog=exog_train,
                        enforce_stationarity=False,
                        enforce_invertibility=False).fit(method_kwargs={"warn_convergence": False})
            if np.isfinite(fit.aic) and fit.aic < best[0]:
                best = (fit.aic, fit, (p, d, q))
        except Exception:
            continue
    if best[1] is None:
        return np.full(n_ahead, float(np.mean(y_train))), None
    try:
        pred = best[1].forecast(steps=n_ahead, exog=exog_test)
        return np.asarray(pred, float), best[2]
    except Exception:
        return np.full(n_ahead, float(np.mean(y_train))), best[2]


def _exog_columns(bundle, train_idx, k=5):
    """The k features most correlated with the target inside the training rows.

    Chosen on training data only -- selecting exogenous regressors using the
    full series would leak the test period into the model specification.
    """
    tab = bundle.tab.iloc[train_idx].fillna(0.0)
    y = bundle.y[train_idx]
    scores = {}
    for name in FEATURE_NAMES:
        col = tab[name].to_numpy()
        if np.std(col) == 0:
            continue
        scores[name] = abs(np.corrcoef(col, y)[0, 1])
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return ranked or FEATURE_NAMES[:k]


# --------------------------------------------------------------------------- #
# Uniform fit/predict across every family
# --------------------------------------------------------------------------- #
def predict_model(name, bundle, train_idx, test_idx, seed=CFG.SEED,
                  rf_params=None, nn_epochs=None, return_model=False):
    """Fit `name` on `train_idx` and return its predictions for `test_idx`.

    One entry point for all four families, so the cross-validation loop and the
    final test evaluation cannot accidentally treat two models differently.
    """
    y_train = bundle.y[train_idx]
    n_test = len(test_idx)

    if name == "Climatology (training mean)":
        model, pred = None, np.full(n_test, y_train.mean())
    elif name == "Persistence (previous mainshock)":
        model = None
        previous = np.concatenate([[y_train[-1]], bundle.y[test_idx][:-1]])
        pred = previous
    elif name in SEQUENCE_NETS:
        Xtr, Xte = bundle.sequence(train_idx, test_idx)
        # Carve an inner validation slice off the END of the training block, so
        # early stopping is judged on the most recent data available to it.
        # min, not max: max(0.85n, n-1) collapses to n-1 for every n above 7,
        # which leaves a single row to early-stop on and makes the stopping
        # signal noise. The clamps keep at least one row on each side.
        cut = max(1, min(int(0.85 * len(Xtr)), len(Xtr) - 1))
        net = SEQUENCE_NETS[name](seed=seed, epochs=nn_epochs or CFG.NN_EPOCHS)
        net.fit(Xtr[:cut], y_train[:cut], Xtr[cut:], y_train[cut:])
        model, pred = net, net.predict(Xte)
    elif name in ("ARIMA", "ARIMAX"):
        if name == "ARIMA":
            pred, order = _fit_arima(y_train, n_test)
            model = {"order": order, "exog": None}
        else:
            cols = _exog_columns(bundle, train_idx)
            keep = [FEATURE_NAMES.index(c) for c in cols]
            tab_tr, tab_te = bundle.tabular(train_idx, test_idx)
            ex_tr, ex_te = tab_tr[:, keep], tab_te[:, keep]
            pred, order = _fit_arima(y_train, n_test, ex_tr, ex_te)
            model = {"order": order, "exog": cols}
    else:
        Xtr, Xte = bundle.tabular(train_idx, test_idx)
        estimator = tabular_estimators(seed, rf_params)[name][0]
        estimator.fit(Xtr, y_train)
        model, pred = estimator, estimator.predict(Xte)

    pred = np.asarray(pred, float).ravel()
    if pred.size != n_test:                      # a failed ARIMA forecast
        pred = np.full(n_test, y_train.mean())
    pred = np.nan_to_num(pred, nan=float(y_train.mean()))
    return (pred, model) if return_model else pred


def model_registry(rf_params=None) -> pd.DataFrame:
    """The inventory table: what each model is and what it reads."""
    rows = [
        {"Model": "Climatology (training mean)", "Family": "Baseline",
         "Input representation": "None (constant)",
         "Key settings": "Predicts the training-set mean for every sequence"},
        {"Model": "Persistence (previous mainshock)", "Family": "Baseline",
         "Input representation": "Previous target",
         "Key settings": "Reuses the magnitude of the preceding mainshock"},
    ]
    for name, (_, family, params) in tabular_estimators(rf_params=rf_params).items():
        rows.append({"Model": name, "Family": family,
                     "Input representation": "22 engineered features",
                     "Key settings": params})
    rows += [
        {"Model": "LSTM", "Family": "Recurrent network",
         "Input representation": f"{CFG.SEQ_LEN} × 5 event stream",
         "Key settings": f"{CFG.NN_UNITS} units, Adam (lr={CFG.NN_LR}), "
                         f"early stopping (patience {CFG.NN_PATIENCE})"},
        {"Model": "GRU", "Family": "Recurrent network",
         "Input representation": f"{CFG.SEQ_LEN} × 5 event stream",
         "Key settings": f"{CFG.NN_UNITS} units, two gates, same optimiser as the LSTM"},
        {"Model": "1D-CNN", "Family": "Convolutional network",
         "Input representation": f"{CFG.SEQ_LEN} × 5 event stream",
         "Key settings": f"{CFG.CNN_FILTERS} filters, kernel {CFG.CNN_KERNEL}, "
                         "ReLU, global max pooling"},
        {"Model": "ARIMA", "Family": "Classical time series",
         "Input representation": "Order-indexed target series",
         "Key settings": "(p, d, q) up to (2, 1, 2), selected by AIC"},
        {"Model": "ARIMAX", "Family": "Classical time series",
         "Input representation": "Target series + 5 exogenous features",
         "Key settings": "As ARIMA, with the 5 features most correlated with the "
                         "target in the training rows"},
    ]
    return pd.DataFrame(rows)


ALL_MODELS = (["Climatology (training mean)", "Persistence (previous mainshock)"]
              + list(tabular_estimators().keys())
              + list(SEQUENCE_NETS.keys()) + ["ARIMA", "ARIMAX"])


def rolling_origin_cv(bundle, n_train_val, folds=CFG.CV_FOLDS, models=None,
                      seed=CFG.SEED, rf_params=None, nn_epochs=None, verbose=True):
    """Expanding-window validation over the training and validation partitions.

    Fold i trains on everything before its test block and predicts the block
    that follows.  The training window only ever grows, which mirrors how the
    model would actually be used: you forecast the next sequence knowing every
    sequence that came before it and none that came after.
    """
    models = models or ALL_MODELS
    block = n_train_val // (folds + 1)
    if block < 10:
        raise ValueError("Too few sequences for rolling-origin validation.")

    records = []
    for fold in range(folds):
        train_end = block * (fold + 1)
        test_end = min(block * (fold + 2), n_train_val)
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(train_end, test_end)
        if test_idx.size < 5:
            continue
        if verbose:
            print(f"      fold {fold + 1}/{folds}: train n={train_idx.size}, "
                  f"test n={test_idx.size}")
        y_true = bundle.y[test_idx]
        for name in models:
            pred = predict_model(name, bundle, train_idx, test_idx, seed=seed,
                                 rf_params=rf_params, nn_epochs=nn_epochs)
            err = pred - y_true
            records.append({"Model": name, "Fold": fold + 1,
                            "n train": train_idx.size, "n test": test_idx.size,
                            "RMSE": float(np.sqrt(np.mean(err ** 2))),
                            "MAE": float(np.mean(np.abs(err)))})
    return pd.DataFrame(records)


def cv_summary(cv) -> pd.DataFrame:
    """Mean +/- SD across folds, ranked, with the per-fold mean rank."""
    ranks = cv.pivot(index="Fold", columns="Model", values="RMSE").rank(axis=1)
    g = cv.groupby("Model")
    out = pd.DataFrame({
        "Model": g.size().index,
        "Folds": g.size().to_numpy(),
        "M RMSE": g["RMSE"].mean().to_numpy(),
        "SD RMSE": g["RMSE"].std(ddof=1).to_numpy(),
        "Min RMSE": g["RMSE"].min().to_numpy(),
        "Max RMSE": g["RMSE"].max().to_numpy(),
        "M MAE": g["MAE"].mean().to_numpy(),
        "Mean rank": ranks.mean().reindex(g.size().index).to_numpy()})
    return out.sort_values("M RMSE").reset_index(drop=True)


def friedman_nemenyi(cv):
    """Friedman omnibus test across models, with Nemenyi critical difference.

    This is the standard protocol for comparing many models over several data
    splits (Demsar, 2006): a rank-based omnibus test first, and a single
    critical difference afterwards rather than a wall of pairwise p-values.
    """
    matrix = cv.pivot(index="Fold", columns="Model", values="RMSE").dropna()
    k, n = matrix.shape[1], matrix.shape[0]
    chi2, p = stats.friedmanchisquare(*[matrix[c].to_numpy() for c in matrix.columns])
    ranks = matrix.rank(axis=1).mean()
    # Nemenyi critical difference at alpha = .05, using the studentised range
    # divided by sqrt(2); q for alpha=.05 is tabulated, approximated here.
    q_alpha = stats.norm.ppf(1 - CFG.ALPHA / (k * (k - 1))) * np.sqrt(2)
    cd = q_alpha * np.sqrt(k * (k + 1) / (6 * n))
    best_rank = ranks.min()
    summary = pd.DataFrame({
        "Model": ranks.index, "Mean rank": ranks.to_numpy(),
        "Rank difference from best": ranks.to_numpy() - best_rank,
        "Distinguishable from best": np.where(ranks.to_numpy() - best_rank > cd,
                                              "Yes", "No")}).sort_values("Mean rank")
    test = pd.DataFrame([
        {"Quantity": "Friedman χ²", "Value": f"{chi2:.3f}"},
        {"Quantity": "df", "Value": f"{k - 1}"},
        {"Quantity": "p", "Value": fmt_p(p)},
        {"Quantity": "Models compared (k)", "Value": f"{k}"},
        {"Quantity": "Validation folds (N)", "Value": f"{n}"},
        {"Quantity": "Nemenyi critical difference (α = .05)", "Value": f"{cd:.3f}"},
        {"Quantity": "Decision",
         "Value": ("At least one model differs" if p < CFG.ALPHA
                   else "No model is distinguishable from the others")}])
    return test, summary.reset_index(drop=True)


# =============================================================================
# PART 11.  EVALUATION AND MODEL COMPARISON
# -----------------------------------------------------------------------------
# Every headline metric is reported with a bootstrap confidence interval.  A
# test partition of a hundred sequences produces an RMSE whose third decimal is
# noise, and a point estimate alone invites the reader to over-read it.
# =============================================================================
def regression_metrics(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    err = y_pred - y_true
    mse = float(np.mean(err ** 2))
    ss_res, ss_tot = float((err ** 2).sum()), float(((y_true - y_true.mean()) ** 2).sum())
    return {"n": y_true.size, "MSE": mse, "RMSE": float(np.sqrt(mse)),
            "MAE": float(np.mean(np.abs(err))),
            "MAPE (%)": float(np.mean(np.abs(err / np.where(y_true == 0, np.nan, y_true))) * 100),
            "R²": 1 - ss_res / ss_tot if ss_tot > 0 else np.nan,
            "Bias (ME)": float(np.mean(err)), "Max |error|": float(np.max(np.abs(err))),
            "% within ±0.3": float(np.mean(np.abs(err) <= 0.3) * 100),
            "% within ±0.5": float(np.mean(np.abs(err) <= 0.5) * 100)}


def _bootstrap_ci(y_true, y_pred, statistic, n_boot=CFG.BOOTSTRAP_N, seed=CFG.SEED):
    rng = np.random.default_rng(seed)
    n = len(y_true)
    draws = np.asarray([statistic(y_true[i], y_pred[i])
                        for i in (rng.integers(0, n, n) for _ in range(n_boot))])
    draws = draws[np.isfinite(draws)]
    if draws.size == 0:
        return np.nan, np.nan
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def regression_table(results, ci=True, seed=CFG.SEED) -> pd.DataFrame:
    """`results` maps a row label to `{"y_true": ..., "y_pred": ...}`."""
    rows = []
    for label, payload in results.items():
        y_true = np.asarray(payload["y_true"], float)
        y_pred = np.asarray(payload["y_pred"], float)
        row = {"Model and partition": label, **regression_metrics(y_true, y_pred)}
        if ci:
            lo, hi = _bootstrap_ci(y_true, y_pred,
                                   lambda a, b: float(np.sqrt(np.mean((b - a) ** 2))),
                                   seed=seed)
            row["95% CI for RMSE"] = f"[{lo:.3f}, {hi:.3f}]"
        rows.append(row)
    return pd.DataFrame(rows)


def leaderboard(predictions, y_true, reference="Climatology (training mean)") -> pd.DataFrame:
    """Every model on the held-out test partition, ranked, with a skill score.

    Skill is the percentage reduction in mean squared error relative to
    climatology.  A negative skill score means the model is worse than quoting
    the historical average, which is the result a reader most needs to see.
    """
    y_true = np.asarray(y_true, float)
    ref_mse = float(np.mean((np.asarray(predictions[reference], float) - y_true) ** 2))
    rows = []
    for name, pred in predictions.items():
        m = regression_metrics(y_true, pred)
        lo, hi = _bootstrap_ci(y_true, np.asarray(pred, float),
                               lambda a, b: float(np.sqrt(np.mean((b - a) ** 2))))
        rows.append({"Model": name, "RMSE": m["RMSE"],
                     "95% CI for RMSE": f"[{lo:.3f}, {hi:.3f}]",
                     "MAE": m["MAE"], "R²": m["R²"], "Bias": m["Bias (ME)"],
                     "% within ±0.3": m["% within ±0.3"],
                     "Skill vs. climatology (%)": 100 * (1 - m["MSE"] / ref_mse)})
    out = pd.DataFrame(rows).sort_values("RMSE").reset_index(drop=True)
    out.insert(0, "Rank", np.arange(1, len(out) + 1))
    return out


def compare_models(y_true, pred_a, pred_b, name_a, name_b) -> pd.DataFrame:
    """Paired tests on two models' absolute errors over the same test set.

    Diebold-Mariano is the standard forecast-comparison test; the Wilcoxon
    signed-rank test is included because the loss differentials are not normal.
    """
    y_true = np.asarray(y_true, float)
    err_a = np.abs(np.asarray(pred_a, float) - y_true)
    err_b = np.abs(np.asarray(pred_b, float) - y_true)
    diff = err_a - err_b

    t_stat, t_p = stats.ttest_rel(err_a, err_b)
    try:
        w_stat, w_p = stats.wilcoxon(err_a, err_b)
    except ValueError:
        w_stat, w_p = np.nan, np.nan
    sd = diff.std(ddof=1)
    dm = diff.mean() / (sd / np.sqrt(diff.size)) if sd > 0 else np.nan
    dm_p = 2 * stats.norm.sf(abs(dm)) if np.isfinite(dm) else np.nan
    pooled = np.sqrt((err_a.var(ddof=1) + err_b.var(ddof=1)) / 2)
    better = name_b if diff.mean() > 0 else name_a
    significant = min([p for p in (t_p, w_p, dm_p) if np.isfinite(p)], default=1) < CFG.ALPHA

    return pd.DataFrame([
        {"Comparison": f"{name_a} vs. {name_b}", "Statistic": "Mean |error| difference",
         "Value": diff.mean(), "p": np.nan,
         "Interpretation": f"positive favours {name_b}"},
        {"Comparison": "", "Statistic": "Paired t", "Value": t_stat, "p": t_p,
         "Interpretation": "Significant" if t_p < CFG.ALPHA else "Not significant"},
        {"Comparison": "", "Statistic": "Wilcoxon signed-rank W", "Value": w_stat,
         "p": w_p, "Interpretation": ("Significant" if (np.isfinite(w_p) and w_p < CFG.ALPHA)
                                      else "Not significant")},
        {"Comparison": "", "Statistic": "Diebold–Mariano DM", "Value": dm, "p": dm_p,
         "Interpretation": ("Significant" if (np.isfinite(dm_p) and dm_p < CFG.ALPHA)
                            else "Not significant")},
        {"Comparison": "", "Statistic": "Cohen's d (paired errors)",
         "Value": diff.mean() / pooled if pooled > 0 else np.nan, "p": np.nan,
         "Interpretation": (f"{better} has lower error" if significant
                            else "No significant difference")}])


def pairwise_dm_matrix(predictions, y_true, models) -> pd.DataFrame:
    """Diebold-Mariano p-values for every pair among the leading models."""
    y_true = np.asarray(y_true, float)
    out = pd.DataFrame("", index=models, columns=models, dtype=object)
    for a in models:
        for b in models:
            if a == b:
                out.loc[a, b] = "—"
                continue
            diff = (np.abs(np.asarray(predictions[a], float) - y_true)
                    - np.abs(np.asarray(predictions[b], float) - y_true))
            sd = diff.std(ddof=1)
            if sd == 0:
                out.loc[a, b] = "—"
                continue
            dm = diff.mean() / (sd / np.sqrt(diff.size))
            out.loc[a, b] = fmt_p(2 * stats.norm.sf(abs(dm)))
    out.insert(0, "Model", models)
    return out.reset_index(drop=True)


def _ljung_box(x, lags=10):
    """Ljung-Box Q for residual autocorrelation, computed without statsmodels."""
    x = np.asarray(x, float) - np.mean(x)
    n, denom, q = x.size, (x ** 2).sum(), 0.0
    for k in range(1, lags + 1):
        q += ((x[k:] * x[:-k]).sum() / denom) ** 2 / (n - k)
    q *= n * (n + 2)
    return float(q), float(stats.chi2.sf(q, lags))


def residual_diagnostics(results) -> pd.DataFrame:
    """Bias, normality, heteroscedasticity and autocorrelation of residuals."""
    rows = []
    for label, payload in results.items():
        y_true = np.asarray(payload["y_true"], float)
        pred = np.asarray(payload["y_pred"], float)
        resid = pred - y_true
        t_stat, t_p = stats.ttest_1samp(resid, 0.0)
        sw_w, sw_p = stats.shapiro(resid[:5000])
        # Breusch-Pagan style check: regress squared residuals on the prediction.
        slope, _, _, p_het, _ = stats.linregress(pred, resid ** 2)
        lb_q, lb_p = _ljung_box(resid, lags=min(10, max(1, len(resid) // 5)))
        rows.append({"Model": label, "n": resid.size, "Mean residual": resid.mean(),
                     "SD": resid.std(ddof=1), "t (mean = 0)": t_stat, "p (bias)": t_p,
                     "Shapiro–Wilk W": sw_w, "p (normality)": sw_p,
                     "Heteroscedasticity slope": slope, "p (heterosced.)": p_het,
                     "Ljung–Box Q": lb_q, "p (autocorr.)": lb_p})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def confusion_table(y_true, y_pred, labels):
    """Confusion matrix with row totals, formatted for the paper."""
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    display = pd.DataFrame(matrix, index=labels, columns=labels).astype(object)
    for i, label in enumerate(labels):
        total = matrix[i].sum()
        for j, col in enumerate(labels):
            pct = 100 * matrix[i, j] / total if total else 0
            display.loc[label, col] = f"{matrix[i, j]} ({pct:.1f}%)"
    display["Total actual"] = matrix.sum(axis=1)
    display = display.reset_index()
    display.columns = ["Actual class"] + list(display.columns[1:])
    return matrix, display


def classification_report_table(y_true, y_pred, labels) -> pd.DataFrame:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0)
    rows = [{"Magnitude class": l, "Precision": p, "Recall": r, "F1-score": f,
             "Support": int(s)}
            for l, p, r, f, s in zip(labels, precision, recall, f1, support)]
    for average, name in (("macro", "Macro average"), ("weighted", "Weighted average")):
        rows.append({
            "Magnitude class": name,
            "Precision": precision_score(y_true, y_pred, labels=labels,
                                         average=average, zero_division=0),
            "Recall": recall_score(y_true, y_pred, labels=labels,
                                   average=average, zero_division=0),
            "F1-score": f1_score(y_true, y_pred, labels=labels,
                                 average=average, zero_division=0),
            "Support": int(support.sum())})
    return pd.DataFrame(rows)


def overall_classification_table(y_true, y_pred, labels, seed=CFG.SEED) -> pd.DataFrame:
    """Accuracy, macro F1 and both kappas, each with a bootstrap 95% CI."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    n = matrix.sum()
    metrics = {
        "Accuracy": lambda a, b: float(np.mean(a == b)),
        "Macro F1": lambda a, b: float(f1_score(a, b, labels=labels, average="macro",
                                                zero_division=0)),
        "Cohen's κ": lambda a, b: float(cohen_kappa_score(a, b, labels=labels)),
        "Weighted κ (quadratic)": lambda a, b: float(
            cohen_kappa_score(a, b, labels=labels, weights="quadratic"))}

    rng = np.random.default_rng(seed)
    boot = {k: [] for k in metrics}
    for _ in range(CFG.BOOTSTRAP_N):
        idx = rng.integers(0, len(y_true), len(y_true))
        a, b = y_true[idx], y_pred[idx]
        if len(np.unique(a)) < 2:
            continue
        for k, fn in metrics.items():
            boot[k].append(fn(a, b))

    rows = []
    for name, fn in metrics.items():
        value = fn(y_true, y_pred)
        draws = np.asarray(boot[name], float)
        lo, hi = ((np.percentile(draws, 2.5), np.percentile(draws, 97.5))
                  if draws.size else (np.nan, np.nan))
        rows.append({"Metric": name, "Estimate": value,
                     "95% CI": f"[{lo:.3f}, {hi:.3f}]" if np.isfinite(lo) else "—",
                     "Interpretation": kappa_label(value) if "κ" in name else "—"})
    # Pre-formatted so the count is not rendered with the statistics' decimals.
    rows.append({"Metric": "Test sequences (N)", "Estimate": f"{int(n):,}",
                 "95% CI": "—", "Interpretation": "—"})
    rows.append({"Metric": "Majority-class rate (no-skill accuracy)",
                 "Estimate": float(matrix.sum(axis=1).max() / n), "95% CI": "—",
                 "Interpretation": "Reference for the accuracy above"})
    return pd.DataFrame(rows)


def probabilistic_skill_table(y_true_mag, prob_sources, threshold=6.0) -> pd.DataFrame:
    """Threshold-free discrimination for the M >= `threshold` forecast.

    A classifier can be perfectly useless at its own argmax and still rank
    sequences correctly.  ROC AUC and average precision measure that ranking;
    the Brier skill score says whether the probabilities themselves beat simply
    quoting the base rate every time.
    """
    actual = (np.asarray(y_true_mag, float) >= threshold).astype(int)
    base_rate = actual.mean()
    brier_ref = float(np.mean((base_rate - actual) ** 2))
    rows = []
    for label, prob in prob_sources.items():
        prob = np.clip(np.asarray(prob, float), 0.0, 1.0)
        if len(np.unique(actual)) < 2:
            rows.append({"Probability source": label, "ROC AUC": np.nan,
                         "Average precision": np.nan, "Brier score": np.nan,
                         "Brier skill score": np.nan, "Base rate": base_rate})
            continue
        brier = brier_score_loss(actual, prob)
        rows.append({"Probability source": label,
                     "ROC AUC": roc_auc_score(actual, prob),
                     "Average precision": average_precision_score(actual, prob),
                     "Brier score": brier,
                     "Brier skill score": 1 - brier / brier_ref if brier_ref > 0 else np.nan,
                     "Base rate": base_rate})
    return pd.DataFrame(rows)


def binary_alarm_table(y_true_mag, y_pred_mag, threshold=6.0) -> pd.DataFrame:
    """Treat the forecast as an M >= threshold alarm and score it operationally.

    Accuracy over three ordinal classes hides the question a disaster-management
    reader actually has: when the model calls a strong event, how often is it
    right, and how many does it miss.
    """
    actual = np.asarray(y_true_mag, float) >= threshold
    alarm = np.asarray(y_pred_mag, float) >= threshold
    tp = int((actual & alarm).sum())
    fp = int((~actual & alarm).sum())
    fn = int((actual & ~alarm).sum())
    tn = int((~actual & ~alarm).sum())
    pod = tp / (tp + fn) if tp + fn else np.nan
    far = fp / (tp + fp) if tp + fp else np.nan
    pofd = fp / (fp + tn) if fp + tn else np.nan
    csi = tp / (tp + fp + fn) if tp + fp + fn else np.nan
    return pd.DataFrame([
        {"Quantity": f"True positives (forecast and observed M ≥ {threshold})", "Value": tp},
        {"Quantity": "False positives (false alarms)", "Value": fp},
        {"Quantity": "False negatives (missed events)", "Value": fn},
        {"Quantity": "True negatives", "Value": tn},
        {"Quantity": "Probability of detection (POD / recall)", "Value": pod},
        {"Quantity": "False-alarm ratio (FAR)", "Value": far},
        {"Quantity": "Probability of false detection (POFD)", "Value": pofd},
        {"Quantity": "Critical success index (CSI)", "Value": csi},
        {"Quantity": "Hanssen–Kuipers skill score (POD − POFD)",
         "Value": pod - pofd if np.isfinite(pod) and np.isfinite(pofd) else np.nan}])


# =============================================================================
# PART 12.  FIGURES
# -----------------------------------------------------------------------------
# Greyscale-safe, 300 dpi, no chart junk: these have to survive a monochrome
# thesis printer and a projector.
# =============================================================================
# Figures are shown on the landing page inside white plates, so they use the
# page's own palette and a sans rather than the matplotlib default serif.
# Helvetica Neue is chosen over the closer-looking Avenir Next for a dull
# reason: this machine registers Avenir Next as a single face at weight 700, so
# every label rendered bold and emphasis became impossible. Helvetica Neue
# registers a true 400. Emphasis in these figures is therefore carried by
# colour rather than weight, which is the more durable choice anyway.
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "DejaVu Sans"],
    "font.size": 9.5,
    "font.weight": "normal",
    "axes.labelweight": "normal",
    "axes.linewidth": 0.7,
    "axes.edgecolor": "#cfd5cb",
    "axes.labelcolor": "#454c46",
    "axes.labelpad": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": "#636c65", "ytick.color": "#636c65",
    "xtick.labelsize": 8.8, "ytick.labelsize": 8.8,
    "xtick.major.size": 3, "ytick.major.size": 3,
    "xtick.major.width": 0.7, "ytick.major.width": 0.7,
    "legend.frameon": False, "legend.fontsize": 8.2,
    "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
    "savefig.facecolor": "white", "figure.facecolor": "white",
})
INK = "#121612"        # body ink, matching the page
ACCENT = "#b0392a"     # the single accent, reserved for what matters
MUTED = "#636c65"      # secondary labels
LINE = "#e3e7e0"       # hairlines
FILL = "#c9cfc8"       # neutral bar body
FILL_SOFT = "#d5dad2"  # bars that fail their benchmark, still legible


def _save(fig, name):
    path = CFG.FIGURE_DIR / name
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_distributions(df):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9))
    axes[0].hist(df["Magnitude"].dropna(), bins=40, color=FILL, edgecolor=INK, linewidth=0.5)
    axes[0].set_xlabel("Magnitude (working scale)")
    axes[0].set_ylabel("Frequency")
    axes[0].set_title("(a) Magnitude", loc="left", fontsize=9)
    axes[1].hist(df["Depth"].dropna(), bins=40, color=FILL, edgecolor=INK, linewidth=0.5)
    axes[1].set_xlabel("Focal depth (km)")
    axes[1].set_ylabel("Frequency")
    axes[1].set_yscale("log")
    axes[1].set_title("(b) Focal depth (log scale)", loc="left", fontsize=9)
    fig.tight_layout()
    return _save(fig, "fig_distributions.png")


def fig_epicentres(df):
    fig, ax = plt.subplots(figsize=(4.4, 5.2))
    big = df[df["Magnitude"] >= 6.0]
    ax.scatter(df["Longitude"], df["Latitude"], s=1.5, c="#b8b8b8", linewidths=0,
               alpha=0.5, label="All events")
    ax.scatter(big["Longitude"], big["Latitude"], s=14, facecolors="none",
               edgecolors=INK, linewidths=0.6, label="M ≥ 6.0")
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ax.set_aspect("equal", adjustable="box")
    ax.legend(frameon=False, fontsize=7.5, loc="upper right")
    fig.tight_layout()
    return _save(fig, "fig_epicentres.png")


def fig_gutenberg_richter(df):
    m = df["Magnitude"].dropna().to_numpy()
    bins, inc, cum = fmd(m)
    # Use the same Mc the summary table headlines, so figure and table agree.
    mc_gft, _ = mc_goodness_of_fit(m)
    mc = mc_gft if np.isfinite(mc_gft) else mc_maxc(m)
    est = b_value_mle(m, mc)

    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    ax.semilogy(bins, cum, "o", ms=3, mfc="none", color=INK, label="Cumulative N(≥M)")
    ax.semilogy(bins, np.where(inc > 0, inc, np.nan), "s", ms=2.5, color=ACCENT,
                alpha=0.6, label="Incremental N(M)")
    line = bins[bins >= mc]
    ax.semilogy(line, 10 ** (est["a"] - est["b"] * line), "-", color=INK, lw=1.2,
                label=f"GR fit: b = {est['b']:.3f} ± {est['b_se']:.3f}")
    ax.axvline(mc, ls="--", lw=0.8, color=ACCENT)
    ax.annotate(f"$M_c$ = {mc:.1f}", xy=(mc, cum.min()), xytext=(5, 14),
                textcoords="offset points", fontsize=8, color=ACCENT)
    ax.set_xlabel("Magnitude")
    ax.set_ylabel("Number of earthquakes")
    ax.legend(frameon=False, fontsize=7.5)
    fig.tight_layout()
    return _save(fig, "fig_gutenberg_richter.png")


def fig_temporal(annual):
    fig, ax = plt.subplots(figsize=(7.0, 2.9))
    ax.bar(annual["Year"], annual["Count"], color=FILL, edgecolor="none", width=0.85)
    ax.set_xlabel("Year")
    ax.set_ylabel("Recorded events")
    ax2 = ax.twinx()
    ax2.plot(annual["Year"], annual["MaxMag"], "-", color=INK, lw=1.0)
    ax2.set_ylabel("Annual maximum magnitude")
    ax2.spines["top"].set_visible(False)
    fig.tight_layout()
    return _save(fig, "fig_temporal.png")


def fig_importance(importance, top=15):
    data = importance.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(5.0, 3.8))
    ax.barh(data["Feature"], data["Permutation importance"],
            xerr=data["SD (permutation)"], color=FILL, edgecolor=INK, linewidth=0.5,
            error_kw={"lw": 0.6, "ecolor": ACCENT})
    ax.set_xlabel("Permutation importance (increase in test MSE)")
    fig.tight_layout()
    return _save(fig, "fig_importance.png")


def fig_leaderboard(board):
    """Test error for every model, ranked, with the baseline as the dividing line.

    The chart has one job: show which models are worth anything. So the winner
    is the only thing in the accent colour, the two naive baselines are drawn
    hollow because they are references rather than results, and everything that
    fails to beat climatology sits in the shaded region to the right of the
    line. Values are printed at the bar ends, which removes the need to track
    back to an axis and lets the axis itself recede.
    """
    data = board.iloc[::-1].reset_index(drop=True)       # best at the top
    ref = float(board.loc[board["Model"].str.startswith("Climatology"), "RMSE"].iloc[0])
    is_base = data["Model"].str.contains("Climatology|Persistence")
    best = data["RMSE"].idxmin()

    height = 0.30 * len(data) + 1.5
    fig, ax = plt.subplots(figsize=(7.2, height))

    # Everything slower than the baseline sits in a faintly shaded band.
    ax.axvspan(ref, data["RMSE"].max() * 1.13, color="#f3e9e6", zorder=0)

    colours, edges = [], []
    for i, row in data.iterrows():
        if is_base[i]:
            colours.append("white"); edges.append("#b6bdb7")
        elif i == best:
            colours.append(ACCENT); edges.append(ACCENT)
        elif row["RMSE"] < ref:
            colours.append(FILL); edges.append(FILL)
        else:
            colours.append(FILL_SOFT); edges.append(FILL_SOFT)

    bars = ax.barh(data["Model"], data["RMSE"], height=0.68,
                   color=colours, edgecolor=edges, linewidth=0.9, zorder=3)

    # Value at the end of every bar, in the bar's own visual weight.
    span = data["RMSE"].max()
    for i, (bar, value) in enumerate(zip(bars, data["RMSE"])):
        ax.text(value + span * 0.012, bar.get_y() + bar.get_height() / 2,
                f"{value:.3f}", va="center", ha="left", fontsize=8.4,
                color=ACCENT if i == best else (MUTED if is_base[i] else INK),
                zorder=4)

    ax.axvline(ref, ls=(0, (4, 3)), lw=1.1, color="#9aa39c", zorder=2)
    ax.annotate("climatology baseline", xy=(ref, len(data) - 0.28),
                xytext=(7, 0), textcoords="offset points",
                fontsize=8.4, color=MUTED, va="center")
    ax.annotate("anything past this line adds nothing", xy=(ref, len(data) - 0.92),
                xytext=(7, 0), textcoords="offset points",
                fontsize=7.6, color="#a8766c", va="center")

    ax.set_xlim(0, span * 1.13)
    ax.set_xlabel("Test RMSE in magnitude units, lower is better")
    ax.set_ylabel("")
    ax.tick_params(axis="y", length=0, pad=6)
    ax.tick_params(axis="x", pad=4)
    for i, label in enumerate(ax.get_yticklabels()):
        label.set_color(ACCENT if i == best else (MUTED if is_base[i] else INK))

    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.xaxis.grid(True, color=LINE, lw=0.6, zorder=1)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return _save(fig, "fig_leaderboard.png")


def fig_cv_distribution(cv, order):
    """Per-fold RMSE spread: a single test number hides how unstable a model is."""
    data = [cv.loc[cv["Model"] == m, "RMSE"].to_numpy() for m in order]
    fig, ax = plt.subplots(figsize=(6.2, 0.26 * len(order) + 1.2))
    bp = ax.boxplot(data[::-1], vert=False, widths=0.6, patch_artist=True,
                    medianprops={"color": INK, "lw": 1.2},
                    flierprops={"marker": "o", "ms": 3, "mfc": "none",
                                "mec": ACCENT, "lw": 0.5})
    for patch in bp["boxes"]:
        patch.set(facecolor=FILL, edgecolor=INK, linewidth=0.6)
    ax.set_yticklabels(order[::-1], fontsize=8)
    ax.set_xlabel("RMSE across rolling-origin validation folds")
    fig.tight_layout()
    return _save(fig, "fig_cv_distribution.png")


def fig_predictions(results):
    fig, axes = plt.subplots(1, len(results), figsize=(3.2 * len(results), 3.3),
                             squeeze=False)
    for ax, (label, payload) in zip(axes[0], results.items()):
        y, p = np.asarray(payload["y_true"]), np.asarray(payload["y_pred"])
        ax.scatter(y, p, s=12, facecolors="none", edgecolors=INK, linewidths=0.6)
        lim = [min(y.min(), p.min()) - 0.1, max(y.max(), p.max()) + 0.1]
        ax.plot(lim, lim, "--", color=ACCENT, lw=0.8)
        ax.set_xlim(lim)
        ax.set_ylim(lim)
        ax.set_xlabel("Observed mainshock magnitude")
        ax.set_ylabel("Forecast magnitude")
        ax.set_title(label, loc="left", fontsize=9)
        ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    return _save(fig, "fig_predictions.png")


def fig_residuals(results):
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    for (label, payload), marker in zip(results.items(), ["o", "s", "^", "D"]):
        y, p = np.asarray(payload["y_true"]), np.asarray(payload["y_pred"])
        ax.scatter(p, p - y, s=12, facecolors="none", edgecolors=INK, linewidths=0.6,
                   marker=marker, label=label)
    ax.axhline(0, ls="--", lw=0.8, color=ACCENT)
    ax.set_xlabel("Forecast magnitude")
    ax.set_ylabel("Residual (forecast − observed)")
    ax.legend(frameon=False, fontsize=7.5)
    fig.tight_layout()
    return _save(fig, "fig_residuals.png")


def fig_confusion(matrix, labels):
    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    ax.imshow(matrix, cmap="Greys", aspect="auto")
    short = [l.split(" (")[0] for l in labels]
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(short, rotation=30, ha="right")
    ax.set_yticklabels(short)
    peak = matrix.max() if matrix.size else 1
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, f"{matrix[i, j]}", ha="center", va="center", fontsize=9,
                    color="white" if matrix[i, j] > peak * 0.6 else INK)
    ax.set_xlabel("Forecast class")
    ax.set_ylabel("Observed class")
    for spine in ax.spines.values():
        spine.set_visible(True)
    fig.tight_layout()
    return _save(fig, "fig_confusion.png")


def fig_learning_curves(histories):
    """Validation MSE per epoch for the three sequence networks."""
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    for (name, history), style in zip(histories.items(), ["-", "--", ":"]):
        if not history:
            continue
        frame = pd.DataFrame(history)
        ax.semilogy(frame["epoch"], frame["val_mse"], style, color=INK, lw=1.1,
                    label=name)
    ax.set_xlabel("Training epoch")
    ax.set_ylabel("Validation MSE (log scale)")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    return _save(fig, "fig_learning_curves.png")


# =============================================================================
# PART 13.  APA 7 WORD EXPORT
# -----------------------------------------------------------------------------
# python-docx has no concept of an APA table, so the borders are written
# directly into the table's XML: a rule above the header, a rule below the
# header, a rule below the final row, and nothing else.  No vertical lines, no
# interior horizontal lines -- that is the whole of the APA border rule, and it
# is the part every hand-built Word table gets wrong.
# =============================================================================
BODY_FONT = "Times New Roman"
BODY_SIZE = Pt(12)
TABLE_SIZE = Pt(10)
LEFT = WD_ALIGN_PARAGRAPH.LEFT
CENTER = WD_ALIGN_PARAGRAPH.CENTER
RIGHT = WD_ALIGN_PARAGRAPH.RIGHT


def _set_cell_border(cell, **kwargs):
    """Apply per-edge borders to one cell. Edges not named are set to 'nil'."""
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right"):
        spec = kwargs.get(edge, {"val": "nil"})
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        for key, value in spec.items():
            element.set(qn(f"w:{key}"), str(value))


def _set_repeat_header(row):
    """Mark a row as a header so Word repeats it when a table breaks a page."""
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    row._tr.get_or_add_trPr().append(header)


def _disable_autofit(table, widths_in):
    """Pin column widths; Word ignores cell widths unless autofit is off."""
    table.autofit = False
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    table._tbl.tblPr.append(layout)
    for row in table.rows:
        for cell, width in zip(row.cells, widths_in):
            cell.width = Inches(width)


def _style_run(run, bold=False, italic=False, size=TABLE_SIZE, font=BODY_FONT):
    run.bold, run.italic = bold, italic
    run.font.size = size
    run.font.name = font
    run.font.color.rgb = RGBColor(0, 0, 0)
    # East-Asian font binding, otherwise Word may substitute in some locales.
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    return run


def _cell_paragraph(cell, text, bold=False, italic=False, align=LEFT, size=TABLE_SIZE):
    cell.text = ""
    para = cell.paragraphs[0]
    para.alignment = align
    pf = para.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(2), Pt(2), 1.0
    _style_run(para.add_run(str(text)), bold=bold, italic=italic, size=size)
    return para


def new_document() -> Document:
    """A blank US Letter document with APA body defaults."""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = BODY_SIZE
    style.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attr, Inches(1))
    return doc


def _orient_section(doc, landscape):
    """Open a new section in the requested orientation and return it."""
    current = doc.sections[-1]
    if (current.page_width > current.page_height) == landscape:
        return current
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    width, height = section.page_width, section.page_height
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = ((max(width, height), min(width, height))
                                               if landscape
                                               else (min(width, height), max(width, height)))
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attr, Inches(1))
    return section


def ensure_portrait(doc):
    """Return to portrait before content that was laid out for it."""
    _orient_section(doc, False)


def add_heading(doc, text, level=1):
    """APA headings: Level 1 centred bold, Level 2 flush-left bold."""
    para = doc.add_paragraph()
    para.alignment = CENTER if level == 1 else LEFT
    para.paragraph_format.space_before = Pt(18 if level == 1 else 12)
    para.paragraph_format.space_after = Pt(6)
    _style_run(para.add_run(text), bold=True, italic=(level >= 3), size=BODY_SIZE)


def add_paragraph(doc, text, italic=False, size=BODY_SIZE):
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(6)
    para.paragraph_format.line_spacing = 1.5
    _style_run(para.add_run(text), italic=italic, size=size)


def _numeric_columns(df) -> set:
    """Columns whose cells read as numbers, so they should be right-aligned."""
    pattern = re.compile(r"^[−\-–]?[\d,]*\.?\d+([eE][+\-]?\d+)?%?$|^[<>]\s?\.?\d")
    numeric = set()
    for col in df.columns:
        values = [str(v).strip() for v in df[col] if str(v).strip() not in ("—", "")]
        if values and sum(bool(pattern.match(v)) for v in values) / len(values) >= 0.7:
            numeric.add(col)
    return numeric


def _auto_widths(df, usable_in) -> list:
    """Width proportional to the longest cell, with a floor and a ceiling."""
    widths = [min(max(max([len(str(col))] + [len(str(v)) for v in df[col]]), 6), 46)
              for col in df.columns]
    scaled = [usable_in * w / sum(widths) for w in widths]
    floor = [max(w, 0.45) for w in scaled]
    return [w * usable_in / sum(floor) for w in floor]


def add_apa_table(doc, df, number, title, note=None, align=None, col_widths=None,
                  landscape=False, font_size=TABLE_SIZE, page_break_before=True):
    """Write `df` (already string-valued) as an APA 7 table."""
    before = len(doc.sections)
    section = _orient_section(doc, landscape)
    usable = (section.page_width - section.left_margin - section.right_margin) / 914400
    # A new section already starts its own page; a page break on top of it would
    # leave a blank page between the two.
    if page_break_before and doc.paragraphs and len(doc.sections) == before:
        doc.add_page_break()

    label = doc.add_paragraph()
    label.paragraph_format.space_after = Pt(0)
    _style_run(label.add_run(f"Table {number}"), bold=True, size=BODY_SIZE)
    heading = doc.add_paragraph()
    heading.paragraph_format.space_after = Pt(8)
    _style_run(heading.add_run(title), italic=True, size=BODY_SIZE)

    body = df.astype(object).where(pd.notna(df), "—")
    n_rows, n_cols = body.shape
    table = doc.add_table(rows=n_rows + 1, cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    if col_widths is None:
        col_widths = _auto_widths(body, usable)
    _disable_autofit(table, col_widths)

    align = align or {}
    numericish = _numeric_columns(body)

    head = table.rows[0]
    _set_repeat_header(head)
    for j, name in enumerate(body.columns):
        _cell_paragraph(head.cells[j], name, align=align.get(name, CENTER), size=font_size)
        _set_cell_border(head.cells[j], top={"val": "single", "sz": 8, "color": "000000"},
                         bottom={"val": "single", "sz": 4, "color": "000000"})

    for i, (_, record) in enumerate(body.iterrows()):
        row = table.rows[1 + i]
        last = i == n_rows - 1
        for j, name in enumerate(body.columns):
            default = RIGHT if name in numericish else LEFT
            _cell_paragraph(row.cells[j], record[name], align=align.get(name, default),
                            size=font_size)
            _set_cell_border(row.cells[j],
                             bottom=({"val": "single", "sz": 8, "color": "000000"}
                                     if last else {"val": "nil"}))

    if note:
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(6)
        para.paragraph_format.line_spacing = 1.0
        _style_run(para.add_run("Note. "), italic=True, size=Pt(10))
        _style_run(para.add_run(note), size=Pt(10))


def add_figure(doc, image_path, number, title, note=None, width_in=6.0):
    """Figure in APA order: label, italic title, image, then the note."""
    doc.add_page_break()
    label = doc.add_paragraph()
    label.paragraph_format.space_after = Pt(0)
    _style_run(label.add_run(f"Figure {number}"), bold=True, size=BODY_SIZE)
    heading = doc.add_paragraph()
    heading.paragraph_format.space_after = Pt(8)
    _style_run(heading.add_run(title), italic=True, size=BODY_SIZE)
    para = doc.add_paragraph()
    para.alignment = CENTER
    para.add_run().add_picture(str(image_path), width=Inches(width_in))
    if note:
        n = doc.add_paragraph()
        n.paragraph_format.line_spacing = 1.0
        _style_run(n.add_run("Note. "), italic=True, size=Pt(10))
        _style_run(n.add_run(note), size=Pt(10))


class Report:
    """Collects tables into the Word document, the CSV folder, and the log."""

    def __init__(self, doc):
        self.doc = doc
        self.n = 0
        self.figure_n = 0
        self.index = []

    def table(self, df, title, note=None, *, slug, decimals=2, p_columns=(),
              strip_zero_columns=(), int_columns=(), landscape=False, align=None,
              font_size=TABLE_SIZE):
        df.to_csv(CFG.TABLE_DIR / f"{slug}.csv", index=False)
        formatted = format_frame(df, decimals=decimals, p_columns=p_columns,
                                 strip_zero_columns=strip_zero_columns,
                                 int_columns=int_columns)
        self.n += 1
        self.index.append((self.n, title))
        add_apa_table(self.doc, formatted, self.n, title, note, align=align,
                      landscape=landscape, font_size=font_size)
        print(f"  Table {self.n:>2}  {title}")

    def raw_table(self, df, title, note=None, *, slug, landscape=False, align=None,
                  font_size=TABLE_SIZE):
        """For frames already string-valued (cross-tabs, confusion matrices)."""
        df.to_csv(CFG.TABLE_DIR / f"{slug}.csv", index=False)
        self.n += 1
        self.index.append((self.n, title))
        add_apa_table(self.doc, df.astype(str), self.n, title, note, align=align,
                      landscape=landscape, font_size=font_size)
        print(f"  Table {self.n:>2}  {title}")

    def figure(self, path, title, note=None, width_in=6.0):
        self.figure_n += 1
        add_figure(self.doc, path, self.figure_n, title, note, width_in)
        print(f"  Figure {self.figure_n}  {title}")


# =============================================================================
# PART 14.  MAIN PIPELINE
# =============================================================================
def _sequence_profile(sequences, skipped) -> pd.DataFrame:
    rows = [
        (f"Candidate mainshocks (independent, M ≥ {CFG.MAINSHOCK_MIN_MAG:.1f})",
         f"{sequences.attrs.get('n_mainshocks', 0):,}"),
        ("Rejected: window opens before the catalogue starts",
         f"{skipped.get('outside catalogue start', 0):,}"),
        (f"Rejected: fewer than {CFG.MIN_FORESHOCKS} events in the observation window",
         f"{skipped.get('too few foreshocks', 0):,}"),
        ("Forecast sequences retained", f"{len(sequences):,}"),
        ("Observation window",
         f"{CFG.T_OBS_DAYS:.0f} days, {CFG.RADIUS_KM:.0f} km radius"),
        ("Period covered",
         f"{sequences['MainshockTime'].min():%b %Y} – "
         f"{sequences['MainshockTime'].max():%b %Y}"),
        ("Target magnitude, M (SD)",
         f"{sequences['Target'].mean():.3f} ({sequences['Target'].std(ddof=1):.3f})"),
        ("Target magnitude range",
         f"{sequences['Target'].min():.1f} – {sequences['Target'].max():.1f}"),
        ("Median foreshocks per window", f"{sequences['NO'].median():.0f}"),
        ("Sequences with an M ≥ 6.0 target",
         f"{int((sequences['Target'] >= 6.0).sum()):,}"),
        ("Sequences with an M ≥ 7.0 target",
         f"{int((sequences['Target'] >= 7.0).sum()):,}")]
    return pd.DataFrame(rows, columns=["Quantity", "Value"])


def _network_training_table(nets, backend) -> pd.DataFrame:
    """What each sequence network actually did during training."""
    rows = [{"Setting": "Deep-learning backend in use", "LSTM": backend,
             "GRU": backend, "1D-CNN": backend}]
    fields = [("Architecture",
               lambda n: (f"{CFG.NN_UNITS} units" if n.name != "1D-CNN"
                          else f"{CFG.CNN_FILTERS} filters, kernel {CFG.CNN_KERNEL}")),
              ("Trainable parameters", lambda n: f"{n.n_parameters_:,}"),
              ("Epochs run (of %d max)" % CFG.NN_EPOCHS, lambda n: f"{n.epochs_run_}"),
              ("Best validation MSE", lambda n: f"{n.best_val_mse_:.4f}")]
    for label, fn in fields:
        row = {"Setting": label}
        for name, net in nets.items():
            row[name] = fn(net) if net is not None else "—"
        rows.append(row)
    rows += [
        {"Setting": "Optimiser", "LSTM": f"Adam (lr = {CFG.NN_LR})",
         "GRU": f"Adam (lr = {CFG.NN_LR})", "1D-CNN": f"Adam (lr = {CFG.NN_LR})"},
        {"Setting": "Early stopping", "LSTM": f"patience {CFG.NN_PATIENCE}",
         "GRU": f"patience {CFG.NN_PATIENCE}", "1D-CNN": f"patience {CFG.NN_PATIENCE}"},
        {"Setting": "Input", "LSTM": f"{CFG.SEQ_LEN} × 5 event stream",
         "GRU": f"{CFG.SEQ_LEN} × 5 event stream",
         "1D-CNN": f"{CFG.SEQ_LEN} × 5 event stream"}]
    return pd.DataFrame(rows)


def _title_page(doc):
    add_heading(doc, "Statistical Analysis Tables", 1)
    add_paragraph(doc, "A Machine Learning Model for Forecasting Mainshock Magnitudes "
                       "Using PHIVOLCS Foreshock Data", italic=True)
    add_paragraph(doc, "All tables follow APA 7th-edition format: a bold table number, "
                       "an italic title in title case, horizontal rules only, and a note "
                       "beneath the table where interpretation is needed. Every table in "
                       "this document was generated directly from the source catalogue by "
                       "the accompanying Python script; no value was entered by hand.")
    add_paragraph(doc, f"Source data: {CFG.DATA_XLSX.name}. Analysis seed: {CFG.SEED}. "
                       f"Significance level: α = {CFG.ALPHA}.")


def _finish(doc, report, started):
    ensure_portrait(doc)
    add_heading(doc, "List of Tables", 1)
    for number, title in report.index:
        add_paragraph(doc, f"Table {number}. {title}", size=Pt(11))
    doc.save(CFG.DOCX_PATH)
    print(f"\nWrote {report.n} tables and {report.figure_n} figures")
    print(f"  Word document : {CFG.DOCX_PATH}")
    print(f"  CSV tables    : {CFG.TABLE_DIR}")
    print(f"  Figures       : {CFG.FIGURE_DIR}")
    print(f"  Elapsed       : {time.time() - started:.1f}s")


def main(run_models=True, run_figures=True, quick=False, excel=None):
    started = time.time()
    doc = new_document()
    report = Report(doc)
    _title_page(doc)

    # ------------------------------------------------------------- Stage 1 --
    print("\n[1/7] Loading and cleaning the catalogue")
    raw = read_raw(excel)
    catalogue, audit, relations = load_catalogue(excel)
    print(f"      {len(raw):,} raw records → {len(catalogue):,} clean events")

    add_heading(doc, "Section A. Data Preparation and Catalogue Description", 1)
    report.table(catalogue_overview(catalogue, len(raw)),
                 "Profile of the PHIVOLCS Earthquake Catalogue After Cleaning",
                 "Working magnitude is the first available scale in the order "
                 f"{' > '.join(CFG.MAGNITUDE_PREFERENCE)}. The catalogue is an event "
                 "list, not a uniformly complete record; detection capability improves "
                 "markedly after the 1970s (see Table 8).",
                 slug="t01_catalogue_overview", align={"Value": LEFT})
    report.table(audit, "Data-Cleaning Audit Trail",
                 "Rules were applied in the order shown. A record removed by an earlier "
                 "rule is not re-tested by a later one, so the counts sum to the retained "
                 "total.",
                 slug="t02_cleaning_audit",
                 int_columns=("Records before", "Removed", "Records retained"),
                 align={"Step": LEFT, "Note": LEFT})
    report.table(magnitude_scale_profile(catalogue),
                 "Availability and Distribution of the Four Reported Magnitude Scales",
                 "n reported counts events for which the scale is populated; n adopted "
                 "counts events for which it became the working magnitude. Ml saturates "
                 "near M 6.5 and mb near M 6.0, which is why Mw and Ms take precedence.",
                 slug="t03_magnitude_scales", decimals={"% of catalogue": 1},
                 int_columns=("n reported", "n adopted as working scale"))
    report.table(scale_coverage(catalogue),
                 "Co-Reporting of Magnitude Scales Within the Catalogue",
                 "Mw is co-reported with another scale for very few events, which is the "
                 "reason no catalogue-wide conversion to Mw was attempted (see Table 5).",
                 slug="t04_scale_coverage", decimals={"% of catalogue": 1},
                 int_columns=("n events",), align={"Scales reported together": LEFT})
    report.table(relations, "Orthogonal Regression Relations Between Magnitude Scales",
                 "Major-axis (orthogonal) regression of the response on the predictor, "
                 "fitted on events reporting both scales. SEE = standard error of the "
                 "estimate. Relations involving Mw rest on too few co-reported events to "
                 "support catalogue-wide homogenisation, and were not applied.",
                 slug="t05_scale_conversions", decimals=3, int_columns=("n",),
                 align={"Usable": LEFT})
    if "SrcDistKm" in catalogue.columns:
        report.raw_table(source_distance_check(catalogue).astype(str),
                         "Distance to the Nearest Active Fault, and Its Verification",
                         "Fault lines were mapped in QGIS and the distance measured with the "
                         "Haversine formula on a sphere of radius 6,371 km, as the methodology "
                         "specifies. The supplied value is used as given. It is recomputed here "
                         "from the two coordinate pairs beside it purely as a transcription "
                         "check; the residual differences are a rounding effect that grows with "
                         "distance and is immaterial inside the 100 km observation radius.",
                         slug="t07_fault_distance",
                         align={"Quantity": LEFT, "Value": LEFT})

    report.table(parameter_descriptives(catalogue),
                 "Descriptive Statistics for the Principal Seismic Parameters",
                 "CI = confidence interval for the mean. Skewness and kurtosis are "
                 "bias-corrected; for a normal distribution both approach zero.",
                 slug="t06_parameter_descriptives", decimals=3, int_columns=("n",),
                 align={"Variable": LEFT}, font_size=Pt(9))

    # ------------------------------------------------------------- Stage 2 --
    print("\n[2/7] Frequency distributions")
    add_heading(doc, "Section B. Frequency Distributions", 1)
    report.table(frequency_by_magnitude_class(catalogue),
                 "Frequency Distribution of Events by Magnitude Class",
                 "Class boundaries begin at the catalogue's own reporting threshold. No "
                 "event in the workbook carries a working magnitude below M 4.0, so the "
                 "conventional micro and minor classes are empty by construction.",
                 slug="t07_freq_magnitude",
                 decimals={"%": 1, "Cumulative %": 1, "Mdn depth (km)": 1},
                 int_columns=("f",), align={"Magnitude class": LEFT})
    report.table(frequency_by_decade(catalogue), "Recorded Seismicity by Decade",
                 "The rise in recorded events tracks the expansion of the PHIVOLCS "
                 "seismic network. Decadal counts are therefore a measure of observation, "
                 "and any temporal trend must be read with that in mind.",
                 slug="t08_freq_decade",
                 decimals={"%": 1, "M (magnitude)": 2, "SD": 2, "Max": 1,
                           "Mdn depth (km)": 1},
                 int_columns=("f", "f (M ≥ 6.0)"), align={"Decade": LEFT})
    report.table(frequency_by_depth_class(catalogue),
                 "Frequency Distribution of Events by Hypocentral Depth Class",
                 "Depth classes follow the USGS convention. Shallow events dominate and "
                 "carry the greatest surface hazard for a given magnitude.",
                 slug="t09_freq_depth", decimals={"%": 1, "Cumulative %": 1},
                 int_columns=("f",), align={"Depth class": LEFT})
    observed, crosstab_display = crosstab_magnitude_depth(catalogue)
    report.raw_table(crosstab_display,
                     "Cross-Tabulation of Magnitude Class by Hypocentral Depth Class",
                     "Cell entries are counts with row percentages in parentheses.",
                     slug="t10_crosstab", align={"Magnitude class": LEFT})

    # ------------------------------------------------------------- Stage 3 --
    print("\n[3/7] Inferential tests")
    add_heading(doc, "Section C. Inferential Statistics", 1)
    numeric_vars = ["Magnitude", "Depth", "Latitude", "Longitude"]
    report.table(normality_tests(catalogue, numeric_vars),
                 "Tests of Normality for the Seismic Parameters",
                 "Shapiro–Wilk is computed on a random subsample of 5,000 events, the "
                 "largest n for which the statistic is defined. All four variables depart "
                 "from normality, which is why rank-based tests are reported alongside "
                 "parametric ones throughout.",
                 slug="t11_normality", decimals=3,
                 p_columns=("p (S–W)", "p (K²)", "p (K–S)"), int_columns=("n",),
                 align={"Variable": LEFT, "Decision at α = .05": LEFT}, font_size=Pt(9))
    report.raw_table(correlation_matrix(catalogue, numeric_vars),
                     "Pearson Correlation Matrix for the Seismic Parameters",
                     f"N = {len(catalogue.dropna(subset=numeric_vars)):,}. "
                     "* p < .05. ** p < .01. *** p < .001. Leading zeros are omitted.",
                     slug="t12_correlation_matrix", align={"Variable": LEFT})
    report.table(correlation_detail(catalogue, numeric_vars),
                 "Pairwise Associations Among the Seismic Parameters",
                 "With N in the tens of thousands nearly every association is "
                 "statistically significant; r² and the strength label, not p, carry the "
                 "practical meaning.",
                 slug="t13_correlation_detail", decimals=3, p_columns=("p (r)", "p (ρ)"),
                 int_columns=("n",),
                 strip_zero_columns=("Pearson r", "Spearman ρ", "r²"),
                 align={"Variable pair": LEFT, "Strength (Cohen)": LEFT})

    desc_depth, tests_depth = group_comparison(catalogue, "Magnitude", "DepthClass")
    report.table(desc_depth, "Magnitude by Depth Class: Group Descriptive Statistics",
                 None, slug="t14_depth_groups", decimals=3, int_columns=("n",),
                 align={"Group": LEFT})
    report.table(tests_depth,
                 "Omnibus Tests of Magnitude Differences Across Depth Classes",
                 "Levene's test rejects homogeneity of variance, so Welch's ANOVA and the "
                 "Kruskal–Wallis test are the defensible omnibus results; the classical F "
                 "is reported only for comparison.",
                 slug="t15_depth_omnibus", decimals=3, p_columns=("p",),
                 align={"Test": LEFT, "df": LEFT, "Effect size index": LEFT,
                        "Interpretation": LEFT})
    report.table(dunn_posthoc(catalogue, "Magnitude", "DepthClass"),
                 "Dunn's Post Hoc Comparisons of Magnitude Across Depth Classes",
                 "p values are Bonferroni-adjusted for the number of pairwise "
                 "comparisons. Cliff's δ is a non-parametric effect size bounded by ±1.",
                 slug="t16_depth_posthoc", decimals=3,
                 p_columns=("p", "p (Bonferroni)"), strip_zero_columns=("Cliff's δ",),
                 align={"Comparison": LEFT, "Decision": LEFT})

    chi_result, chi_resid = chi_square_independence(observed)
    report.table(chi_result,
                 "Chi-Square Test of Independence: Magnitude Class by Depth Class",
                 "Cramér's V is benchmarked against the degrees of freedom of the table.",
                 slug="t17_chisquare", decimals=3, p_columns=("p",),
                 int_columns=("df", "N"),
                 align={"Test": LEFT, "Effect size": LEFT, "Decision at α = .05": LEFT})
    report.raw_table(chi_resid.astype(str),
                     "Standardised Residuals for the Magnitude-by-Depth Cross-Tabulation",
                     "Residuals beyond ±1.96 mark cells contributing significantly to the "
                     "chi-square statistic at α = .05.",
                     slug="t18_chisq_residuals", align={"Magnitude class": LEFT})

    annual = annual_series(catalogue)
    annual.to_csv(CFG.TABLE_DIR / "annual_series.csv", index=False)
    report.table(trend_table(annual),
                 "Mann–Kendall Trend Tests on the Annual Seismicity Series",
                 "Sen's slope is the Theil–Sen median slope per year. A trend in recorded "
                 "counts confounds real seismicity with network growth; the magnitude "
                 "series is the less confounded of the four.",
                 slug="t19_trend", decimals=3, p_columns=("p",),
                 int_columns=("n (years)", "Mann–Kendall S"),
                 strip_zero_columns=("Kendall's τ",),
                 align={"Series": LEFT, "Trend": LEFT})
    report.raw_table(era_comparison(catalogue).astype(str),
                     "Comparison of Recorded Magnitudes Before and After 1980",
                     "1980 approximates the modernisation of the national seismic "
                     "network. A difference here is at least as likely to reflect "
                     "improved detection of small events as a change in seismicity.",
                     slug="t20_era_comparison", align={"Statistic": LEFT, "Value": LEFT})

    # ------------------------------------------------------------- Stage 4 --
    print("\n[4/7] Gutenberg–Richter analysis")
    add_heading(doc, "Section D. Frequency–Magnitude Distribution", 1)
    report.table(gr_summary(catalogue),
                 "Completeness Magnitude and Gutenberg–Richter Parameters for the Full "
                 "Catalogue",
                 "Mc (MAXC) is the maximum-curvature estimate with the conventional +0.2 "
                 "correction; Mc (GFT) is the 90% goodness-of-fit estimate of Wiemer and "
                 "Wyss (2000). b (MLE) is the Aki–Utsu estimator with the Shi and Bolt "
                 "(1982) standard error. A b-value near 1.0 is typical of subduction "
                 "seismicity.",
                 slug="t21_gr_full", decimals=3, int_columns=("N events", "N ≥ Mc"),
                 align={"Subset": LEFT}, font_size=Pt(9))
    report.table(gr_summary(catalogue[catalogue["Year"] >= 1980], "Decade"),
                 "Gutenberg–Richter Parameters by Decade, 1980 to Present",
                 "Restricted to 1980 onward, where the catalogue is dense enough for "
                 "stable per-decade estimates. Drift in Mc across decades is a "
                 "completeness effect; drift in b is the physically interesting quantity.",
                 slug="t22_gr_decade", decimals=3, int_columns=("N events", "N ≥ Mc"),
                 align={"Subset": LEFT}, landscape=True, font_size=Pt(9))
    report.table(gr_summary(catalogue, "DepthClass"),
                 "Gutenberg–Richter Parameters by Hypocentral Depth Class",
                 "Differences in b between depth regimes are interpreted as differences "
                 "in the stress state of the seismogenic volume.",
                 slug="t23_gr_depth", decimals=3, int_columns=("N events", "N ≥ Mc"),
                 align={"Subset": LEFT}, landscape=True, font_size=Pt(9))

    # ------------------------------------------------------------- Stage 5 --
    print("\n[5/7] Maeda declustering and feature construction")
    add_heading(doc, "Section E. Declustering and Feature Engineering", 1)
    flagged, decluster_summary = decluster(catalogue)
    independent = flagged[~flagged["IsDependent"]].reset_index(drop=True)
    print(f"      {len(independent):,} independent events retained "
          f"({int(flagged['IsDependent'].sum()):,} dependent events removed)")

    report.table(maeda_window_reference(),
                 "Space–Time Windows Implied by Maeda's Method",
                 "Windows follow Equations 1 and 2 of Hirose et al. (2021). An event "
                 "inside the window of an earlier event and at least 1.0 magnitude unit "
                 "smaller (Equation 3) is classified as dependent.",
                 slug="t24_maeda_windows", decimals=2,
                 align={"Precursor magnitude (Mpre)": LEFT})
    report.table(decluster_summary, "Outcome of Maeda's Declustering Procedure",
                 "Percentages are of the events entering the procedure.",
                 slug="t25_decluster_summary", decimals={"% of input": 1},
                 int_columns=("n",), align={"Declustering stage": LEFT})
    report.table(decluster_effect(catalogue, independent),
                 "Catalogue Descriptive Statistics Before and After Declustering",
                 "Removing dependent events raises the mean magnitude because the removed "
                 "population is, by construction, the small one.",
                 slug="t26_decluster_effect", decimals=3,
                 int_columns=("N", "n (M ≥ 5.0)", "n (M ≥ 6.0)"),
                 align={"Catalogue": LEFT})
    report.table(gr_summary(independent),
                 "Gutenberg–Richter Parameters for the Declustered Catalogue",
                 "Compare with Table 21. Declustering typically lowers b, since clustered "
                 "sequences are magnitude-poor relative to background seismicity.",
                 slug="t27_gr_declustered", decimals=3,
                 int_columns=("N events", "N ≥ Mc"), align={"Subset": LEFT},
                 font_size=Pt(9))
    report.raw_table(feature_dictionary().astype(str),
                     f"The {len(FEATURE_NAMES)} Engineered Seismic Features",
                     f"The first {len(CORE_FEATURE_NAMES)} follow Wang et al. (2023) as "
                     "tabulated in the study methodology. The last "
                     f"{len(FAULT_FEATURE_NAMES)} summarise the distance to the nearest "
                     "active fault, which Data Collection names as a selected parameter but "
                     "which has no row in that table. Every feature is computed from the "
                     f"events inside the observation window: {CFG.T_OBS_DAYS:.0f} days and "
                     f"{CFG.RADIUS_KM:.0f} km preceding the mainshock. The mainshock's own "
                     "distance to a fault is deliberately excluded, being a property of the "
                     "event under forecast.",
                     slug="t28_feature_dictionary",
                     align={"Feature": LEFT, "Category": LEFT, "Description": LEFT},
                     font_size=Pt(9))

    sequences = build_sequences(independent, full=catalogue)
    if sequences.empty:
        raise SystemExit("No mainshock sequences met the observation-window criteria.")
    sequences.to_csv(CFG.TABLE_DIR / "feature_matrix.csv", index=False)
    print(f"      {len(sequences):,} forecast sequences built from "
          f"{sequences.attrs.get('n_mainshocks', 0):,} candidate mainshocks")

    report.table(_sequence_profile(sequences, sequences.attrs.get("skipped", {})),
                 "Construction of the Forecast Sequence Data Set",
                 f"A mainshock qualifies at M ≥ {CFG.MAINSHOCK_MIN_MAG:.1f} and requires "
                 f"at least {CFG.MIN_FORESHOCKS} catalogued events inside its observation "
                 "window. Observation windows are drawn from the full catalogue rather "
                 "than the declustered one, because the small dependent events Maeda's "
                 "method removes are precisely the precursory activity the features are "
                 "meant to measure.",
                 slug="t29_sequence_profile", align={"Quantity": LEFT, "Value": LEFT})
    report.table(feature_descriptives(sequences),
                 f"Descriptive Statistics for the {len(FEATURE_NAMES)} Engineered Features",
                 "Statistics describe the features as computed. Missing values arise "
                 "where a window is too sparse to support a b-value fit; they are "
                 "median-imputed from the training rows of each fold only. Before "
                 "modelling, the energy, occurrence-probability and elapsed-time features "
                 "are log-transformed and every feature is winsorised at the training 1st "
                 "and 99th percentiles — both monotone, so the tree ensembles are "
                 "unaffected and the linear, kernel and neural models are protected from "
                 "the heavy tails these quantities carry by construction.",
                 slug="t30_feature_descriptives", decimals=3,
                 int_columns=("n valid", "n missing"), align={"Feature": LEFT},
                 landscape=True, font_size=Pt(8.5))
    occ_datasets = {r: build_occurrence_dataset(catalogue, independent, r)
                    for r in CFG.OCC_RADII}
    occ_results, occ_fitted = fit_occurrence_models(occ_datasets)
    for r, d in occ_datasets.items():
        d.to_csv(CFG.TABLE_DIR / f"occurrence_anchors_{int(r)}km.csv", index=False)

    report.table(target_feature_correlations(sequences),
                 "Correlations Between Each Engineered Feature and the Mainshock "
                 "Magnitude",
                 "Pearson r and Spearman ρ against the observed mainshock magnitude "
                 "across all sequences. These are univariate associations and do not "
                 "account for the interactions the ensemble models exploit.",
                 slug="t31_feature_target_corr", decimals=3,
                 p_columns=("p (r)", "p (ρ)"),
                 strip_zero_columns=("Pearson r", "Spearman ρ"), int_columns=("n",),
                 align={"Feature": LEFT, "Strength": LEFT})

    # ---- Occurrence forecasting ---------------------------------------- #
    print("\n      occurrence dataset and probability models ...")
    add_heading(doc, "Section F. Probability of Occurrence", 1)
    report.table(occurrence_profile(occ_datasets),
                 "Construction of the Occurrence Data Set",
                 f"Each anchor is a moment and a place with at least {CFG.MIN_FORESHOCKS} "
                 f"catalogued events in the preceding {CFG.T_OBS_DAYS:.0f} days, labelled by "
                 f"whether an independent earthquake of the stated size followed within the "
                 f"next {CFG.HORIZON_DAYS:.0f} days. This is the reverse of the magnitude "
                 "model's window, which looks backward. Anchors within a day and half a radius "
                 "of one already kept are dropped, because a single swarm would otherwise "
                 "contribute dozens of near-identical rows.",
                 slug="t33_occurrence_profile", decimals=1,
                 int_columns=("Anchors", "Thinned out") + tuple(
                     f"n positive (M ≥ {t:g})" for t in CFG.OCC_THRESHOLDS),
                 align={"Period": LEFT}, landscape=True, font_size=Pt(8.5))

    report.table(occ_results,
                 "Does the Model Beat the Historical Rate? Rolling-Origin Scores",
                 "Scored across expanding-window folds rather than one split: with four to "
                 "thirty positives in a test block, a single split returns an AUC anywhere "
                 "between .13 and .80 for the same cell. A cell counts as modelled only if the "
                 "calibrated probability beats quoting the base rate, meaning a positive mean "
                 "Brier skill score and a mean AUC above .55. The historical rate column is a "
                 "real conditional frequency and remains a defensible answer wherever the model "
                 "does not clear that bar.",
                 slug="t34_occurrence_skill", decimals=3,
                 int_columns=("Anchors", "Positives", "Folds scored"),
                 align={"Threshold": LEFT, "Verdict": LEFT}, landscape=True, font_size=Pt(8.5))

    report.table(occurrence_intervals(occ_datasets),
                 f"Probability of Occurrence With {int((1 - CFG.ALPHA) * 100)}% Confidence "
                 "Intervals",
                 "Rate is the observed frequency: of n anchors where a sequence was already "
                 "under way, the proportion followed within "
                 f"{CFG.HORIZON_DAYS:.0f} days by an independent earthquake of that size at "
                 "that distance. The Wilson interval is the standard interval for a "
                 "proportion and is reported because a reader will expect it; Wald's is "
                 "unusable at these rates, returning a negative lower bound. The year-block "
                 "interval resamples whole years instead of individual anchors, dropping the "
                 "independence assumption Wilson requires: these anchors are overlapping "
                 "windows cut from one catalogue and a single productive swarm supplies many "
                 "of them. Where the two disagree, the block interval is the defensible one. "
                 "Margin of error is the half-width of the corresponding interval, in "
                 "percentage points.",
                 slug="t35_occurrence_intervals", decimals=2,
                 int_columns=("n anchors", "n occurred"),
                 align={"Threshold": LEFT, f"Wilson {int((1 - CFG.ALPHA) * 100)}% CI": LEFT,
                        f"Year-block {int((1 - CFG.ALPHA) * 100)}% CI": LEFT},
                 landscape=True, font_size=Pt(8.5))

    if not run_models:
        _finish(doc, report, started)
        return

    # ------------------------------------------------------------- Stage 6 --
    print("\n[6/7] Model construction, validation and comparison")
    add_heading(doc, "Section F. Model Construction and Comparison", 1)

    bundle = DataBundle(sequences, catalogue)
    train, val, test = chronological_split(sequences)
    n_tr, n_va, n_te = len(train), len(val), len(test)
    idx_train = np.arange(n_tr)
    idx_val = np.arange(n_tr, n_tr + n_va)
    idx_trval = np.arange(n_tr + n_va)
    idx_test = np.arange(n_tr + n_va, len(sequences))
    y_test = bundle.y[idx_test]

    report.table(split_summary(train, val, test),
                 "Chronological 60:20:20 Partitioning of the Sequence Data Set",
                 "The split is strictly by time: every validation sequence postdates "
                 "every training sequence, and every test sequence postdates both. A "
                 "random shuffle would let a model learn from the future of its own test "
                 "set.",
                 slug="t32_split", decimals=3,
                 int_columns=("n sequences", "n (M ≥ 6.0)"),
                 align={"Partition": LEFT, "Period covered": LEFT})
    report.table(class_distribution(train, val, test),
                 "Magnitude-Class Distribution Across the Three Partitions",
                 "Major events are rare in every partition. This imbalance is the reason "
                 "Cohen's κ, rather than raw accuracy, is treated as the headline "
                 "agreement statistic.",
                 slug="t33_class_distribution", decimals=1,
                 int_columns=("Training f", "Validation f", "Test f"),
                 align={"Magnitude class": LEFT})

    print("      tuning Random Forest ...")
    Xtr, Xva = bundle.tabular(idx_train, idx_val)
    rf, rf_params, rf_trials = tune_random_forest(
        Xtr, bundle.y[idx_train], Xva, bundle.y[idx_val],
        grid=CFG.RF_GRID_QUICK if quick else CFG.RF_GRID)
    report.table(rf_trials.head(12),
                 "Random Forest Hyperparameter Search (Top 12 Configurations)",
                 "Configurations ranked by root mean squared error on the validation "
                 "partition. Grid search was scored on the held-out development set "
                 "rather than by k-fold cross-validation, which would shuffle the time "
                 "ordering back together.",
                 slug="t34_rf_grid", decimals=4,
                 align={"max_features": LEFT, "max_depth": LEFT})

    report.raw_table(model_registry(rf_params).astype(str),
                     "Inventory of the Forecasting Models Compared",
                     f"{len(ALL_MODELS)} forecasters across four families, all scored on "
                     "the same sequences. The two baselines are included because a "
                     "forecasting model earns its claim only by beating them.",
                     slug="t35_model_registry",
                     align={"Model": LEFT, "Family": LEFT,
                            "Input representation": LEFT, "Key settings": LEFT},
                     landscape=True, font_size=Pt(9))

    print(f"      rolling-origin cross-validation over {len(ALL_MODELS)} models ...")
    cv = rolling_origin_cv(bundle, n_tr + n_va, rf_params=rf_params,
                           nn_epochs=120 if quick else None)
    cv.to_csv(CFG.TABLE_DIR / "cv_raw_folds.csv", index=False)
    summary = cv_summary(cv)

    report.table(summary,
                 "Rolling-Origin Cross-Validation Results Across All Models",
                 "Expanding-window validation over the training and validation "
                 "partitions: each fold trains on everything before its test block and "
                 "forecasts the block that follows. SD across folds is the more honest "
                 "measure of a model's reliability than any single split, and Mean rank "
                 "is what the Friedman test in Table 37 operates on.",
                 slug="t36_cv_summary", decimals=3, int_columns=("Folds",),
                 align={"Model": LEFT}, font_size=Pt(9))

    friedman, nemenyi = friedman_nemenyi(cv)
    report.raw_table(friedman.astype(str),
                     "Friedman Test for Differences Among the Models",
                     "The Friedman test is the standard rank-based omnibus comparison of "
                     "several models across several data splits (Demšar, 2006). The "
                     "Nemenyi critical difference is the gap in mean rank two models must "
                     "show before they can be called distinguishable.",
                     slug="t37_friedman", align={"Quantity": LEFT, "Value": LEFT})
    report.table(nemenyi,
                 "Mean Ranks and Nemenyi Post Hoc Comparison Against the Leading Model",
                 "A model marked 'No' cannot be distinguished from the best performer at "
                 "α = .05. The Nemenyi critical difference scales with the number of "
                 "models and shrinks only with the number of folds, so comparing many "
                 "models over a few folds can produce a critical difference wider than "
                 "the whole range of ranks — in which case every row reads 'No'. That is "
                 "a statement about the power of this test, not evidence that the models "
                 "perform equally; the leaderboard and its confidence intervals are the "
                 "more informative comparison.",
                 slug="t38_nemenyi", decimals=3, align={"Model": LEFT,
                                                        "Distinguishable from best": LEFT})

    print("      refitting every model on train + validation, scoring on test ...")
    predictions, fitted = {}, {}
    for name in ALL_MODELS:
        pred, model = predict_model(name, bundle, idx_trval, idx_test,
                                    rf_params=rf_params,
                                    nn_epochs=120 if quick else None,
                                    return_model=True)
        predictions[name] = pred
        fitted[name] = model
        print(f"        {name:<34s} RMSE = {np.sqrt(np.mean((pred - y_test) ** 2)):.4f}")

    board = leaderboard(predictions, y_test)
    report.table(board,
                 f"Test-Partition Leaderboard for All {len(ALL_MODELS)} Models",
                 "Every model refitted on the combined training and validation "
                 "partitions, then scored once on the untouched test partition. Skill is "
                 "the percentage reduction in mean squared error relative to climatology; "
                 "a negative value means the model is worse than quoting the historical "
                 "average, which is the result a reader most needs to see.",
                 slug="t39_leaderboard", decimals=3, int_columns=("Rank",),
                 align={"Model": LEFT, "95% CI for RMSE": LEFT},
                 landscape=True, font_size=Pt(9))

    top_models = list(board["Model"].head(5))
    report.raw_table(pairwise_dm_matrix(predictions, y_test, top_models),
                     "Diebold–Mariano Comparisons Among the Five Leading Models",
                     "Cell entries are two-sided p values for the null hypothesis that the "
                     "row and column models have equal forecast accuracy on the test "
                     "partition. The test is paired on the absolute errors of the same "
                     "sequences.",
                     slug="t40_dm_matrix", align={"Model": LEFT}, font_size=Pt(9))

    # Headline models, fitted on training data only, so the train/validation/test
    # progression shows how much optimism each carries.
    best_net = min(SEQUENCE_NETS, key=lambda n: float(
        summary.loc[summary["Model"] == n, "M RMSE"].iloc[0]))
    nets, net_predictions = {}, {}
    for name in SEQUENCE_NETS:
        Str, Sall = bundle.sequence(idx_train, np.arange(len(sequences)))
        net = SEQUENCE_NETS[name](seed=CFG.SEED, epochs=120 if quick else CFG.NN_EPOCHS)
        cut = int(0.85 * len(Str))
        net.fit(Str[:cut], bundle.y[idx_train][:cut], Str[cut:], bundle.y[idx_train][cut:])
        nets[name] = net
        net_predictions[name] = net.predict(Sall)
    print(f"      best sequence network by validation RMSE: {best_net}")

    rf_all = rf.predict(bundle.tabular(idx_train, np.arange(len(sequences)))[1])
    detail = {}
    for label, idx in (("training", idx_train), ("validation", idx_val), ("test", idx_test)):
        detail[f"Random Forest — {label}"] = {"y_true": bundle.y[idx], "y_pred": rf_all[idx]}
    for label, idx in (("training", idx_train), ("validation", idx_val), ("test", idx_test)):
        detail[f"{best_net} — {label}"] = {"y_true": bundle.y[idx],
                                           "y_pred": net_predictions[best_net][idx]}
    report.table(regression_table(detail),
                 "Regression Performance Across the Three Partitions for the Two Headline "
                 "Models",
                 "Both models here are fitted on the training partition alone, so the gap "
                 "between training and test error is each model's optimism; a large gap "
                 "indicates overfitting. Confidence intervals are percentile bootstrap "
                 f"intervals over {CFG.BOOTSTRAP_N:,} resamples. MSE, RMSE and MAE are in "
                 "magnitude units.",
                 slug="t41_regression_detail", decimals=3, int_columns=("n",),
                 align={"Model and partition": LEFT, "95% CI for RMSE": LEFT},
                 landscape=True, font_size=Pt(8.5))

    report.raw_table(_network_training_table(nets, sequence_backend()).astype(str),
                     "Training Outcome of the Three Sequence Networks",
                     "All three networks share the optimiser, the early-stopping rule and "
                     "the input tensor, so the comparison isolates the architecture. The "
                     "GRU carries roughly a quarter fewer parameters than the LSTM; the "
                     "convolutional net has no recurrence at all, and including it tests "
                     "whether the task actually requires a memory of the sequence.",
                     slug="t42_network_training",
                     align={"Setting": LEFT, "LSTM": LEFT, "GRU": LEFT, "1D-CNN": LEFT})

    report.table(compare_models(y_test, predictions["Random Forest"],
                                predictions[best_net], "Random Forest", best_net),
                 "Statistical Comparison of the Two Headline Models on the Test Partition",
                 "Tests are paired on the absolute errors of the same test sequences. "
                 "Diebold–Mariano is the standard forecast-comparison test; the Wilcoxon "
                 "signed-rank test is reported because the loss differentials are not "
                 "normal.",
                 slug="t43_model_comparison", decimals=4, p_columns=("p",),
                 align={"Comparison": LEFT, "Statistic": LEFT, "Interpretation": LEFT})

    Xtrval, Xtest = bundle.tabular(idx_trval, idx_test)
    importance = feature_importance_table(fitted["Random Forest"], Xtest, y_test)
    report.table(importance,
                 "Random Forest Feature Importance for Mainshock Magnitude",
                 "Impurity importance is the model's built-in metric and is biased toward "
                 "high-cardinality continuous features. Permutation importance is measured "
                 "on the held-out test partition and is the more trustworthy ranking; it "
                 "reports the increase in error when a feature is randomly shuffled.",
                 slug="t44_feature_importance", decimals=4, int_columns=("Rank",),
                 align={"Feature": LEFT}, font_size=Pt(9))

    # ---- ordinal classification ------------------------------------------ #
    y_class_trval = sequences["TargetClass"].astype(str).to_numpy()[idx_trval]
    y_class_test = sequences["TargetClass"].astype(str).to_numpy()[idx_test]
    clf = fit_random_forest_classifier(Xtrval, y_class_trval, rf_params)
    pred_class = clf.predict(Xtest)
    labels = list(CFG.MAG_CLASS_LABELS)
    strong = [i for i, c in enumerate(clf.classes_) if c != CFG.MAG_CLASS_LABELS[0]]
    prob_strong = clf.predict_proba(Xtest)[:, strong].sum(axis=1)

    matrix, confusion_display = confusion_table(y_class_test, pred_class, labels)
    report.raw_table(confusion_display,
                     "Confusion Matrix for Magnitude-Class Forecasts on the Test Partition",
                     "Rows are observed classes, columns are forecast classes. Cell "
                     "entries are counts with row percentages in parentheses; the diagonal "
                     "holds the correct forecasts. An empty column means the classifier "
                     "never issued that forecast: under this degree of class imbalance the "
                     "majority vote of the forest is the common class for every sequence, "
                     "even with balanced class weights. Tables 48 and 49 assess the same "
                     "forecasts without relying on that vote.",
                     slug="t45_confusion", align={"Actual class": LEFT})
    report.table(classification_report_table(y_class_test, pred_class, labels),
                 "Per-Class Precision, Recall and F1-Score on the Test Partition",
                 "Support is the number of test sequences observed in each class. The "
                 "macro average weights every class equally and is the fairer summary "
                 "under imbalance.",
                 slug="t46_classification_report", decimals=3, int_columns=("Support",),
                 strip_zero_columns=("Precision", "Recall", "F1-score"),
                 align={"Magnitude class": LEFT})
    report.table(overall_classification_table(y_class_test, pred_class, labels),
                 "Overall Classification Agreement, Including Cohen's Weighted Kappa",
                 "Quadratic weighting penalises a forecast that misses by two classes far "
                 "more than one that misses by one, as the study methodology requires. "
                 "Interpretation follows the Landis and Koch benchmarks. Compare the "
                 "accuracy against the majority-class rate in the final row before reading "
                 "it as skill.",
                 slug="t47_overall_classification", decimals=3,
                 strip_zero_columns=("Estimate",),
                 align={"Metric": LEFT, "95% CI": LEFT, "Interpretation": LEFT})

    # Platt scaling: turn the regression forecast into a calibrated probability
    # by fitting a logistic link on the training-and-validation forecasts only.
    rf_trval_pred = fitted["Random Forest"].predict(Xtrval)
    platt = LogisticRegression().fit(rf_trval_pred.reshape(-1, 1),
                                     (bundle.y[idx_trval] >= 6.0).astype(int))
    prob_regression = platt.predict_proba(predictions["Random Forest"].reshape(-1, 1))[:, 1]
    report.table(probabilistic_skill_table(y_test, {
        "Random Forest classifier P(M ≥ 6.0)": prob_strong,
        "Random Forest regression, Platt-scaled": prob_regression}),
        "Threshold-Free Probabilistic Skill for the M ≥ 6.0 Forecast",
        "ROC AUC above .50 and a positive Brier skill score indicate discrimination "
        "beyond the base rate. This is the evidence for whether the model carries any "
        "usable signal about strong events, independent of where the decision threshold "
        "is placed — a classifier whose argmax is degenerate can still rank correctly. "
        "The regression forecast is converted to a probability by Platt scaling fitted on "
        "the training and validation partitions alone.",
        slug="t48_probabilistic_skill", decimals=3,
        strip_zero_columns=("ROC AUC", "Average precision", "Brier score",
                            "Brier skill score", "Base rate"),
        align={"Probability source": LEFT})
    report.table(binary_alarm_table(y_test, predictions["Random Forest"], threshold=6.0),
                 "Operational Skill of the Forecast Treated as an M ≥ 6.0 Alarm",
                 "Derived from the regression forecasts by thresholding at M 6.0. POD and "
                 "FAR answer the question a disaster-management reader has, which class "
                 "accuracy does not: how many strong events are caught, and at what cost "
                 "in false alarms.",
                 slug="t49_alarm_skill", decimals=3, align={"Quantity": LEFT})

    report.table(residual_diagnostics({
        f"{name} (test)": {"y_true": y_test, "y_pred": predictions[name]}
        for name in top_models[:3]}),
        "Residual Diagnostics for the Three Leading Models",
        "A significant mean residual indicates systematic bias; a significant "
        "heteroscedasticity slope indicates error that grows with the forecast magnitude; "
        "a significant Ljung–Box Q indicates residuals that remain autocorrelated in time.",
        slug="t50_residuals", decimals=3,
        p_columns=("p (bias)", "p (normality)", "p (heterosced.)", "p (autocorr.)"),
        int_columns=("n",), align={"Model": LEFT}, landscape=True, font_size=Pt(8.5))

    # ------------------------------------------------------------- Stage 7 --
    if run_figures:
        print("\n[7/7] Figures")
        ensure_portrait(doc)
        add_heading(doc, "Section G. Figures", 1)
        report.figure(fig_distributions(catalogue),
                      "Distribution of Magnitude and Focal Depth in the Cleaned Catalogue",
                      f"N = {len(catalogue):,} events.", width_in=6.4)
        report.figure(fig_epicentres(catalogue),
                      "Epicentral Distribution of Catalogued Earthquakes",
                      "Open circles mark events of M ≥ 6.0.", width_in=4.2)
        report.figure(fig_gutenberg_richter(catalogue),
                      "Frequency–Magnitude Distribution and the Gutenberg–Richter Fit",
                      "The fitted line uses the Aki–Utsu maximum-likelihood b-value above "
                      "Mc.", width_in=4.4)
        report.figure(fig_temporal(annual),
                      "Annual Recorded Seismicity and Annual Maximum Magnitude",
                      "Bars are event counts (left axis); the line is the annual maximum "
                      "magnitude (right axis).", width_in=6.4)
        report.figure(fig_cv_distribution(cv, list(summary["Model"])),
                      "Distribution of Validation RMSE Across Rolling-Origin Folds",
                      "Models ordered by mean RMSE. The width of each box is the model's "
                      "instability across folds, which a single test score cannot show.",
                      width_in=6.2)
        report.figure(fig_leaderboard(board),
                      f"Test-Partition RMSE for All {len(ALL_MODELS)} Models",
                      "The dashed line marks the climatology baseline; any bar to its "
                      "right is a model that fails to beat the historical average.",
                      width_in=6.2)
        report.figure(fig_learning_curves({n: net.history_ for n, net in nets.items()}),
                      "Validation Learning Curves for the Three Sequence Networks",
                      "Early stopping restores the weights at each curve's minimum.",
                      width_in=5.2)
        report.figure(fig_importance(importance),
                      "Permutation Feature Importance for the Random Forest Model",
                      "Error bars are ±1 SD over 20 permutation repeats on the test "
                      "partition.", width_in=5.0)
        report.figure(fig_predictions({m: {"y_true": y_test, "y_pred": predictions[m]}
                                       for m in top_models[:3]}),
                      "Forecast Versus Observed Mainshock Magnitude for the Three Leading "
                      "Models", "The dashed line is perfect agreement.", width_in=6.4)
        report.figure(fig_residuals({m: {"y_true": y_test, "y_pred": predictions[m]}
                                     for m in top_models[:3]}),
                      "Residuals Against Forecast Magnitude", None, width_in=5.0)
        report.figure(fig_confusion(matrix, labels),
                      "Confusion Matrix for Magnitude-Class Forecasts", None, width_in=4.4)

    _finish(doc, report, started)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Statistical analysis and ML pipeline for the PHIVOLCS catalogue.")
    parser.add_argument("--no-models", action="store_true",
                        help="skip model training and evaluation")
    parser.add_argument("--no-figures", action="store_true", help="skip figure generation")
    parser.add_argument("--quick", action="store_true",
                        help="smaller search grids and shorter network training")
    parser.add_argument("--excel", default=None, help="path to an alternative workbook")
    args = parser.parse_args()
    main(run_models=not args.no_models, run_figures=not args.no_figures,
         quick=args.quick, excel=args.excel)
