"""ETF share collector for GitHub Actions. Collect official exchange-published ETF share observations using AKShare. Store verified observations in data/shares.csv (unit: 10,000 shares). Do not treat missing or stale observations as fresh data. """
import datetime as dt
import pathlib
import random
import re
import time

import pandas as pd

ETFS = {'510300', '510330', '510310', '159919'}
SSE_ETFS = ETFS - {'159919'}
SZSE_ETFS = {'159919'}
OUT = pathlib.Path(__file__).resolve().parent / 'data' / 'shares.csv'
COLS = ['date', 'code', 'shares_10k', 'source']
TZ = dt.timezone(dt.timedelta(hours=8))

# IMPORTANT: Set only after checking exchange/AKShare documentation and sample values.
# The SZSE function's raw '基金份额' is commonly reported in shares (份),
# while the SSE function may report 10k shares (万份). This must be verified.
# Until confirmed, leave a source at None to prevent wrongly scaled imports.
SOURCE_RAW_UNITS = {'SSE': None, 'SZSE': None}


def retry(label, fn, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            print(f'WARNING {label} attempt {attempt}/{attempts}: '
                  f'{type(exc).__name__}: {str(exc)[:240]}', flush=True)
            if attempt < attempts:
                time.sleep(min(15, 2 ** attempt) + random.random())
    return None


def numeric(value):
    try:
        x = float(str(value).replace(',', '').strip())
        return x if pd.notna(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def parse_date(value):
    try:
        parsed = pd.to_datetime(value, errors='coerce')
        if pd.isna(parsed):
            return None
        return parsed.date()
    except (TypeError, ValueError, OverflowError):
        return None


def normalize(frame, source, fallback_date=None):
    if frame is None or frame.empty:
        print(f'INFO {source}: empty response', flush=True)
        return pd.DataFrame(columns=COLS)
    print(f'DIAGNOSTIC {source} columns: {frame.columns.tolist()}', flush=True)
    print(f'DIAGNOSTIC {source} sample:\n{frame.head(3).to_string(index=False)}', flush=True)
    if '基金代码' not in frame.columns or '基金份额' not in frame.columns:
        print(f'WARNING {source}: unexpected column schema; skipping', flush=True)
        return pd.DataFrame(columns=COLS)

    unit = SOURCE_RAW_UNITS[source]
    if unit not in ('shares', '10k_shares'):
        print(f'WARNING {source}: raw share unit not verified; '
              'diagnostics printed, observations NOT imported', flush=True)
        return pd.DataFrame(columns=COLS)

    allowed = SSE_ETFS if source == 'SSE' else SZSE_ETFS
    today = dt.datetime.now(TZ).date()
    rows = []
    for _, row in frame.iterrows():
        raw_code = str(row.get('基金代码', '')).strip().split('.')[0]
        match = re.search(r'(?<!\d)\d{6}(?!\d)', raw_code)
        if not match:
            continue
        code = match.group(0)
        if code not in allowed:
            continue
        value = numeric(row.get('基金份额'))
        if value is None:
            continue
        raw_date = row.get('统计日期', row.get('日期', fallback_date))
        day = parse_date(raw_date)
        if day is None or day > today:
            continue
        shares_10k = value / 10000 if unit == 'shares' else value
        if not 0 < shares_10k < 1e10:
            continue
        rows.append({'date': day.isoformat(), 'code': code,
                     'shares_10k': shares_10k, 'source': source})
    return pd.DataFrame(rows, columns=COLS)


def read_old():
    if not OUT.exists():
        return pd.DataFrame(columns=COLS)
    frame = pd.read_csv(OUT, dtype={'code': str})
    if not set(COLS).issubset(frame.columns):
        raise ValueError('Existing shares.csv schema mismatch; refusing to overwrite')
    return frame[COLS].copy()


def main():
    import akshare as ak
    today = dt.datetime.now(TZ).date()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    old = read_old()
    print(f'INFO Today (Asia/Shanghai): {today}; existing rows: {len(old)}', flush=True)
    print('INFO Verify SOURCE_RAW_UNITS before enabling imports.', flush=True)
    new = []

    # Query the previous 14 calendar days to fill missing SSE observations.
    for offset in range(1, 15):
        day = today - dt.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        label = f'SSE {day:%Y-%m-%d}'
        frame = retry(label, lambda d=day: ak.fund_etf_scale_sse(date=d.strftime('%Y%m%d')))
        if frame is not None:
            data = normalize(frame, 'SSE', day)
            if not data.empty:
                new.append(data)
        time.sleep(0.4)

    # SZSE date-range endpoint. Historical observations can be delayed.
    start = today - dt.timedelta(days=45)
    frame = retry('SZSE', lambda: ak.fund_scale_daily_szse(
        start_date=start.strftime('%Y%m%d'),
        end_date=today.strftime('%Y%m%d'), symbol='ETF'))
    if frame is not None:
        data = normalize(frame, 'SZSE')
        if not data.empty:
            new.append(data)

    # Never rewrite an existing file if no validated observations were fetched.
    if not new:
        raise RuntimeError('No validated ETF share observations fetched. '
                           'Existing CSV unchanged. Review DIAGNOSTIC logs and verify units.')

    merged = pd.concat([old] + new, ignore_index=True)
    merged['date'] = pd.to_datetime(merged['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    merged['code'] = merged['code'].astype(str).str.zfill(6)
    merged['shares_10k'] = pd.to_numeric(merged['shares_10k'], errors='coerce')
    merged = merged[merged['code'].isin(ETFS) & merged['date'].notna()
                    & merged['shares_10k'].gt(0)].copy()
    merged = merged.drop_duplicates(['date', 'code'], keep='last').sort_values(['date', 'code'])
    tmp = OUT.with_suffix('.csv.tmp')
    merged.to_csv(tmp, index=False, encoding='utf-8')
    tmp.replace(OUT)

    print(f'Saved {len(merged)} rows; validated batches {len(new)}', flush=True)
    for code in sorted(ETFS):
        sub = merged[merged['code'] == code]
        if sub.empty:
            print(f'WARNING {code}: no observations', flush=True)
        else:
            latest = sub['date'].max()
            age = (today - dt.date.fromisoformat(latest)).days
            print(f'INFO {code}: latest={latest}, age={age} calendar days', flush=True)
            if age > 5:
                print(f'WARNING {code}: stale observations', flush=True)


if __name__ == '__main__':
    main()