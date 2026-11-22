"""CSI300: collect 4 ETF market values and CSI300 close. No unverified denominator is fabricated. Supply verified data/float_cap_verified.csv (date,csi300_float_cap_yi) to publish data/etf_market_ratio.csv. """
from pathlib import Path
import datetime as dt
import time
import pandas as pd
import akshare as ak

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
CODES = ('510300', '510330', '510310', '159919')
START = '20240101'  # Collect full CSI300 history; ETF market value still requires observed shares.


def _clean_history(df, value_column, output_column, code, end):
    if df is None or df.empty:
        raise ValueError(f'{code}: empty historical data')
    date_col = next((c for c in ('date', '日期') if c in df.columns), None)
    close_col = next((c for c in ('close', '收盘') if c in df.columns), None)
    if not date_col or not close_col:
        raise ValueError(f'{code}: unexpected columns {list(df.columns)}')
    out = df[[date_col, close_col]].rename(
        columns={date_col: 'date', close_col: output_column}
    ).copy()
    out['date'] = pd.to_datetime(out['date'], errors='coerce').dt.normalize()
    out[output_column] = pd.to_numeric(out[output_column], errors='coerce')
    out = out.dropna()
    out = out[out[output_column] > 0].drop_duplicates('date', keep='last')
    start = pd.to_datetime(START, format='%Y%m%d')
    finish = pd.to_datetime(end, format='%Y%m%d')
    out = out[out['date'].between(start, finish)]
    if out.empty:
        raise ValueError(f'{code}: no valid prices within date range')
    return out


def get_prices(code, end):
    # Sina history does not use Eastmoney's rate-limited push2 endpoint.
    symbol = ('sh' if code.startswith('5') else 'sz') + code
    errors = []
    for provider, loader in (
        ('Sina', lambda: ak.fund_etf_hist_sina(symbol=symbol)),
        ('Eastmoney fallback', lambda: ak.fund_etf_hist_em(
            symbol=code, period='daily', start_date=START,
            end_date=end, adjust='')),
    ):
        try:
            out = _clean_history(loader(), 'close', 'close', code, end)
            print(f'INFO {code} ETF prices: {provider}, {len(out)} rows', flush=True)
            return out
        except Exception as exc:
            errors.append(f'{provider}: {type(exc).__name__}: {exc}')
            print(f'WARNING {code} {errors[-1]}', flush=True)
            time.sleep(2)
    raise RuntimeError(f'ETF {code} price providers failed: ' + ' | '.join(errors))


def get_index(end):
    errors = []
    for provider, loader in (
        ('Sina', lambda: ak.index_zh_daily_sina(symbol='sh000300')),
        ('Eastmoney fallback', lambda: ak.index_zh_hist_em(
            symbol='000300', period='daily', start_date=START,
            end_date=end)),
    ):
        try:
            out = _clean_history(loader(), 'close', 'csi300_close', 'CSI300', end)
            print(f'INFO CSI300 index: {provider}, {len(out)} rows', flush=True)
            return out
        except Exception as exc:
            errors.append(f'{provider}: {type(exc).__name__}: {exc}')
            print(f'WARNING CSI300 {errors[-1]}', flush=True)
            time.sleep(2)
    raise RuntimeError('CSI300 index providers failed: ' + ' | '.join(errors))


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
    DATA.mkdir(exist_ok=True)
    index_export = index.copy()
    index_export['date'] = index_export['date'].dt.strftime('%Y-%m-%d')
    index_export.to_csv(DATA / 'csi300_index_history.csv', index=False)
    print(f'Saved {len(index_export)} CSI300 index history observations')
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