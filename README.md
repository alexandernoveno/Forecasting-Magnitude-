# Forecasting Mainshock Magnitudes from PHIVOLCS Foreshock Data

Undergraduate thesis, BS Civil Engineering, Lyceum of the Philippines
University, Cavite, 2026.
Loui Cris C. Atienza, Alexander Jr. R. Noveno, Joseph Lorenz B. Pajarin.

A statistical analysis of the 1907 to 2026 PHIVOLCS earthquake catalogue and a
comparison of sixteen models that forecast the magnitude of a mainshock from
the foreshock sequence preceding it. Every event carries its distance to the
nearest active fault, measured against fault lines mapped in QGIS.

**The headline result is modest and reported as such.** An Extra Trees ensemble
on 27 engineered features reduces squared error by 23.6% against simply quoting
the historical average magnitude. The typical error is still about half a
magnitude unit. A third of the field, including the convolutional network and
the multilayer perceptron, fails to beat that average at all.

This is not a prediction system. It estimates how large a mainshock would be if
one follows a sequence already under way, and says nothing about whether one
will occur, or when, or where.

## What is here

| Path | What it is |
|---|---|
| `earthquake_analysis.py` | The whole analysis in one file. 50 tables, 11 figures, one Word document. |
| `index.html` | The landing page, served at the repository root by GitHub Pages |
| `app.js` | Hero drum chart and the forecast panel behaviour |
| `export_model_bundle.py` | Exports the trained models to JSON for the browser |
| `verify_bundle.cjs` | Checks the browser reimplementation against Python |
| `outputs/` | Generated tables, figures and the Word document |
| `Earthquake Data Sets NEW.xlsx` | The source catalogue with mapped fault distances |

The analysis is one file: **`earthquake_analysis.py`**. It produces 50
APA 7th-edition tables and 11 figures in a single Word document, plus every
table as CSV.

## Run it

```bash
pip install -r requirements.txt
python earthquake_analysis.py
```

About three minutes end to end. Options:

```bash
python earthquake_analysis.py --no-models     # statistics only, ~15 s
python earthquake_analysis.py --quick         # smaller grids, shorter training
python earthquake_analysis.py --no-figures
python earthquake_analysis.py --excel "Other Catalogue.xlsx"
```

## Output

```
outputs/
  Statistical_Analysis_Tables.docx   50 tables + 11 figures, APA format
  tables/*.csv                       every table as raw numbers
  tables/feature_matrix.csv          the 22-feature modelling data set
  tables/cv_raw_folds.csv            per-model, per-fold validation scores
  figures/*.png                      300 dpi, greyscale-safe
```

## What is inside the file

| Part | Contents |
|---|---|
| 1 | Configuration — every threshold in one class |
| 2 | Utilities and APA number formatting |
| 3 | Data loading, cleaning, audit trail, working magnitude |
| 4 | Descriptive statistics and frequency distributions |
| 5 | Normality, correlation, ANOVA/Kruskal–Wallis, Dunn, χ², Mann–Kendall |
| 6 | Completeness magnitude (MAXC, GFT) and b-value (LSQ, Aki–Utsu MLE) |
| 7 | Maeda's declustering method, Equations 1–3 of Hirose et al. (2021) |
| 8 | The 22 engineered features of Wang et al. (2023) |
| 9 | LSTM, GRU and 1D-CNN implemented directly on NumPy |
| 10 | The 16-model zoo and rolling-origin validation |
| 11 | Evaluation, model comparison, weighted κ, residual diagnostics |
| 12 | Figures |
| 13 | APA 7 Word export |
| 14 | Main pipeline |

## The models compared

| Family | Models |
|---|---|
| Baseline | Climatology, Persistence |
| Tabular ML | Random Forest, Extra Trees, Gradient Boosting, Histogram GB, SVR, k-NN, Elastic Net, Ridge, MLP |
| Sequence | LSTM, GRU, 1D-CNN — on the raw foreshock stream |
| Classical time series | ARIMA, ARIMAX |

All sixteen are scored on identical sequences, first by expanding-window
rolling-origin validation and then once on an untouched test partition.

TensorFlow and PyTorch are optional. The three sequence networks fall back to
NumPy implementations contained in the file, so the pipeline runs identically on
a machine with neither installed. Their backward passes are verified against
numerical gradients to about 1e-6.

## Analysis decisions worth knowing

**Fault distance is a separate feature group, not a rewrite of Table 1.** The
methodology's feature table lists 22 features and does not include fault
distance, although Data Collection names it as a selected parameter. The 22 are
reproduced exactly as published; five more summarise how far the foreshocks sit
from the nearest mapped fault. Three of those five rank fifth, sixth and
seventh of 27 by permutation importance and together carry 18% of the total.
The other two, closest approach and migration trend, score negative and measure
nothing the model can use. The mainshock's own fault distance is deliberately
excluded: it is a property of the event being forecast.

**The supplied fault distances are used as given, and checked.** They are the
authors' own QGIS measurement. Recomputing them from the coordinate pairs beside
them agrees for 98.2% of events to within a kilometre; the residual grows with
distance and is immaterial inside the 100 km observation radius. The browser
cannot rerun a QGIS layer, so it takes the nearest of the 797 distinct source
points the catalogue resolves to, which reproduces the mapped assignment for
99.7% of events and is at most 0.24 km further out for the rest.

**Occurrence probability is reported as a historical rate, not a model output.**
Objective 2 asks for the magnitude and its probability. The magnitude model
assumes an earthquake follows and estimates how large; it cannot say whether
one follows, because every sequence in that data set ends in a mainshock and so
every label is positive. A separate occurrence data set was therefore built:
1,702 to 4,125 anchors, each a moment and place with recent activity, labelled
by whether an independent earthquake of a given size followed within the next
14 days at a given radius.

Across nine combinations of magnitude and radius the calibrated model beat the
historical base rate in exactly one, M 5.0 and above within 50 km, by 3.4%
Brier skill with a fold-to-fold spread several times that. Scored on a single
chronological split it looked far better, which is why it is scored across
rolling-origin folds: one split returns an AUC anywhere from .13 to .80 on the
same cell when a test block holds four to thirty positives. The site therefore
publishes the observed conditional frequencies and states what the model
achieved. Tables 33 and 34 carry the full grid.

**The catalogue is complete only from M 4.0.** No event in the workbook carries
a working magnitude below 4.0 — PHIVOLCS publishes its bulletin from that
threshold. Magnitude classes therefore begin at the catalogue's own floor rather
than at the conventional "micro" class, which would be empty.

**The four magnitude scales are not homogenised.** Ml, mb and Ms are almost
never co-reported with Mw, so no defensible conversion could be estimated from
this catalogue alone (Table 5). The working magnitude is the first available
scale in the order Mw > Ms > mb > Ml. `CFG.MAGNITUDE_POLICY = "converted"`
switches on conversion if you later supply a catalogue with better Mw overlap.

**Observation windows come from the full catalogue, not the declustered one.**
Maeda's method removes small dependent events, which is correct for estimating
background rates — but those events *are* the precursory activity the 22
features measure. Mainshock targets come from the declustered catalogue; their
windows come from the full one.

**Every split is chronological, never random.** A shuffled split lets a model
learn from the future of its own test set, which is the most common way a
seismic forecasting result turns out to be an artefact. Imputation, winsorising
and scaling are refitted inside each fold from that fold's training rows only.

**Heavy-tailed features are log-transformed and winsorised before modelling.**
`Energy` spans about ten orders of magnitude and the magnitude deficit diverges
as the fitted b-value approaches zero. Both transforms are monotone, so the tree
ensembles are unaffected; without them the linear, kernel and neural models are
driven by single pathological windows.

**Extra Trees is capped at depth 10 so it can be shipped to the browser.**
Unrestricted it reaches 13 MB of JSON and scores 0.4904; at depth 10 it is
1.7 MB and scores 0.4922, a difference an order of magnitude inside the
bootstrap interval on this test set. The analysis and the export are pinned to
the same configuration so there is one number, not two.

**The energy feature follows the thesis, not the literature.** Table 1 of the
methodology gives `Energy = sqrt(Σ 10^(12 + 1.8·Mi))`. Wang et al. (2023) and
the classical Gutenberg–Richter energy relation use `(11.8, 1.5)`. The thesis
form is the default so the reported numbers match the written method; change
`CFG.ENERGY_COEFFS` to `(11.8, 1.5)` for the literature form.

## Reproducibility

Seeded at `CFG.SEED = 42` throughout: every forest, the permutation importance,
every bootstrap, and all three network initialisations. Re-running reproduces
every number in the document.

## The landing page

The site lives at the repository root so GitHub Pages serves it at the project
URL with no configuration: the study's findings plus an interactive panel that
runs the trained models in the browser.

**Live: https://alexandernoveno.github.io/Forecasting-Magnitude-/**

| File | What it is |
|---|---|
| `index.html` | The page itself: markup, design tokens, interaction layer |
| `app.js` | Hero drum chart and forecast panel |
| `forecast.js` | Feature engineering and the four models, reimplemented in JavaScript |
| `model_bundle.json` | Random Forest, Gradient Boosting, Elastic Net and LSTM, exported |
| `catalogue.json` | The cleaned catalogue, for regional context |
| `export_model_bundle.py` | Builds the two JSON files from the trained models |
| `verify_bundle.cjs` | Checks the JavaScript against Python |

```bash
python export_model_bundle.py    # rebuild the models the page runs
node verify_bundle.cjs           # confirm the browser matches Python
```

**Run `verify_bundle.cjs` after touching either implementation.** `forecast.js`
is a second implementation of maths that already exists in Python, so the two
can drift apart silently and the page would report wrong forecasts with no
error. The verifier replays 60 held-out sequences through the browser code and
compares against Python: 1,320 feature values and 240 predictions, failing on
any disagreement past tolerance.

Three of the four models agree with Python to floating-point noise. Extra Trees
does too, because its split thresholds are drawn at random inside each feature's
range and so rarely sit next to a value being tested. The Random Forest is the
exception: its thresholds are midpoints between adjacent observed values,
exactly where test values cluster, so a feature differing in the seventh decimal
can land on the other side of a split. Measured over the 60 sequences, that
moves its forecast by at most 1.04e-2 magnitude units and changes the
two-decimal figure on the page in 3 cases of 60. That is 2% of the model's own
RMSE and well inside the plus or minus half a unit the page already reports, so
it is bounded and documented rather than engineered away.

The panel forecasts the magnitude a mainshock would reach given a foreshock
sequence already under way. It does not forecast whether one will happen, or
when, or where, and the page says so where the number appears.

## Publishing the landing page

The site is plain static files at the repository root, with no build step.
GitHub Pages serves it from `main` with the source set to `/ (root)`. A
`.nojekyll` file turns Jekyll off so the files are served exactly as committed.
To preview locally:

```bash
python -m http.server 8000
```

The interactive panel fetches `model_bundle.json` and `catalogue.json`, so it
needs to be served over HTTP rather than opened as a `file://` path.

## Note on `analysis/`

The `analysis/` package is the earlier multi-file version of this same
pipeline. `earthquake_analysis.py` supersedes it and adds the model zoo and
rolling-origin validation. Delete `analysis/` to avoid keeping two copies.
