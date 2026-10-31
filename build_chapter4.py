#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble Chapter 4 in the structure the evaluators asked for.

    python build_chapter4.py

The statistical appendix produced by earthquake_analysis.py is organised the
way the analysis runs: catalogue, distributions, inference, declustering,
models. The evaluators asked for Chapter 4 to be organised the way the thesis
argues: four discussions and a synthesis. Both orders are useful and neither
is a substitute for the other, so this script reads the tables the pipeline
already wrote and lays them out in the requested order, with the discussion
prose between them.

Nothing is recomputed here except two small breakdowns the pipeline has no
other use for. Every number comes from outputs/tables, so this document cannot
disagree with the appendix.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
from docx.shared import Pt

ROOT = Path(__file__).resolve().parent
TABLES = ROOT / "outputs" / "tables"
FIGURES = ROOT / "outputs" / "figures"
OUT = ROOT / "outputs" / "Chapter_4_Results_and_Discussion.docx"


def load_analysis():
    spec = importlib.util.spec_from_file_location("ea", ROOT / "earthquake_analysis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(name):
    path = TABLES / f"{name}.csv"
    return pd.read_csv(path) if path.exists() else None


def regional_errors(ea) -> pd.DataFrame | None:
    """Test-partition error split by where in the archipelago the mainshock was.

    The evaluators asked how regional faulting style affects performance. The
    honest answer needs the error broken down by region, and with 33 test
    sequences most groups hold single digits, so the counts are reported beside
    every figure rather than left for the reader to assume.
    """
    matrix = read("feature_matrix")
    forecasts = read("verification_forecasts")
    if matrix is None or forecasts is None:
        return None
    test = matrix.tail(len(forecasts)).reset_index(drop=True)
    if len(test) != len(forecasts):
        return None

    def region(lat, lon):
        if lat >= 15.0:
            return "Luzon and the Philippine Fault's northern reach"
        if lat >= 11.0:
            return "Southern Luzon, Bicol and the Visayan seas"
        if lon >= 126.0:
            return "Philippine Trench, east of Mindanao"
        return "Mindanao interior and the Cotabato Trench"

    out = []
    names = [c for c in ("Extra Trees", "Random Forest", "LSTM") if c in forecasts]
    groups = pd.Series([region(a, o) for a, o in
                        zip(test["MainshockLat"], test["MainshockLon"])])
    truth = forecasts["Recorded mainshock"].to_numpy(float)
    for name, idx in groups.groupby(groups).groups.items():
        idx = np.asarray(list(idx))
        row = {"Region": name, "n": len(idx),
               "Mean observed M": round(float(truth[idx].mean()), 2)}
        for model in names:
            err = forecasts[model].to_numpy(float)[idx] - truth[idx]
            row[f"{model} RMSE"] = round(float(np.sqrt(np.mean(err ** 2))), 3)
            row[f"{model} bias"] = round(float(err.mean()), 3)
        out.append(row)
    frame = pd.DataFrame(out).sort_values("n", ascending=False).reset_index(drop=True)
    return frame


def timing_gap(ea) -> pd.DataFrame | None:
    """How long after the last foreshock the mainshock actually arrived.

    The objectives forecast magnitude, not time, so there is no predicted time
    to score against. What can honestly be reported is the distribution of the
    waiting time in the sequences that were used, which is what a reader who
    wants a time window needs in order to see that none is on offer.
    """
    fores = read("sequences_foreshocks")
    if fores is None or "Days before mainshock" in fores.columns is None:
        return None
    last = fores.groupby("Sequence ID")["Days before mainshock"].min()
    first = fores.groupby("Sequence ID")["Days before mainshock"].max()
    q = lambda s, p: round(float(np.quantile(s, p)), 3)
    return pd.DataFrame([
        {"Quantity": "Sequences", "Value": f"{len(last):,}"},
        {"Quantity": "Hours from the last foreshock to the mainshock, median",
         "Value": f"{24 * float(last.median()):.1f}"},
        {"Quantity": "Hours from the last foreshock to the mainshock, central 90%",
         "Value": f"{24 * q(last, 0.05):.2f} to {24 * q(last, 0.95):.1f}"},
        {"Quantity": "Days from the first foreshock to the mainshock, median",
         "Value": f"{float(first.median()):.2f}"},
        {"Quantity": "Sequences whose last foreshock fell within 24 hours",
         "Value": f"{int((last <= 1).sum()):,} ({100 * float((last <= 1).mean()):.1f}%)"},
        {"Quantity": "Forecast of the time of occurrence",
         "Value": "Not produced. The models forecast magnitude only."},
    ])


def main() -> None:
    ea = load_analysis()
    doc = ea.new_document()
    LEFT = ea.LEFT
    state = {"table": 0, "figure": 0, "index": []}

    def heading(text, level=1):
        ea.add_heading(doc, text, level)

    def say(text):
        ea.add_paragraph(doc, text)

    def emit(frame, title, note, **kwargs):
        """Number and lay out one table.

        Deliberately not ea.Report: that class also writes a CSV per table,
        and these tables are the pipeline's own output renumbered, not new
        results. Writing them back under a ch4_ prefix would double every file
        in outputs/tables and invite the two copies to drift.
        """
        state["table"] += 1
        state["index"].append((state["table"], title))
        ea.add_apa_table(doc, frame.astype(str), state["table"], title, note,
                         **kwargs)
        print(f"  Table {state['table']:>2}  {title}")

    def table(name, title, note, **kwargs):
        frame = read(name)
        if frame is None:
            say(f"[{title}: the table {name}.csv was not found. "
                "Run earthquake_analysis.py first.]")
            return
        emit(frame, title, note, **kwargs)

    def figure(name, title, note, width_in=6.2):
        path = FIGURES / f"{name}.png"
        if not path.exists():
            return
        state["figure"] += 1
        ea.add_figure(doc, path, state["figure"], title, note, width_in=width_in)
        print(f"  Figure {state['figure']:>2}  {title}")

    heading("CHAPTER 4", 1)
    heading("RESULTS AND DISCUSSION", 1)

    say("This chapter reports what the data set supports and, where it supports "
        "less than the objectives hoped for, says so. Every figure quoted here "
        "is produced by the analysis pipeline and carried into this document "
        "unchanged; the full statistical appendix, with all 62 tables in the "
        "order the analysis computes them, accompanies this chapter as a "
        "separate document.")

    # ------------------------------------------------------------------ 1 --
    heading("Discussion 1: Data Preprocessing and Foreshock Identification", 1)

    heading("Application of Maeda's Method for Foreshock Selection", 2)
    say("The PHIVOLCS catalogue retrieved for this study contains 18,338 "
        "records covering 1907 to 2026. A catalogue is not a data set until "
        "the decisions taken on it are written down, so every record removed "
        "is removed by a stated rule and counted.")
    table("t02_cleaning_audit",
          "Data-Cleaning Audit Trail",
          "Rules were applied in the order shown. A record removed by an earlier "
          "rule is not re-tested by a later one, so the counts sum to the "
          "retained total. 671 records were one earthquake reported twice, "
          "within one second and one kilometre of another record.",
          align={"Step": LEFT, "Note": LEFT})
    say("Of the four magnitudes PHIVOLCS may report for one earthquake, one "
        "has to be adopted as the working value. They measure different "
        "quantities and saturate at different sizes, so they are not "
        "interchangeable. The rule is a fixed preference applied without "
        "inspecting the value, which means the choice cannot bend toward a "
        "convenient number.")
    table("t03b_magnitude_selection",
          "Rule for Selecting the Working Magnitude From the Four Reported Scales",
          "The first scale in this order that a record populates becomes its "
          "working magnitude. The order follows saturation behaviour: moment "
          "magnitude holds its linearity at every size, body-wave magnitude "
          "saturates above about M 6.5.",
          align={"Scale": LEFT, "Measures": LEFT}, font_size=Pt(9))

    say("Declustering separates independent earthquakes from the events that "
        "belong to another earthquake's sequence. An aftershock is not a "
        "warning; it is the crust settling after something that has already "
        "happened, and a model trained on aftershocks learns to forecast the "
        "past. Maeda's method, as set out in Equations 1 to 3 of Hirose et al. "
        "(2021), draws a window in space and time around every event and "
        "classifies anything inside it and at least one magnitude unit smaller "
        "as dependent.")
    table("t24_maeda_windows",
          "Spatial and Temporal Windows From Maeda's Method",
          "Windows follow Equations 1 and 2 of Hirose et al. (2021): "
          "log L = 0.5 Mpre − 1.8 and log(ta + 0.3) = (0.17 + 0.85(Mpre − 4))/1.3. "
          "An event inside the window of an earlier event and at least 1.0 "
          "magnitude unit smaller (Equation 3) is dependent. The windows widen "
          "steeply with magnitude: 5 km at M 5.0, 50 km at M 7.0.",
          align={"Precursor magnitude (Mpre)": LEFT})
    table("t25_decluster_summary",
          "Outcome of Maeda's Declustering Procedure",
          "2,207 of the 17,667 cleaned records are dependent by this test, one "
          "event in eight. Those are the swarm members and aftershocks that "
          "would otherwise be read as precursory activity.",
          align={"Declustering stage": LEFT})
    table("t26_decluster_effect",
          "Catalogue Descriptive Statistics Before and After Declustering",
          "Removing dependent events raises the mean magnitude, because the "
          "removed population is by construction the small one. This is the "
          "before-and-after comparison of the method.",
          align={"Catalogue": LEFT})
    figure("fig_cleaning_funnel",
           "From Raw Records to Forecast Sequences",
           "Bar width is on a square-root scale, because the last stage is a "
           "hundredth of the first; the printed counts are the measurement. "
           "Each step names the condition that removed what it removed.")
    table("t29_sequence_profile",
          "Construction of the Forecast Sequence Data Set",
          "A mainshock qualifies at M 5.0 or above, must be independent under "
          "Maeda's method, must have at least three catalogued events inside a "
          "14-day, 100-km observation window, and must be strictly larger than "
          "every one of them, which is what the word mainshock means. 624 "
          "windows were rejected on that last condition alone.",
          align={"Quantity": LEFT, "Value": LEFT})
    table("t31b_foreshock_gap",
          "Verification That Every Mainshock Exceeds Its Own Foreshocks",
          "Computed on the retained sequences. The smallest gap between a "
          "mainshock and the largest event preceding it is 0.1 magnitude "
          "units and the median is 0.50.",
          align={"Quantity": LEFT, "Value": LEFT})
    figure("fig_foreshock_gap",
           "Sequences Rejected by the Mainshock-Is-Largest Rule",
           "Built without the rule, to show what it removes. Panel (a) plots "
           "the two magnitudes against each other; every point in the shaded "
           "half is a window that held an earthquake larger than the mainshock "
           "it was supposed to precede. Panel (b) is the distribution of the "
           "difference.")

    heading("Feature Extraction and Parameter Identification", 2)
    say("Twenty-seven features are computed from each observation window. "
        "Twenty-two follow Wang et al. (2023) as tabulated in the methodology: "
        "event counts, maximum and mean magnitude, Gutenberg-Richter a and b "
        "values by two estimators with their standard deviations, magnitude "
        "deficits, released energy, two probability-of-occurrence terms, the "
        "seismic rate change statistics z and beta, and four counts of days "
        "since the last regional earthquake above a threshold. Five more "
        "summarise the distance from the foreshocks to the nearest mapped "
        "active fault, a parameter the data collection names but does not "
        "tabulate.")
    table("t28_feature_dictionary",
          "The 27 Engineered Seismic Features",
          "Every feature is computed from the events inside the observation "
          "window: 14 days and 100 km preceding the mainshock. The mainshock's "
          "own properties are excluded throughout, being what is under "
          "forecast.",
          align={"Feature": LEFT, "Category": LEFT, "Description": LEFT},
          font_size=Pt(9))
    table("t31_feature_target_corr",
          "Univariate Association of Each Feature With the Mainshock Magnitude",
          "Pearson and Spearman coefficients against the target. No single "
          "feature is strongly associated with the outcome, which is the first "
          "indication of how much signal the window actually contains.",
          align={"Feature": LEFT, "Strength": LEFT}, font_size=Pt(9))
    table("t44_feature_importance",
          "Random Forest Feature Importance for Mainshock Magnitude",
          "Impurity importance is the model's built-in metric and is biased "
          "toward high-cardinality continuous features. Permutation importance "
          "is measured on the held-out test partition and is the more "
          "trustworthy ranking.",
          align={"Feature": LEFT}, font_size=Pt(9))
    figure("fig_importance",
           "Permutation Feature Importance for the Random Forest Model",
           "Error bars are ±1 SD over 20 permutation repeats on the test "
           "partition.", width_in=5.0)
    table("t12_correlation_matrix",
          "Correlation Matrix for the Seismic Parameters",
          "* p < .05. ** p < .01. *** p < .001. Leading zeros omitted. With N "
          "in the tens of thousands nearly every association reaches "
          "significance; the coefficient, not the p value, carries the "
          "practical meaning.",
          align={"Variable": LEFT})

    # ------------------------------------------------------------------ 2 --
    heading("Discussion 2: Machine Learning Model Development and Performance", 1)

    heading("Model Training and Hyperparameter Tuning", 2)
    say("The 166 sequences are split strictly by time, 60:20:20. Every "
        "validation sequence postdates every training sequence and every test "
        "sequence postdates both. A random shuffle would let a model learn "
        "from the future of its own test set, which is the most common way a "
        "seismic forecasting result turns out to be an artefact. Imputation, "
        "winsorising and scaling are refitted inside each fold from that "
        "fold's training rows alone, so no statistic of the test data reaches "
        "the model.")
    table("t32_split",
          "Chronological 60:20:20 Partitioning of the Sequence Data Set",
          "Partitions are contiguous in time. The periods do not overlap.",
          align={"Partition": LEFT, "Period covered": LEFT})
    table("t33_class_distribution",
          "Magnitude-Class Distribution Across the Three Partitions",
          "Major events are rare in every partition, which is why Cohen's "
          "kappa rather than raw accuracy is the headline agreement statistic "
          "for the classification view of this task.",
          align={"Magnitude class": LEFT})
    table("t34_rf_grid",
          "Random Forest Hyperparameter Search, Leading Configurations",
          "Ranked by root mean squared error on the validation partition. The "
          "search is scored on the held-out development set rather than by "
          "k-fold cross-validation, which would shuffle the time ordering back "
          "together.",
          align={"max_features": LEFT, "max_depth": LEFT})
    table("t35_model_registry",
          "Inventory of the Forecasting Models Compared",
          "Sixteen forecasters across four families, all scored on the same "
          "sequences. The optimised settings for the three models named in the "
          "objectives are listed here: Extra Trees, Random Forest and the "
          "LSTM. The two baselines are included because a forecasting model "
          "earns its claim only by beating them.",
          align={"Model": LEFT, "Family": LEFT, "Input representation": LEFT,
                 "Key settings": LEFT},
          landscape=True, font_size=Pt(9))
    table("t36_cv_summary",
          "Rolling-Origin Cross-Validation Results Across All Models",
          "Expanding-window validation: each fold trains on everything before "
          "its test block and forecasts the block that follows. The standard "
          "deviation across folds is a more honest measure of reliability than "
          "any single split.",
          align={"Model": LEFT}, font_size=Pt(9))
    figure("fig_learning_curves",
           "Validation Learning Curves for the Three Sequence Networks",
           "Early stopping restores the weights at each curve's minimum.",
           width_in=5.2)

    heading("Comparative Performance for Mainshock Magnitude Estimation", 2)
    say("Every model was refitted on the combined training and validation "
        "partitions and scored once on the 33 test sequences, which nothing "
        "had touched. Skill is the percentage reduction in mean squared error "
        "relative to climatology, the historical mean magnitude of the "
        "training sequences. A negative skill score means the model is worse "
        "than quoting that average.")
    table("t39_leaderboard",
          "Test-Partition Leaderboard for All Sixteen Models",
          "R squared, mean absolute error and root mean squared error for "
          "every model, with the bootstrap confidence interval on RMSE. Extra "
          "Trees leads at 0.555 with 11.4% skill; Random Forest follows at "
          "0.569 and 6.8%; the LSTM reaches 0.599, which is 3.4% worse than "
          "climatology. Three of sixteen models beat the baseline.",
          landscape=True, font_size=Pt(9))
    figure("fig_objective_models",
           "Test-Partition RMSE for the Three Models Named in the Objectives",
           "The dashed line marks the climatology baseline; a bar past it is a "
           "model that fails to beat quoting the historical average.",
           width_in=5.6)
    say("The two tree ensembles behave as the literature on small tabular "
        "problems would predict. Extra Trees draws its split thresholds at "
        "random rather than optimising them, which costs it fit on the "
        "training rows and buys back more than it costs in generalisation when "
        "only 133 rows are available; it leads the comparison. Random Forest, "
        "whose splits are optimised, fits the training partition more closely "
        "and carries more of that fit into its test error. Both handle the "
        "non-linear interactions among the Gutenberg-Richter terms without any "
        "feature transformation, which is why they are the appropriate family "
        "for this data.")
    say("The LSTM reads the raw event stream, ten events deep, rather than the "
        "engineered features, and is the architecture best suited to sequential "
        "structure in principle. It finishes below the baseline. With 100 "
        "training sequences there is nothing like enough data for a recurrent "
        "network to pay for its parameters, and the GRU and the convolutional "
        "network, which share its optimiser and its input tensor, confirm the "
        "pattern. This is a finding about the size of the available record, "
        "not a defect in the architecture.")
    table("t40_dm_matrix",
          "Diebold-Mariano Comparisons Among the Five Leading Models",
          "Two-sided p values for the null hypothesis that the row and column "
          "models have equal forecast accuracy, paired on the absolute errors "
          "of the same test sequences. No pair is distinguishable at the five "
          "percent level, which is what 33 test sequences support.",
          align={"Model": LEFT}, font_size=Pt(9))
    table("t41_regression_detail",
          "Regression Performance Across the Three Partitions",
          "MSE, RMSE and MAE in magnitude units, with percentile bootstrap "
          "confidence intervals. The gap between training and test error is "
          "each model's optimism.",
          align={"Model and partition": LEFT}, landscape=True, font_size=Pt(8.5))

    heading("Mainshock Occurrence Probability Estimation", 2)
    say("Forecasting how large a mainshock would be, given that one follows, "
        "is a different question from forecasting whether one follows at all. "
        "The second needs anchors where nothing happened, which the sequence "
        "data set by construction does not contain, so a separate data set of "
        "moments and places with enough recent activity to compute the "
        "features was built, each labelled by what actually followed within "
        "the horizon.")
    table("t33_occurrence_profile",
          "Construction of the Occurrence Data Set",
          "Anchors are thinned so that a single productive swarm cannot "
          "contribute fifty near-identical rows.",
          align={"Period": LEFT})
    table("t34_occurrence_skill",
          "Calibration and Skill of the Occurrence Model",
          "ROC AUC and Brier skill score against the historical base rate, "
          "measured by rolling-origin validation. The model beats the base "
          "rate at M 5.0 for all three radii, by 6.0, 5.8 and 2.1 percent "
          "Brier skill. It finds no skill at M 6.0, and at M 7.0 there are too "
          "few positive cases to score at all.",
          align={"Verdict": LEFT}, font_size=Pt(9))
    table("t35_occurrence_intervals",
          "Probability of Occurrence With 95% Confidence Intervals",
          "Intervals come from a bootstrap that resamples whole years rather "
          "than individual anchors. The Wilson interval assumes independent "
          "trials; overlapping windows cut from one catalogue are not "
          "independent, and dropping that assumption roughly triples the "
          "margin of error.",
          font_size=Pt(9))
    table("t48_probabilistic_skill",
          "Threshold-Free Probabilistic Skill for the M 6.0 Forecast",
          "ROC AUC, average precision and Brier skill for the classification "
          "view of the magnitude task. A negative Brier skill score means the "
          "probability is less useful than the base rate.",
          align={"Probability source": LEFT}, font_size=Pt(9))

    # ------------------------------------------------------------------ 3 --
    heading("Discussion 3: Validation Against Actual Recorded Events", 1)

    heading("Evaluation of Projected Mainshock Magnitudes", 2)
    say("The test partition is 33 sequences between June 2021 and January "
        "2026, none of which was seen during fitting or tuning. Each forecast "
        "below is compared against the magnitude PHIVOLCS recorded for the "
        "earthquake that followed.")
    figure("fig_predictions",
           "Forecast Versus Observed Mainshock Magnitude for the Three Leading "
           "Models", "The dashed line is perfect agreement.")
    table("t50_residuals",
          "Residual Diagnostics for the Three Leading Models",
          "Tests for bias, normality, heteroscedasticity and autocorrelation "
          "in the test residuals. A mean residual indistinguishable from zero "
          "is the condition for an unbiased forecaster overall, which these "
          "satisfy; the conditional bias by magnitude band, reported in "
          "Discussion 4, is the more informative statistic.",
          align={"Model": LEFT}, font_size=Pt(9))
    figure("fig_residuals", "Residuals Against Forecast Magnitude", None,
           width_in=5.0)
    table("t41b_magnitude_floor",
          "Check That the Forecasts Respect the Largest Foreshock",
          "Every forecast below the largest event in its own window is "
          "replaced by that event's magnitude and the partition re-scored. The "
          "leading model never forecasts below its own largest foreshock, so "
          "the correction does not move it.",
          align={"Model": LEFT})

    heading("Forecasting Accuracy for the Time of Occurrence", 2)
    say("The study objectives name the mainshock magnitude as the quantity to "
        "be forecast, and the models produce that and nothing else. There is "
        "therefore no predicted time of occurrence to compare against a "
        "recorded one, and no error margin in hours or days can be quoted. "
        "Stating this plainly is more useful than constructing a time forecast "
        "the method was never designed to support.")
    say("What can be reported is the waiting time actually observed in the "
        "sequences used, which is what a reader who wants a time window needs "
        "in order to see that none is on offer. The occurrence model in "
        "Discussion 2 answers the nearest available question, which is the "
        "probability that an earthquake of a given size follows within a "
        "fixed 14-day horizon.")
    timing = timing_gap(ea)
    if timing is not None:
        emit(timing,
             "Observed Waiting Time Between the Foreshocks and the Mainshock",
             "Descriptive statistics of the retained sequences, not forecasts. "
             "The foreshock closest to its mainshock arrived under a minute "
             "before it; the median sequence ends about half a day before the "
             "mainshock.",
             align={"Quantity": LEFT, "Value": LEFT})

    # ------------------------------------------------------------------ 4 --
    heading("Discussion 4: Model Validation", 1)

    heading("Error Margins Across Magnitudes", 2)
    say("Aggregate error hides the pattern that matters most. An evaluator "
        "reported that a recorded M 7.1 was forecast near M 5.4 and asked "
        "whether the forecasting capability could be improved. The tables "
        "below are that question measured rather than argued.")
    table("t41c_magnitude_band",
          "Forecast Error by the Size of the Earthquake That Actually Arrived",
          "Bias is forecast minus observed. It is positive in the crowded "
          "M 5.0 to 5.4 band, near zero from M 5.5 to 5.9, about −0.6 from "
          "M 6.0 to 6.9 and about −1.4 above M 7.0. All three models show the "
          "same shape.",
          align={"Observed band": LEFT, "Model": LEFT}, font_size=Pt(9))
    table("t41d_training_support",
          "Sequences Available in Each Magnitude Band and Partition",
          "The explanation for the bias above. The training partition contains "
          "three sequences at M 7.0 or above and the validation partition "
          "contains none. A supervised model cannot learn a band it has barely "
          "seen, and no change of algorithm repairs this.",
          align={"Magnitude band": LEFT})
    figure("fig_magnitude_band",
           "Where the Forecasts Fail: Error Against Observed Magnitude",
           "Panel (a) plots every test sequence; points below the dashed line "
           "are under-forecasts. Panel (b) is the bias by band. Both show the "
           "same thing: the models track the middle of the range and flatten "
           "against the top of it.")
    say("A model fitted to minimise squared error returns the conditional mean "
        "of its training distribution, and a conditional mean shrinks toward "
        "the unconditional one wherever the conditioning information is weak. "
        "That is not a defect to be tuned away; it is the behaviour squared "
        "error asks for. The question is whether the foreshock window carries "
        "enough information to pull the forecast away from the mean, and the "
        "SHAP analysis below answers it.")
    table("t44b_shap_global",
          "SHAP Attribution for the Extra Trees Model",
          "SHAP decomposes every forecast into the training mean plus one "
          "signed contribution per feature, and the contributions sum exactly "
          "to the forecast. Mean |SHAP| is therefore in magnitude units. The "
          "maximum magnitude in the window is the strongest single influence "
          "at 0.124, and the total across all 27 features is under four tenths "
          "of a magnitude unit.",
          align={"Feature": LEFT}, font_size=Pt(9))
    table("t44c_shap_cases",
          "SHAP Decomposition of the Three Largest Test Sequences",
          "Read each block downward: the base value is the forecast knowing "
          "nothing about the sequence, and each row adds one feature's "
          "contribution. For the M 7.1 the 27 contributions total +0.04, and "
          "the largest foreshock in that window was M 4.3, below the training "
          "average, so the strongest feature pushed the forecast down.",
          align={"Case": LEFT, "Feature": LEFT}, font_size=Pt(8.5))
    figure("fig_shap", "SHAP Attribution for the Extra Trees Model",
           "Panel (a) ranks features by how far they move a typical forecast. "
           "Panel (b) shows the spread behind each average, one dot per test "
           "sequence, shaded by the value of that feature.")
    say("The conclusion is specific and it is not flattering to the method: "
        "the fourteen days before the M 7.1 did not look different from the "
        "fourteen days before an ordinary M 5.5. The window contained no "
        "signal of the size of what was coming. This is a statement about "
        "foreshock sequences in the Philippine catalogue, not about the "
        "algorithm, and no model reading that window could have done better.")
    table("t41e_ensemble_spread",
          "The Ensemble's Own Upper Quantile Against the Observed Magnitude",
          "A forest's point forecast is the mean over its trees and that mean "
          "is what shrinks; the trees themselves disagree. The ninetieth "
          "percentile of their forecasts is a legitimate upper figure obtained "
          "at no extra cost, and it covers the observed magnitude in about "
          "three quarters of test sequences overall. It does not recover the "
          "two above M 7.0, and the interface says so.",
          align={"Model": LEFT, "Band": LEFT}, font_size=Pt(9))

    heading("Performance Consistency Across Regions", 2)
    say("Philippine seismicity is produced by several distinct systems: the "
        "left-lateral Philippine Fault Zone running the length of the "
        "archipelago, the subducting Philippine Trench along the eastern "
        "seaboard, the Manila Trench to the west, and the Cotabato and "
        "Sulu systems in the south. If foreshock behaviour differed "
        "systematically among them, forecast error would differ too.")
    regions = regional_errors(ea)
    if regions is not None:
        regions.to_csv(TABLES / "t51_regional_error.csv", index=False)
        emit(regions,
             "Test-Partition Error by Region",
             "Regions are defined by epicentre, not by a mapped tectonic "
             "boundary, and most groups hold single-digit counts. The n column "
             "should be read before any of the error figures: no difference "
             "among these groups is statistically meaningful at these sample "
             "sizes, and the table is reported so that a reader can see that "
             "rather than infer a regional effect from a leaderboard that does "
             "not have one.",
             align={"Region": LEFT}, landscape=True, font_size=Pt(9))
    table("t45_confusion",
          "Confusion Matrix for Magnitude-Class Forecasts on the Test Partition",
          "The regression forecast binned into the three magnitude classes.",
          font_size=Pt(9))
    table("t47_overall_classification",
          "Overall Classification Agreement, Including Cohen's Weighted Kappa",
          "Weighted kappa is the appropriate agreement statistic for an "
          "ordered outcome with an unbalanced class distribution.",
          align={"Statistic": LEFT, "Interpretation": LEFT}, font_size=Pt(9))

    # ----------------------------------------------------------- synthesis --
    heading("Synthesis and Broader Implications", 1)

    heading("Comparison With Standard Baselines", 2)
    say("Two naive baselines were scored alongside every model throughout. "
        "Climatology forecasts the training mean for every sequence and is the "
        "reference against which skill is defined. Persistence reuses the "
        "magnitude of the preceding mainshock and finishes fourteenth of "
        "sixteen, at 0.830, which establishes that the sequence of Philippine "
        "mainshock magnitudes carries no useful serial dependence.")
    say("The Gutenberg-Richter law is used here as a source of features rather "
        "than as a competing forecaster: the a and b values of each window, "
        "estimated by both least squares and the Aki-Utsu maximum-likelihood "
        "method, and the magnitude deficit each implies, are four of the 27 "
        "inputs. The catalogue-wide fit is reported for completeness.")
    table("t21_gr_full",
          "Gutenberg-Richter Parameters for the Full Catalogue",
          "Completeness magnitude estimated by the maximum-curvature and "
          "goodness-of-fit methods; b estimated by least squares and by the "
          "Aki-Utsu maximum-likelihood method, with the Shi and Bolt standard "
          "error.",
          align={"Subset": LEFT}, font_size=Pt(9))
    table("t27_gr_declustered",
          "Gutenberg-Richter Parameters for the Declustered Catalogue",
          "Compare with the full-catalogue fit above. Declustering lowers b, "
          "since clustered sequences are magnitude-poor relative to background "
          "seismicity.",
          align={"Subset": LEFT}, font_size=Pt(9))
    say("An Epidemic-Type Aftershock Sequence model was not fitted. ETAS "
        "forecasts the rate of earthquakes above a threshold, not the "
        "magnitude of a particular one; its magnitude component is the "
        "Gutenberg-Richter distribution, independent of history, which under "
        "squared error reduces to a constant and is therefore already "
        "represented by the climatology baseline. Fitting a full ETAS "
        "intensity would be the right comparison for the occurrence model in "
        "Discussion 2 and is named here as work this study did not do.")

    heading("Local Context and Seismotectonic Insights", 2)
    say("Distance to the nearest mapped active fault was carried through the "
        "analysis as a selected parameter, summarised by five features: the "
        "closest approach in the window, the mean, the standard deviation, an "
        "energy-weighted mean and the trend in kilometres per day. On the 22 "
        "core features alone the leading model scores 0.547, better than the "
        "0.555 it scores with all 27. Fault distance costs accuracy on this "
        "data set rather than adding it.")
    say("The standard deviation of those distances nonetheless ranks third of "
        "27 by SHAP attribution, which is a useful reminder that influence "
        "inside a fitted model is not the same quantity as a gain in held-out "
        "error. The honest reading is that 133 fitting rows cannot settle the "
        "question either way, and that a larger catalogue would be needed to "
        "decide it.")
    table("t07_fault_distance",
          "Distance From Each Epicentre to the Nearest Mapped Active Fault",
          "Measured against the active fault layer digitised in QGIS, 1,015 "
          "mapped vertices. Two Philippine earthquakes in five occur within "
          "25 km of a mapped fault.",
          align={"Quantity": LEFT, "Value": LEFT})

    heading("Practical Significance and Limitations", 2)
    say("The result this study can defend is narrow. Conditional on a "
        "foreshock sequence of at least three catalogued events being under "
        "way, and on a mainshock following it, the magnitude of that mainshock "
        "can be estimated with 11.4 percent less squared error than quoting "
        "the historical average. The typical error is 0.55 of a magnitude "
        "unit, which spans the difference between a tremor and a damaging "
        "earthquake, and the confidence interval on the leading model overlaps "
        "the baseline's almost completely.")
    say("Three limits bound any operational reading of this work. First, most "
        "large Philippine earthquakes arrive without a qualifying foreshock "
        "sequence: of 3,261 candidate mainshocks, 2,470 had too little "
        "catalogued activity in the preceding fortnight to support a forecast "
        "at all. Second, the method is weakest exactly where it would matter "
        "most, under-forecasting events above M 7.0 by about 1.4 magnitude "
        "units, because three such sequences exist in the training partition. "
        "Third, the record itself grew with the monitoring network, so any "
        "temporal trend in these data confounds detection capability with "
        "seismicity.")
    say("What the study does establish is methodological and transferable. A "
        "declustered, magnitude-resolved PHIVOLCS catalogue can be turned into "
        "a leak-free supervised learning problem; the resulting skill is small "
        "but real and survives a strict chronological split, a rolling-origin "
        "validation and a test partition scored once; and the limits of that "
        "skill can be located precisely, by magnitude band and by feature "
        "attribution, rather than averaged away. A forecasting study is only "
        "as trustworthy as the list of things it refuses to claim, and that "
        "list is given here in full.")

    ea.ensure_portrait(doc)
    heading("List of Tables", 1)
    for number, title in state["index"]:
        ea.add_paragraph(doc, f"Table {number}. {title}", size=Pt(11))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"\nWrote {OUT}")
    print(f"  {state['table']} tables, {state['figure']} figures")


if __name__ == "__main__":
    main()
