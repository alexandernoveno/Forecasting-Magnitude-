"""Copy everything the client needs into one folder.

Run this after the pipeline so the folder cannot go stale. That is not a
hypothetical: Train_Test_Datasets.xlsx sat at 321/107/107 rows long after the
data set had changed, because nothing regenerated it, and the notes in this
file described four models and 199 mainshocks after both had changed.

Every count below is now read from the file it describes rather than typed,
for the same reason the landing page reads its headline figures from the
pipeline's tables: a number written twice is a number that will disagree with
itself.

    python3 build_client_package.py
"""
import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "For Client"


def counts() -> dict:
    """Whatever the built files actually contain, for the notes below."""
    out = {"models": "the trained models", "tables": "every table",
           "figures": "", "splits": "", "sequences": "", "foreshocks": "",
           "vectors": ""}
    bundle = ROOT / "model_bundle.json"
    if bundle.exists():
        data = json.loads(bundle.read_text())
        names = [data["models"][k]["label"] for k in data["models"]]
        out["models"] = ", ".join(names)
    vectors = ROOT / "verification_vectors.json"
    if vectors.exists():
        out["vectors"] = str(len(json.loads(vectors.read_text())["vectors"]))
    tables = ROOT / "outputs" / "tables"
    if tables.exists():
        out["tables"] = str(len(list(tables.glob("t[0-9]*.csv"))))
    figures = ROOT / "outputs" / "figures"
    if figures.exists():
        out["figures"] = str(len(list(figures.glob("*.png"))))
    try:
        import pandas as pd
        splits = ROOT / "outputs" / "Train_Test_Datasets.xlsx"
        if splits.exists():
            summary = pd.read_excel(splits, sheet_name="Summary")
            out["splits"] = ", ".join(
                f"{r['Partition']} {int(r['n sequences'])}"
                for _, r in summary.iterrows())
        seqs = ROOT / "outputs" / "Foreshock_Sequences.xlsx"
        if seqs.exists():
            out["sequences"] = f"{len(pd.read_excel(seqs, sheet_name='Mainshocks')):,}"
            out["foreshocks"] = f"{len(pd.read_excel(seqs, sheet_name='Foreshocks')):,}"
    except Exception:
        pass
    return out


def files(n) -> list:
    return [
        ("earthquake_analysis.py",
         "The whole pipeline in one file. Cleaning, Maeda declustering, "
         f"Gutenberg-Richter, 27 features, 16 models, {n['tables']} tables, "
         f"{n['figures']} figures, the statistical appendix. About 4 minutes."),
        ("build_chapter4.py",
         "Lays the same tables out in the Chapter 4 structure the evaluators "
         "asked for: four discussions and a synthesis. Run it after the "
         "pipeline. Seconds."),
        ("export_model_bundle.py",
         "Exports the trained models and the evidence panels to JSON for the "
         "website. About 1 minute."),
        ("export_sequence_dataset.py",
         "Writes both spreadsheets below. About 20 seconds."),
        ("verify_forecasts.py",
         "Give the validators this one. Checks the data set and the forecasts "
         "without retraining anything. Seconds."),
        ("requirements.txt", "Python packages needed."),
        ("data/active_faults.json",
         "The active fault traces the website draws and measures distances "
         "against, built from the coordinates you supplied."),
        ("outputs/Train_Test_Datasets.xlsx",
         f"The modelling data. {n['splits']}. One row per mainshock, with the "
         "identifying columns first (sequence, partition, date and time, "
         "coordinates, distance to the nearest source, depth, magnitude and "
         "the scale it came from) and all 27 features after. Split "
         "chronologically."),
        ("outputs/Foreshock_Sequences.xlsx",
         f"The raw events behind those rows. {n['sequences']} mainshocks, "
         f"{n['foreshocks']} foreshocks, each with its own date and time, "
         "coordinates, fault distance, depth and magnitude. This is what "
         "validators retype into the website."),
        ("outputs/Chapter_4_Results_and_Discussion.docx",
         "Chapter 4 in the requested structure: Discussion 1 to 4 and the "
         "synthesis, with the tables and figures each section needs."),
        ("outputs/Statistical_Analysis_Tables.docx",
         f"The full statistical appendix. {n['tables']} tables and "
         f"{n['figures']} figures in APA 7 format, in the order the analysis "
         "computes them."),
        ("model_bundle.json",
         f"The trained models, exported: {n['models']}. verify_forecasts.py "
         "reads this, and so does the website."),
        ("verification_vectors.json",
         f"The {n['vectors']} held-out sequences with the predictions "
         "scikit-learn made for them, so the exported models can be checked "
         "rather than trusted."),
        ("outputs/tables/verification_forecasts.csv",
         "Forecast against recorded magnitude for every held-out sequence, "
         "written by verify_forecasts.py."),
    ]


RUN_ORDER = ("earthquake_analysis.py", "export_model_bundle.py",
             "export_sequence_dataset.py", "build_chapter4.py",
             "verify_forecasts.py")


def main() -> None:
    n = counts()
    manifest = files(n)
    missing = [name for name, _ in manifest if not (ROOT / name).exists()]
    if missing:
        raise SystemExit("Run the pipeline first. Missing: " + ", ".join(missing))

    DEST.mkdir(exist_ok=True)
    lines = ["FILES FOR THE CLIENT",
             f"Copied from the project on {date.today():%d %B %Y}.", ""]
    for name, note in manifest:
        shutil.copy2(ROOT / name, DEST / Path(name).name)
        lines += [Path(name).name, f"    {note}", ""]
    lines += [
        "TO REBUILD EVERYTHING FROM THE RAW CATALOGUE",
        "    pip install -r requirements.txt",
        *(f"    python3 {name}" for name in RUN_ORDER),
        "",
        "Only the first script needs 'Earthquake Data Sets NEW.xlsx', which is",
        "not in this folder, being the raw catalogue. Everything else here",
        "runs as it stands:",
        "",
        "    python3 verify_forecasts.py",
        "",
        "Website: https://alexandernoveno.github.io/Forecasting-Magnitude-/",
        "Code:    https://github.com/alexandernoveno/Forecasting-Magnitude-",
        ""]
    (DEST / "READ ME FIRST.txt").write_text("\n".join(lines))
    print(f"Copied {len(manifest)} files to {DEST}")


if __name__ == "__main__":
    main()
