"""Best-effort official ETF share collector for GitHub Actions."""
import datetime as dt
import pathlib
import random
import time

import pandas as pd

ETFS = {'510300', '510330', '510310', '159919'}
OUT = pathlib.Path(__file__).parent / 'data' / 'shares.csv'
COLS = ['date', 'code', 'shares_10k', 'source']


def normalize(df, source, date=None):
    rows = []
    for _, r in df.iterrows():
        code = str(r.get('基金代码', '')).split('.')[0].strip().zfill(6)
        if code not in ETFS:
            continue
        try:
            val = float(str(r.get('基金份额')).replace(',', ''))
        except (TypeError, ValueError):
            continue
        if not (0 < val < 1e10):
            continue
        rawdate = r.get('统计日期', r.get('日期', date))
        try:
            day = pd.to_datetime(rawdate).strftime('%Y-%m-%d')
        except (TypeError, ValueError):
            continue
        if day == 'NaT':
            continue
        rows.append({'date': day, 'code': code, 'shares_10k': val, 'source': source})
    return pd.DataFrame(rows, columns=COLS)


def retry(label, func, attempts=3):
    for i in range(attempts):
        try:
            return func()
        except Exception as exc:
            print(f'WARNING {label} attempt {i + 1}/{attempts}: {type(exc).__name__}: {str(exc)[:180]}', flush=True)
            if i + 1 < attempts:
                time.sleep(min(12, 2 ** i * 2) + random.random())
    return None


def main():
    import akshare as ak
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(OUT, dtype={'code': str}) if OUT.exists() else pd.DataFrame(columns=COLS)
    new = []
    # Avoid repeat-fetching dates already in history; retry only recent missing dates.
    seen = set()
    if not old.empty and {'date', 'code'}.issubset(old.columns):
        seen = set(zip(old['date'].astype(str), old['code'].astype(str).str.zfill(6)))
    for offset in range(1, 9):
        day = today - dt.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        daystr = day.strftime('%Y-%m-%d')
        if all((daystr, code) in seen for code in ('510300', '510330', '510310')):
            continue
        frame = retry(f'SSE {daystr}', lambda d=day: ak.fund_etf_scale_sse(date=d.strftime('%Y%m%d')))
        if frame is not None:
            normalized = normalize(frame, 'SSE', day)
            if not normalized.empty:
                new.append(normalized)
        time.sleep(1)
    start = today - dt.timedelta(days=30)
    frame = retry('SZSE', lambda: ak.fund_scale_daily_szse(
        start_date=start.strftime('%Y%m%d'), end_date=today.strftime('%Y%m%d'), symbol='ETF'))
    if frame is not None:
        normalized = normalize(frame, 'SZSE')
        if not normalized.empty:
            new.append(normalized)

    merged = pd.concat([old] + new, ignore_index=True)
    if not merged.empty:
        merged['date'] = pd.to_datetime(merged['date'], errors='coerce').dt.strftime('%Y-%m-%d')
        merged['code'] = merged['code'].astype(str).str.zfill(6)
        merged['shares_10k'] = pd.to_numeric(merged['shares_10k'], errors='coerce')
        merged = merged[merged['code'].isin(ETFS) & merged['shares_10k'].gt(0) & merged['date'].notna()]
        merged = merged.drop_duplicates(['date', 'code'], keep='last').sort_values(['date', 'code'])
    merged.to_csv(OUT, index=False, encoding='utf-8')
    added = len(merged) - len(old)
    print(f'Saved {len(merged)} records; fetched batches {len(new)}; net row change {added}', flush=True)
    if not new:
        raise RuntimeError('No ETF shares returned from official endpoints; existing CSV preserved. Check endpoint connectivity and field schema.')


if __name__ == '__main__':
    main()