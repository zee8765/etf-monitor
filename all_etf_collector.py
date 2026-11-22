"""Collect exchange-disclosed shares of direct CSI300 ETFs. Never fabricate free-float market cap."""
import datetime as dt
from pathlib import Path
import time
import pandas as pd
import akshare as ak

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "all_csi300_etf_market.csv"
TZ = dt.timezone(dt.timedelta(hours=8))
# A name-only screen is a candidate universe, not proof of benchmark tracking.
# Conservative whitelist: add funds only after verifying their tracking benchmark.
VERIFIED = {
    "510300", "510330", "510310", "159919",
    "510350", "510360", "510380", "510390",
    "159925", "159927", "159931", "159933",
    "159919", "159300", "159330", "159310",
    "563300", "563350", "563520", "563000",
}
# Some historical codes may be delisted or not track the plain CSI300.
# Therefore do NOT infer full-market coverage from this set alone.
COLUMNS = ["date", "code", "name", "shares_10k", "close", "market_cap_yi", "exchange"]

def normalize(frame, exchange, fallback=None):
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "code", "name", "shares_10k", "exchange"])
    required = {"基金代码", "基金份额"}
    if not required.issubset(frame.columns):
        print(f"WARNING {exchange}: missing columns {required-set(frame.columns)}")
        return pd.DataFrame(columns=["date", "code", "name", "shares_10k", "exchange"])
    name_col = next((c for c in ("基金简称", "基金名称", "证券简称", "证券名称") if c in frame), None)
    if name_col is None:
        print(f"WARNING {exchange}: cannot identify fund benchmark by name")
        return pd.DataFrame(columns=["date", "code", "name", "shares_10k", "exchange"])
    date_col = next((c for c in ("统计日期", "日期") if c in frame), None)
    d = frame.copy()
    d["code"] = d["基金代码"].astype(str).str.split(".").str[0].str.zfill(6)
    d["name"] = d[name_col].astype(str)
    # Direct CSI300 trackers only; exclude enhanced, linked and CSI300 sub-strategies.
    mask = d["name"].str.contains(r"沪深\\s*300|HS300|CSI\\s*300", case=False, regex=True, na=False)
    mask &= ~d["name"].str.contains(
        r"增强|联接|红利|价值|成长|低波|质量|等权|行业|策略|期权|杠杆|反向|股指",
        regex=True, na=False)
    d = d[mask].copy()
    if d.empty:
        return pd.DataFrame(columns=["date", "code", "name", "shares_10k", "exchange"])
    d["date"] = pd.to_datetime(d[date_col] if date_col else fallback, errors="coerce").dt.normalize() if date_col else pd.Timestamp(fallback)
    d["shares_10k"] = pd.to_numeric(
        d["基金份额"].astype(str).str.replace(",", "", regex=False), errors="coerce") / 10000
    d["exchange"] = exchange
    return d.loc[d["date"].notna() & d["shares_10k"].between(1, 1e8),
                 ["date", "code", "name", "shares_10k", "exchange"]]

def get_price(code, start, end):
    symbol = ("sh" if code.startswith("5") else "sz") + code
    try:
        d = ak.fund_etf_hist_sina(symbol=symbol)
        dc = "date" if "date" in d else "日期"
        pc = "close" if "close" in d else "收盘"
        d = d[[dc, pc]].rename(columns={dc:"date",pc:"close"})
        d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        return d[d["date"].between(start, end) & d["close"].gt(0)]
    except Exception as exc:
        print(f"WARNING {code} price unavailable: {exc}")
        return pd.DataFrame(columns=["date","close"])

def main():
    now = dt.datetime.now(TZ).date()
    frames = []
    # Recent exchange observations. The exchange APIs are not a complete
    # historical daily archive for every ETF; never fill missing observations.
    for days in range(1, 15):
        day = now - dt.timedelta(days=days)
        if day.weekday() >= 5:
            continue
        try:
            frames.append(normalize(ak.fund_etf_scale_sse(date=day.strftime("%Y%m%d")), "SSE", day))
        except Exception as exc:
            print(f"WARNING SSE {day}: {exc}")
        time.sleep(.4)
    try:
        frames.append(normalize(ak.fund_scale_daily_szse(
            start_date=(now-dt.timedelta(days=45)).strftime("%Y%m%d"),
            end_date=now.strftime("%Y%m%d"), symbol="ETF"), "SZSE"))
    except Exception as exc:
        print(f"WARNING SZSE: {exc}")
    frames = [x for x in frames if not x.empty]
    if not frames:
        raise RuntimeError("No exchange ETF share observations; preserving existing file")
    observed = pd.concat(frames, ignore_index=True)
    observed = observed.drop_duplicates(["date","code"], keep="last")
    prices = []
    for code in observed["code"].unique():
        p = get_price(code, observed["date"].min(), observed["date"].max())
        if not p.empty:
            p["code"] = code
            prices.append(p)
        time.sleep(.2)
    if not prices:
        raise RuntimeError("No ETF historical prices; preserving existing file")
    joined = observed.merge(pd.concat(prices), on=["date","code"], how="inner", validate="one_to_one")
    joined["market_cap_yi"] = joined["shares_10k"] * joined["close"] / 10000
    joined = joined[joined["market_cap_yi"].gt(0)]
    if OUT.exists():
        old = pd.read_csv(OUT, dtype={"code":str})
        old["date"] = pd.to_datetime(old["date"], errors="coerce").dt.normalize()
        joined = pd.concat([old[COLUMNS], joined[COLUMNS]], ignore_index=True)
    joined = joined.drop_duplicates(["date","code"], keep="last").sort_values(["date","code"])
    DATA.mkdir(exist_ok=True)
    joined["date"] = joined["date"].dt.strftime("%Y-%m-%d")
    joined[COLUMNS].to_csv(OUT, index=False)
    print(f"Saved {len(joined)} observed ETF rows across {joined['code'].nunique()} codes")
    print("IMPORTANT: name-screened universe is not certified complete. No full-market ratio published.")

if __name__ == "__main__":
    main()
