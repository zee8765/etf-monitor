"""CSI300: collect 4 ETF market values and CSI300 close.

No unverified denominator is fabricated. Supply verified data/float_cap_verified.csv
(date,csi300_float_cap_yi) to publish data/etf_market_ratio.csv.
"""
from pathlib import Path
import datetime as dt
import time
import pandas as pd
import akshare as ak

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
CODES = ('510300', '510330', '510310', '159919')
START = '20261001'  # Existing shares.csv begins in October 2026.


def get_prices(code, end):
    last_error = None
    for attempt in range(3):
        try:
            df = ak.fund_etf_hist_em(symbol=code, period='daily', start_date=START,
                                     end_date=end, adjust='')
            if df is None or df.empty or not {'日期', '收盘'}.issubset(df.columns):
                raise ValueError(f'{code}: empty/unexpected ETF price data')
            out = df[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'close'}).copy()
            out['date'] = pd.to_datetime(out['date'], errors='coerce').dt.normalize()
            out['close'] = pd.to_numeric(out['close'], errors='coerce')
            out = out.dropna().query('close > 0').drop_duplicates('date', keep='last')
            if out.empty:
                raise ValueError(f'{code}: no valid prices')
            return out
        except Exception as e:
            last_error = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f'ETF {code} price request failed: {last_error}')


def get_index(end):
    last_error = None
    for attempt in range(3):
        try:
            df = ak.index_zh_a_hist(symbol='000300', period='daily',
                                    start_date=START, end_date=end)
            if df is None or df.empty or not {'日期', '收盘'}.issubset(df.columns):
                raise ValueError('CSI300 index empty/unexpected')
            out = df[['日期', '收盘']].rename(columns={'日期': 'date', '收盘': 'csi300_close'}).copy()
            out['date'] = pd.to_datetime(out['date'], errors='coerce').dt.normalize()
            out['csi300_close'] = pd.to_numeric(out['csi300_close'], errors='coerce')
            out = out.dropna().query('csi300_close > 0').drop_duplicates('date', keep='last')
            if out.empty:
                raise ValueError('No valid index closes')
            return out
        except Exception as e:
            last_error = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f'CSI300 index request failed: {last_error}')


def main():
    shares_file = DATA / 'shares.csv'
    shares = pd.read_csv(shares_file, dtype={'code': str})
    needed = {'date', 'code', 'shares_10k'}
    if not needed.issubset(shares.columns):
        raise ValueError('shares.csv missing columns')
    shares['date'] = pd.to_datetime(shares['date'], errors='coerce').dt.normalize()
    shares['code'] = shares['code'].astype(str).str.zfill(6)
    shares['shares_10k'] = pd.to_numeric(shares['shares_10k'], errors='coerce')
    shares = shares[shares['code'].isin(CODES) & shares['shares_10k'].between(1, 1e8)].copy()
    if shares.duplicated(['date', 'code']).any():
        raise ValueError('Duplicate shares rows: review original data')
    end = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime('%Y%m%d')
    prices = []
    for code in CODES:
        p = get_prices(code, end)
        p['code'] = code
        prices.append(p)
        time.sleep(.5)
    prices = pd.concat(prices, ignore_index=True)
    merged = shares.merge(prices, on=['date', 'code'], how='inner', validate='one_to_one')
    # 10k shares * yuan/share / 10k = 100 million yuan.
    merged['market_cap_yi'] = merged['shares_10k'] * merged['close'] / 10000
    wide = merged.pivot(index='date', columns='code', values='market_cap_yi')
    wide = wide.dropna(subset=list(CODES))
    if wide.empty:
        raise RuntimeError('No dates with all 4 ETF shares and prices')
    aggregate = wide[list(CODES)].sum(axis=1).rename('etf_market_cap_yi').reset_index()
    index = get_index(end)
    partial = aggregate.merge(index, on='date', how='inner', validate='one_to_one')
    if partial.empty:
        raise RuntimeError('No same-date index and ETF market-cap observations')
    DATA.mkdir(exist_ok=True)
    partial['date'] = partial['date'].dt.strftime('%Y-%m-%d')
    partial.to_csv(DATA / 'etf_market_components.csv', index=False)
    print(f'Saved {len(partial)} verified-date ETF value/index observations')

    denominator = DATA / 'float_cap_verified.csv'
    if not denominator.exists():
        print('NOTICE: data/float_cap_verified.csv missing. Ratio is NOT published.')
        return
    cap = pd.read_csv(denominator)
    if not {'date', 'csi300_float_cap_yi'}.issubset(cap.columns):
        raise ValueError('float_cap_verified.csv requires date,csi300_float_cap_yi')
    cap['date'] = pd.to_datetime(cap['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    cap['csi300_float_cap_yi'] = pd.to_numeric(cap['csi300_float_cap_yi'], errors='coerce')
    if cap['date'].isna().any() or cap['date'].duplicated().any():
        raise ValueError('Invalid or duplicated float-cap dates')
    if cap['csi300_float_cap_yi'].isna().any() or (cap['csi300_float_cap_yi'] <= 0).any():
        raise ValueError('Invalid float-cap value')
    result = partial.merge(cap[['date', 'csi300_float_cap_yi']], on='date', how='inner', validate='one_to_one')
    if result.empty:
        print('NOTICE: no matching verified denominator dates; ratio not published.')
        return
    result['ratio_pct'] = result['etf_market_cap_yi'] / result['csi300_float_cap_yi'] * 100
    if (~result['ratio_pct'].between(0, 100, inclusive='neither')).any():
        raise ValueError('Ratio out of range; check market-cap units')
    result = result[['date', 'etf_market_cap_yi', 'csi300_float_cap_yi', 'csi300_close']]
    result.to_csv(DATA / 'etf_market_ratio.csv', index=False)
    print(f'Saved {len(result)} fully verified ratio rows')


if __name__ == '__main__':
    main()
