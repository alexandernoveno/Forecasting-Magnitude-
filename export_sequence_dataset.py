"""Export every mainshock together with the foreshocks that preceded it.

The validators want to retype a sequence into the forecaster and check the
result against what the catalogue actually recorded, so the foreshock sheet is
laid out in the same order as the web form: days before, magnitude, latitude,
longitude, depth. Everything is rebuilt from the workbook, so this file never
drifts from the analysis.
"""
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "Foreshock_Sequences.xlsx"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    ea = load("earthquake_analysis")
    emb = load("export_model_bundle")

    catalogue, _, _ = ea.load_catalogue()
    flagged, _ = ea.decluster(catalogue)
    independent = flagged[~flagged["IsDependent"]].reset_index(drop=True)
    sequences = ea.build_sequences(independent, full=catalogue)
    cat_sorted = catalogue.sort_values("datetime").reset_index(drop=True)

    train, val, _ = ea.chronological_split(sequences)
    partition = (["Training"] * len(train) + ["Validation"] * len(val)
                 + ["Test"] * (len(sequences) - len(train) - len(val)))

    mains, fores = [], []
    for i, row in sequences.iterrows():
        sid = f"M{i + 1:03d}"
        events = emb.window_events(cat_sorted, row, ea)
        mains.append({
            "Sequence ID": sid,
            "Partition": partition[i],
            "Mainshock date and time (UTC)": row["MainshockTime"],
            "Mainshock latitude N": round(float(row["MainshockLat"]), 4),
            "Mainshock longitude E": round(float(row["MainshockLon"]), 4),
            "Mainshock depth km": round(float(row["MainshockDepth"]), 1),
            "Recorded mainshock magnitude": round(float(row["Target"]), 2),
            "Foreshocks in window": len(events),
            "Largest foreshock magnitude": round(float(row["Mag_max"]), 2),
        })
        for k, e in enumerate(events, start=1):
            fores.append({
                "Sequence ID": sid,
                "Foreshock no.": k,
                "Days before mainshock": round(e["before"], 4),
                "Magnitude": e["mag"],
                "Latitude N": e["lat"],
                "Longitude E": e["lon"],
                "Depth km": e["depth"],
            })

    mains = pd.DataFrame(mains)
    fores = pd.DataFrame(fores)

    notes = pd.DataFrame([
        ("What this file is",
         "Every mainshock the study forecasts, with the catalogued earthquakes "
         "that preceded it inside the observation window."),
        ("Observation window",
         f"{ea.CFG.T_OBS_DAYS:.0f} days before the mainshock, within "
         f"{ea.CFG.RADIUS_KM:.0f} km of its epicentre."),
        ("Mainshock definition",
         f"An independent event of M {ea.CFG.MAINSHOCK_MIN_MAG:.1f} or above, "
         "independence decided by Maeda declustering, with at least "
         f"{ea.CFG.MIN_FORESHOCKS} catalogued events inside the window."),
        ("How to use it",
         "Type one sequence's foreshock rows into the forecaster in the order "
         "the columns appear, then compare the forecast against Recorded "
         "mainshock magnitude on the Mainshocks sheet."),
        ("Partition",
         "Training and Validation rows were seen while fitting. Only Test rows "
         "are held out, so those are the fair check of forecast accuracy."),
        ("Foreshocks are not always smaller",
         "The window counts every catalogued event inside the radius, "
         "aftershocks of an earlier larger earthquake included. In "
         f"{100 * (sequences['Target'] < sequences['Mag_max']).mean():.0f}% of "
         "sequences the mainshock is smaller than the largest event in its own "
         "window, so a forecast below the largest foreshock is expected."),
        ("Sequences", f"{len(mains):,}"),
        ("Foreshock records", f"{len(fores):,}"),
        ("Source", "PHIVOLCS catalogue, Earthquake Data Sets NEW.xlsx"),
    ], columns=["Item", "Detail"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl", datetime_format="yyyy-mm-dd hh:mm:ss") as xl:
        notes.to_excel(xl, sheet_name="Read me", index=False)
        mains.to_excel(xl, sheet_name="Mainshocks", index=False)
        fores.to_excel(xl, sheet_name="Foreshocks", index=False)
        for sheet, frame in (("Read me", notes), ("Mainshocks", mains),
                             ("Foreshocks", fores)):
            ws = xl.sheets[sheet]
            ws.freeze_panes = "A2"
            for col, name in enumerate(frame.columns, start=1):
                width = max(len(str(name)), frame[name].astype(str).str.len().max())
                ws.column_dimensions[ws.cell(1, col).column_letter].width = min(width + 3, 60)

    mains.to_csv(ROOT / "outputs" / "tables" / "sequences_mainshocks.csv", index=False)
    fores.to_csv(ROOT / "outputs" / "tables" / "sequences_foreshocks.csv", index=False)
    print(f"Wrote {OUT}")
    print(f"  {len(mains):,} mainshocks, {len(fores):,} foreshock records")


if __name__ == "__main__":
    main()
