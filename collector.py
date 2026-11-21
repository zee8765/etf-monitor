"""Daily best-effort ETF shares collector; intended for GitHub Actions."""
import datetime as dt
import pathlib
import pandas as pd

ETFS={'510300','510330','510310','159919'}
OUT=pathlib.Path(__file__).parent/'data'/'shares.csv'
COLS=['date','code','shares_10k','source']

def normalize(df, source, date=None):
    rows=[]
    for _,r in df.iterrows():
        code=str(r.get('基金代码','')).split('.')[0].strip().zfill(6)
        if code not in ETFS: continue
        raw=r.get('基金份额')
        try: val=float(str(raw).replace(',',''))
        except (TypeError,ValueError): continue
        if not (0<val<1e10): continue
        rawdate=r.get('统计日期',r.get('日期',date))
        try: day=pd.to_datetime(rawdate).strftime('%Y-%m-%d')
        except Exception: continue
        rows.append({'date':day,'code':code,'shares_10k':val,'source':source})
    return pd.DataFrame(rows,columns=COLS)

def main():
    import akshare as ak
    today=dt.date.today()
    new=[]; errors=[]
    # Retrieve last 8 calendar days, allowing delayed official publication.
    for offset in range(1,9):
        day=today-dt.timedelta(days=offset)
        if day.weekday()>4: continue
        try:
            x=normalize(ak.fund_etf_scale_sse(date=day.strftime('%Y%m%d')),'SSE',day)
            if not x.empty: new.append(x)
        except Exception as e: errors.append(f'SSE {day}: {type(e).__name__}: {str(e)[:120]}')
    try:
        start=today-dt.timedelta(days=30)
        x=normalize(ak.fund_scale_daily_szse(start_date=start.strftime('%Y%m%d'),end_date=today.strftime('%Y%m%d'),symbol='ETF'),'SZSE')
        if not x.empty: new.append(x)
    except Exception as e: errors.append(f'SZSE: {type(e).__name__}: {str(e)[:120]}')
    OUT.parent.mkdir(exist_ok=True)
    old=pd.read_csv(OUT,dtype={'code':str}) if OUT.exists() else pd.DataFrame(columns=COLS)
    merged=pd.concat([old]+new,ignore_index=True)
    if not merged.empty:
        merged['date']=pd.to_datetime(merged['date'],errors='coerce').dt.strftime('%Y-%m-%d')
        merged['code']=merged['code'].astype(str).str.zfill(6)
        merged['shares_10k']=pd.to_numeric(merged['shares_10k'],errors='coerce')
        merged=merged[merged['code'].isin(ETFS)&merged['shares_10k'].gt(0)&merged['date'].notna()]
        merged=merged.drop_duplicates(['date','code'],keep='last').sort_values(['date','code'])
    merged.to_csv(OUT,index=False,encoding='utf-8')
    print(f'Saved {len(merged)} records; new batches {len(new)}')
    for e in errors: print('WARNING',e)
    if not new: print('WARNING: No new data from official endpoints. Existing data preserved; not claiming success.')

if __name__=='__main__': main()
