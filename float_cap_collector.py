"""Attempt public CSI300 constituent free-float data; publish only audited dates.
No current-constituent backfill, no interpolated float cap, no fake 2024 values.
"""
from pathlib import Path
import pandas as pd
import akshare as ak

DATA = Path(__file__).resolve().parent / "data"
OUT = DATA / "csi300_float_cap_observed.csv"

def main():
    # The CNI endpoint has historically offered some index sample histories.
    # Availability of 000300 and the free-float column is NOT guaranteed.
    try:
        frame = ak.index_detail_hist_cni(symbol="000300")
    except Exception as exc:
        print(f"NOTICE: CNI CSI300 historical constituent float cap unavailable: {exc}")
        return
    needed = {"日期", "样本代码", "自由流通市值"}
    if not needed.issubset(frame.columns):
        print(f"NOTICE: CNI data lacks required free-float columns: {list(frame.columns)}")
        return
    d = frame[list(needed)].copy()
    d["date"] = pd.to_datetime(d["日期"], errors="coerce").dt.normalize()
    d["code"] = d["样本代码"].astype(str).str.zfill(6)
    d["float_yi"] = pd.to_numeric(d["自由流通市值"], errors="coerce")
    d = d.dropna(subset=["date", "float_yi"])
    d = d[d["float_yi"].gt(0)].drop_duplicates(["date", "code"])
    # A daily total is valid only when all 300 distinct constituents are reported.
    summary = d.groupby("date").agg(
        constituent_count=("code", "nunique"),
        csi300_float_cap_yi=("float_yi", "sum")).reset_index()
    summary = summary[summary["constituent_count"].eq(300)].copy()
    if summary.empty:
        print("NOTICE: no 300-constituent complete float-cap dates; no output")
        return
    if OUT.exists():
        old = pd.read_csv(OUT)
        old["date"] = pd.to_datetime(old["date"], errors="coerce")
        summary = pd.concat([old, summary], ignore_index=True)
    summary = summary.drop_duplicates("date", keep="last").sort_values("date")
    DATA.mkdir(exist_ok=True)
    summary["date"] = summary["date"].dt.strftime("%Y-%m-%d")
    summary.to_csv(OUT, index=False)
    print(f"Saved {len(summary)} dates with 300 observed constituent float-cap values")
    print("CNI definition may differ from CSI index official adjusted market cap; verify before publication.")

if __name__ == "__main__":
    main()
