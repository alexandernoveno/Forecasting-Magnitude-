"""Copy everything the client needs into one folder.

Run this after the pipeline so the folder cannot go stale. That is not a
hypothetical: Train_Test_Datasets.xlsx sat at 321/107/107 rows long after the
data set had changed, because nothing regenerated it.

    python3 build_client_package.py
"""
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "For Client"

FILES = [
    ("earthquake_analysis.py",
     "The whole pipeline in one file. Cleaning, Maeda declustering, "
     "Gutenberg-Richter, 27 features, 16 models, 56 tables, 12 figures, the "
     "Word document. About 4 minutes."),
    ("export_model_bundle.py",
     "Exports the four trained models to JSON for the website. About 1 minute."),
    ("export_sequence_dataset.py",
     "Writes both spreadsheets below. About 20 seconds."),
    ("verify_forecasts.py",
     "Give the validators this one. Checks the data set and the forecasts "
     "without retraining anything. Seconds."),
    ("requirements.txt", "Python packages needed."),
    ("outputs/Train_Test_Datasets.xlsx",
     "The modelling data. Training 119, Validation 40, Test 40, one row per "
     "mainshock with all 27 features and the target. Split chronologically."),
    ("outputs/Foreshock_Sequences.xlsx",
     "The raw events behind those rows. 199 mainshocks, 1,305 foreshocks, in "
     "the column order the website asks for. This is what validators retype."),
    ("outputs/Statistical_Analysis_Tables.docx",
     "All results. 56 tables and 12 figures in APA 7 format."),
    ("model_bundle.json",
     "The four trained models, exported. verify_forecasts.py reads this, and "
     "so does the website."),
    ("verification_vectors.json",
     "The 40 held-out sequences with the predictions scikit-learn made for "
     "them, so the exported models can be checked rather than trusted."),
    ("outputs/tables/verification_forecasts.csv",
     "Forecast against recorded magnitude for each of the 40 held-out "
     "sequences, written by verify_forecasts.py."),
]

RUN_ORDER = ("earthquake_analysis.py", "export_model_bundle.py",
             "export_sequence_dataset.py", "verify_forecasts.py")


def main() -> None:
    missing = [name for name, _ in FILES if not (ROOT / name).exists()]
    if missing:
        raise SystemExit("Run the pipeline first. Missing: " + ", ".join(missing))

    DEST.mkdir(exist_ok=True)
    lines = ["FILES FOR THE CLIENT",
             f"Copied from the project on {date.today():%d %B %Y}.", ""]
    for name, note in FILES:
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
    print(f"Copied {len(FILES)} files to {DEST}")


if __name__ == "__main__":
    main()
