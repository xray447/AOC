"""从 navdata 导出探针用的跑道端 CSV（ident,runway,heading,lat,lon,elev_ft）。"""
import csv
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[3] / "Pre-train/dataset/little_navmap_navigraph.sqlite"
OUT = Path(__file__).resolve().parents[1] / "data/runways.csv"
AIRPORTS = ("RJTT", "RJAA", "RJCC", "ROAH", "ZBAA", "ZSSS", "RKSI")

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = con.execute(
    "select a.ident, re.name, re.heading, re.laty, re.lonx, re.altitude "
    "from runway r join runway_end re "
    "on re.runway_end_id in (r.primary_end_id, r.secondary_end_id) "
    "join airport a on a.airport_id = r.airport_id").fetchall()
OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["airport", "runway", "heading", "lat", "lon", "elev_ft"])
    for r in sorted(rows):
        if r[0] in AIRPORTS:
            w.writerow([r[0], r[1], round(r[2], 1), round(r[3], 6), round(r[4], 6), round(r[5])])
print("wrote", OUT, "rows", len(AIRPORTS))
