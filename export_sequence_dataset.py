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
SPLITS = ROOT / "outputs" / "Train_Test_Datasets.xlsx"


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

    # The catalogue carries no place name; "Location Parameter" in the source
    # workbook is the coordinate pair, and the fault distance and magnitude
    # scale are per-event columns the reviewers asked to see carried through.
    lookup = cat_sorted.set_index("datetime")[["SrcDistKm", "MagScale"]]
    lookup = lookup[~lookup.index.duplicated(keep="first")]

    def extras(when):
        try:
            hit = lookup.loc[pd.Timestamp(when)]
        except KeyError:
            return None, ""
        dist = float(hit["SrcDistKm"]) if pd.notna(hit["SrcDistKm"]) else None
        return (round(dist, 3) if dist is not None else None), str(hit["MagScale"])

    mains, fores = [], []
    for i, row in sequences.iterrows():
        sid = f"M{i + 1:03d}"
        events = emb.window_events(cat_sorted, row, ea)
        dist, scale = extras(row["MainshockTime"])
        mains.append({
            "Sequence ID": sid,
            "Partition": partition[i],
            "Date and Time (UTC)": row["MainshockTime"],
            "Lat (N)": round(float(row["MainshockLat"]), 4),
            "Long (E)": round(float(row["MainshockLon"]), 4),
            "Distance to the Nearest Source (km)": dist,
            "Depth (km)": round(float(row["MainshockDepth"]), 1),
            "Magnitude": round(float(row["Target"]), 2),
            "Magnitude scale used": scale,
            "Foreshocks in window": len(events),
            "Largest foreshock magnitude": round(float(row["Mag_max"]), 2),
            "Gap to largest foreshock": round(float(row["Target"] - row["Mag_max"]), 2),
        })
        for k, e in enumerate(events, start=1):
            when = pd.Timestamp(e["when"])
            fdist = e.get("dist")
            fscale = e.get("scale", "")
            fores.append({
                "Sequence ID": sid,
                "Partition": partition[i],
                "Foreshock no.": k,
                "Date and Time (UTC)": when,
                # Six decimals is a tenth of a second. Four rounded the
                # closest foreshocks to a flat 0.0, which reads as the
                # mainshock's own record rather than an event just before it.
                "Days before mainshock": round(e["before"], 6),
                "Lat (N)": e["lat"],
                "Long (E)": e["lon"],
                "Distance to the Nearest Source (km)": (
                    None if fdist is None else round(float(fdist), 3)),
                "Depth (km)": e["depth"],
                "Magnitude": e["mag"],
                "Magnitude scale used": fscale,
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
         f"{ea.CFG.MIN_FORESHOCKS} catalogued events inside the window, and "
         "larger than every one of them."),
        ("How to use it",
         "Type one sequence's foreshock rows into the forecaster in the order "
         "the columns appear, then compare the forecast against Recorded "
         "mainshock magnitude on the Mainshocks sheet."),
        ("Partition",
         "Training and Validation rows were seen while fitting. Only Test rows "
         "are held out, so those are the fair check of forecast accuracy."),
        ("No foreshock exceeds its mainshock",
         "Checked on every row of the Foreshocks sheet. Windows that held an "
         "earthquake larger than the mainshock were sequences belonging to a "
         "different cluster, swept in because the observation radius is wider "
         "than Maeda's spatial window; they are excluded."),
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

    write_splits(ea, sequences, partition, mains)


def write_splits(ea, sequences, partition, mains) -> None:
    """The same sequences as the 27-feature matrix the models are fitted on,
    one sheet per chronological partition. This is the modelling data set; the
    other workbook is the raw events behind it.

    The identifying columns the reviewers named come first, in their words, so
    a row can be matched against the PHIVOLCS bulletin without decoding a
    feature name: sequence, partition, when, where, how far from the nearest
    mapped fault, how deep, how large, and on which magnitude scale. The 27
    features follow."""
    table = sequences.copy()
    lead = mains.set_index(mains["Sequence ID"])
    ids = [f"M{i + 1:03d}" for i in range(len(table))]
    table.insert(0, "Magnitude scale used",
                 [lead.loc[i, "Magnitude scale used"] for i in ids])
    table.insert(0, "Distance to the Nearest Source (km)",
                 [lead.loc[i, "Distance to the Nearest Source (km)"] for i in ids])
    table.insert(0, "Partition", partition)
    table.insert(0, "Sequence ID", ids)
    table = table.rename(columns={
        "MainshockTime": "Date and Time (UTC)",
        "MainshockLat": "Lat (N)", "MainshockLon": "Long (E)",
        "MainshockDepth": "Depth (km)", "Target": "Magnitude"})
    order = ["Sequence ID", "Partition", "Date and Time (UTC)", "Lat (N)",
             "Long (E)", "Distance to the Nearest Source (km)", "Depth (km)",
             "Magnitude", "Magnitude scale used"]
    table = table[order + [c for c in table.columns if c not in order]]

    rows = []
    for name in ("Training", "Validation", "Test"):
        part = table[table["Partition"] == name]
        rows.append({
            "Partition": name, "n sequences": len(part),
            "% of total": round(100 * len(part) / len(table), 1),
            "First mainshock": part["Date and Time (UTC)"].min(),
            "Last mainshock": part["Date and Time (UTC)"].max(),
            "Mean target M": round(float(part["Magnitude"].mean()), 3),
            "SD": round(float(part["Magnitude"].std(ddof=1)), 3),
            "Min": float(part["Magnitude"].min()),
            "Max": float(part["Magnitude"].max()),
            "n (M >= 6.0)": int((part["Magnitude"] >= 6.0).sum()),
            "n (M >= 7.0)": int((part["Magnitude"] >= 7.0).sum()),
        })
    summary = pd.DataFrame(rows)

    dictionary = pd.DataFrame(
        [{"#": i + 1, "Feature": f,
          "Category": ea.FEATURE_CATEGORIES.get(f, ""),
          "Description": ea.FEATURE_DESCRIPTIONS.get(f, "")}
         for i, f in enumerate(ea.FEATURE_NAMES)])

    with pd.ExcelWriter(SPLITS, engine="openpyxl",
                        datetime_format="yyyy-mm-dd hh:mm:ss") as xl:
        summary.to_excel(xl, sheet_name="Summary", index=False)
        for name in ("Training", "Validation", "Test"):
            table[table["Partition"] == name].to_excel(xl, sheet_name=name, index=False)
        dictionary.to_excel(xl, sheet_name="Feature Dictionary", index=False)
        for sheet in xl.sheets.values():
            sheet.freeze_panes = "A2"
    print(f"Wrote {SPLITS}")
    print("  " + ", ".join(f"{r['Partition']} {r['n sequences']}" for r in rows)
          + f", {len(ea.FEATURE_NAMES)} features per row")


if __name__ == "__main__":
    main()
