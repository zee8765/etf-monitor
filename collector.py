
"""ETF share collector for GitHub Actions."""

import datetime as dt
import pathlib
import random
import time

import pandas as pd
import akshare as ak

ETFS = {
    "510300": "SSE",
    "510330": "SSE",
    "510310": "SSE",
    "159919": "SZSE",
}

OUT = pathlib.Path(__file__).resolve().parent / "data" / "shares.csv"
COLS = ["date", "code", "shares_10k", "source"]
TZ = dt.timezone(dt.timedelta(hours=8))

# Raw units: "shares" or "10k_shares".
# Verify against exchange-published figures before production use.
RAW_UNITS = {
    "SSE": "shares",
    "SZSE": "shares",
}

LOOKBACK_DAYS = 14


def retry(label, func, attempts=3):
    for i in range(attempts):
        try:
            return func()
        except Exception as e:
            print(
                f"WARNING {label} attempt {i+1}/{attempts}: "
                f"{type(e).__name__}: {e}",
                flush=True,
            )
            if i + 1 < attempts:
                time.sleep(2 ** (i + 1) + random.random())
    return None


def normalize(df, source, fallback_date=None):
    if df is None or df.empty:
        return pd.DataFrame(columns=COLS)

    required = {"基金代码", "基金份额"}
    if not required.issubset(df.columns):
        print(f"WARNING {source}: unexpected columns {list(df.columns)}")
        return pd.DataFrame(columns=COLS)

    unit = RAW_UNITS.get(source)
    if unit not in ("shares", "10k_shares"):
        raise ValueError(f"Unverified unit for {source}")

    rows = []

    for _, r in df.iterrows():
        code = str(r["基金代码"]).split(".")[0].strip().zfill(6)

        if ETFS.get(code) != source:
            continue

        raw = pd.to_numeric(
            str(r["基金份额"]).replace(",", ""),
            errors="coerce",
        )

        if pd.isna(raw) or raw <= 0:
            continue

        shares_10k = (
            float(raw) / 10000
            if unit == "shares"
            else float(raw)
        )

        raw_date = r.get(
            "统计日期",
            r.get("日期", fallback_date),
        )

        if pd.isna(raw_date):
            raw_date = fallback_date

        date = pd.to_datetime(raw_date, errors="coerce")

        if pd.isna(date):
            continue

        day = date.strftime("%Y-%m-%d")

        rows.append({
            "date": day,
            "code": code,
            "shares_10k": shares_10k,
            "source": source,
        })

    result = pd.DataFrame(rows, columns=COLS)

    if not result.empty:
        print(
            f"INFO {source}: {len(result)} target records; "
            f"raw unit={unit}",
            flush=True,
        )

    return result


def load_old():
    if not OUT.exists():
        return pd.DataFrame(columns=COLS)

    old = pd.read_csv(OUT, dtype={"code": str})

    if not set(COLS).issubset(old.columns):
        raise ValueError("Existing CSV has incompatible columns")

    return old[COLS].copy()


def collect_sse(today):
    batches = []

    for offset in range(1, LOOKBACK_DAYS + 1):
        day = today - dt.timedelta(days=offset)

        if day.weekday() >= 5:
            continue

        daystr = day.strftime("%Y%m%d")

        frame = retry(
            f"SSE {daystr}",
            lambda d=daystr: ak.fund_etf_scale_sse(date=d),
        )

        if frame is not None:
            result = normalize(frame, "SSE", day)

            if not result.empty:
                batches.append(result)

        time.sleep(0.8)

    return batches


def collect_szse(today):
    start = today - dt.timedelta(days=45)

    frame = retry(
        "SZSE",
        lambda: ak.fund_scale_daily_szse(
            start_date=start.strftime("%Y%m%d"),
            end_date=today.strftime("%Y%m%d"),
            symbol="ETF",
        ),
    )

    if frame is None:
        return []

    result = normalize(frame, "SZSE")

    return [result] if not result.empty else []


def main():
    today = dt.datetime.now(TZ).date()

    print(f"ETF collection started: {today}", flush=True)

    old = load_old()

    new = []
    new.extend(collect_sse(today))
    new.extend(collect_szse(today))

    if not new:
        raise RuntimeError(
            "No target ETF records fetched. "
            "Existing CSV preserved."
        )

    incoming = pd.concat(new, ignore_index=True)

    incoming["date"] = pd.to_datetime(
        incoming["date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    incoming = incoming[
        incoming["code"].isin(ETFS)
        & incoming["date"].notna()
    ]

    incoming = incoming[
        incoming["date"] <= today.isoformat()
    ]

    if incoming.empty:
        raise RuntimeError("No valid target ETF observations")

    # Never overwrite an existing observation with a
    # different value without manual reconciliation.
    old_keys = old.copy()

    if not old_keys.empty:
        old_keys["code"] = old_keys["code"].str.zfill(6)
        old_keys["date"] = pd.to_datetime(
            old_keys["date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")

        existing = set(zip(old_keys["date"], old_keys["code"]))

        incoming = incoming[
            ~incoming.apply(
                lambda r: (r["date"], r["code"]) in existing,
                axis=1,
            )
        ]

    merged = pd.concat([old, incoming], ignore_index=True)

    merged["code"] = merged["code"].astype(str).str.zfill(6)
    merged["shares_10k"] = pd.to_numeric(
        merged["shares_10k"], errors="coerce"
    )

    merged = merged[
        merged["code"].isin(ETFS)
        & merged["shares_10k"].gt(0)
    ]

    merged = merged.drop_duplicates(
        ["date", "code"], keep="first"
    ).sort_values(["date", "code"])

    print("\n===== ETF COLLECTION REPORT =====")

    for code in ETFS:
        subset = merged[merged["code"] == code]
        fresh = incoming[incoming["code"] == code]

        if subset.empty:
            print(f"{code}: NO DATA")
            continue

        latest = subset.iloc[-1]

        print(
            f"{code}: latest={latest['date']}, "
            f"shares_10k={latest['shares_10k']:.4f}, "
            f"new_rows={len(fresh)}"
        )

    print(f"New records: {len(incoming)}")
    print(f"Total records: {len(merged)}")

    # Write only after validation.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(".csv.tmp")
    merged.to_csv(temp, index=False, encoding="utf-8")
    temp.replace(OUT)

    print("CSV saved successfully", flush=True)

    missing = [
        code for code in ETFS
        if incoming[incoming["code"] == code].empty
    ]

    if missing:
        print(
            "WARNING: No new observations for: "
            + ", ".join(missing),
            flush=True,
        )


if __name__ == "__main__":
    main()
