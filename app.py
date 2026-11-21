import os, sqlite3, datetime as dt
import pandas as pd
import streamlit as st
import plotly.express as px

DB=os.getenv('ETF_DB','etf_monitor.sqlite3')
ETFS={'510300':'华泰柏瑞沪深300','510330':'华夏沪深300','159919':'嘉实沪深300','510310':'易方达沪深300'}

def conn():
    c=sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS shares (date TEXT, code TEXT, shares REAL, source TEXT, fetched_at TEXT, PRIMARY KEY(date,code))')
    return c

def store(frame):
    with conn() as c:
        for r in frame.to_dict('records'):
            c.execute('INSERT OR REPLACE INTO shares VALUES (?,?,?,?,?)',(r['date'],r['code'],r['shares'],r['source'],dt.datetime.now().isoformat(timespec='seconds')))

def history():
    with conn() as c: return pd.read_sql_query('SELECT date,code,shares,source FROM shares ORDER BY date',c)

def num(v):
    try: return float(str(v).replace(',',''))
    except (ValueError,TypeError): return None

def normalize(df,source,date=None):
    rows=[]
    for _,r in df.iterrows():
        code=str(r.get('基金代码','')).strip().split('.')[0].zfill(6)
        if code not in ETFS: continue
        value=num(r.get('基金份额'))
        if value is None or value<=0: continue
        raw_date=str(r.get('统计日期',r.get('日期',date or ''))).strip()
        try: day=pd.to_datetime(raw_date).strftime('%Y-%m-%d')
        except Exception: continue
        rows.append(dict(date=day,code=code,shares=value,source=source))
    return pd.DataFrame(rows,columns=['date','code','shares','source'])

@st.cache_data(ttl=60,show_spinner=False)
def eastmoney_quotes():
    import akshare as ak
    df=ak.fund_etf_spot_em()
    if '代码' not in df.columns:
        raise ValueError('行情返回格式不符合预期')
    df['代码']=df['代码'].astype(str).str.zfill(6)
    df=df[df['代码'].isin(ETFS)].copy()
    if df.empty:
        raise ValueError('行情返回为空')
    df['行情来源']='东方财富（AKShare）'
    return df

@st.cache_data(ttl=60,show_spinner=False)
def sina_quotes():
    # 备用公开网页行情接口，可能被限流或禁用；仅返回行情，不返回申赎份额。
    import urllib.request, re
    codes=[('sh' if c.startswith(('5','6')) else 'sz')+c for c in ETFS]
    url='https://hq.sinajs.cn/list='+','.join(codes)
    req=urllib.request.Request(url,headers={'Referer':'https://finance.sina.com.cn/', 'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=9) as response:
        body=response.read().decode('gbk',errors='replace')
    rows=[]
    for line in body.splitlines():
        match=re.search(r'var hq_str_(?:sh|sz)(\d{6})="([^"]*)"',line)
        if not match or match.group(1) not in ETFS: continue
        code,raw=match.groups(); values=raw.split(',')
        if len(values)<32: continue
        try:
            prev=float(values[2]);price=float(values[3])
            if prev<=0 or price<=0: continue
            rows.append({'代码':code,'名称':ETFS[code], '最新价':price,
                         '涨跌幅':round((price/prev-1)*100,3),
                         '成交额':float(values[9]) if values[9] else None,
                         '数据日期':values[30]+' '+values[31],
                         '行情来源':'新浪公开行情（备用）'})
        except (ValueError,IndexError): continue
    if not rows: raise ValueError('备用行情未返回有效数据')
    return pd.DataFrame(rows)

def quotes():
    try:
        return eastmoney_quotes(),None
    except Exception:
        try:
            return sina_quotes(),'东方财富接口不可用，已切换至新浪备用行情。'
        except Exception:
            return pd.DataFrame(),'东方财富和新浪行情接口暂时均不可用，请稍后重试。'

@st.cache_data(ttl=3600,show_spinner=False)
def sse(day):
    import akshare as ak
    return normalize(ak.fund_etf_scale_sse(date=day.strftime('%Y%m%d')),'SSE',day)

@st.cache_data(ttl=3600,show_spinner=False)
def szse(start,end):
    import akshare as ak
    return normalize(ak.fund_scale_daily_szse(start_date=start.strftime('%Y%m%d'),end_date=end.strftime('%Y%m%d'),symbol='ETF'),'SZSE')

st.set_page_config(page_title='国家队ETF监测',layout='wide')
st.title('国家队 ETF 资金监测中心')
st.caption('公开ETF申赎代理指标；不是中央汇金真实账户流水。行情为尽力获取的公开报价，可能延迟或不可用。')
with st.sidebar:
    st.header('数据采集')
    day=st.date_input('上交所份额统计日期',value=dt.date.today()-dt.timedelta(days=1))
    if st.button('获取上交所当日份额'):
        try:
            x=sse(day); store(x); st.success(f'保存 {len(x)} 条（若为0请检查日期/接口）')
        except Exception as e: st.error(f'上交所获取失败：{e}')
    start=st.date_input('深交所开始日期',value=dt.date.today()-dt.timedelta(days=7))
    end=st.date_input('深交所结束日期',value=dt.date.today())
    if st.button('获取深交所份额区间'):
        try:
            if (end-start).days>180: st.error('深交所单次最多约6个月')
            else:
                x=szse(start,end);store(x);st.success(f'保存 {len(x)} 条')
        except Exception as e: st.error(f'深交所获取失败：{e}')
    st.divider()
    uploaded=st.file_uploader('导入份额CSV（date,code,shares）',type='csv')
    if uploaded and st.button('导入CSV'):
        try:
            x=pd.read_csv(uploaded,dtype={'code':str});x['code']=x['code'].str.zfill(6)
            assert {'date','code','shares'}.issubset(x.columns)
            x=x[x['code'].isin(ETFS)].copy();x['date']=pd.to_datetime(x['date']).dt.strftime('%Y-%m-%d');x['shares']=pd.to_numeric(x['shares']);x=x[x['shares']>0]
            x['source']='CSV';store(x);st.success(f'导入 {len(x)} 条')
        except Exception as e: st.error(f'CSV错误：{e}')
    st.caption('上交所数据需逐日拉取；深交所支持日期区间。请先收集至少两个可比交易日。')

st.subheader('盘中行情（60秒缓存，手动刷新页面）')
q,notice=quotes()
if notice: st.warning(notice)
if not q.empty:
    fields=[c for c in ['代码','名称','最新价','涨跌幅','成交额','数据日期','行情来源'] if c in q.columns]
    st.dataframe(q[fields],hide_index=True,use_container_width=True)
    st.caption('新浪备用行情的成交额字段按接口原始口径展示；可能延迟。成交额不是ETF净申赎。')
else:
    st.info('当前无可用报价，份额历史与CSV功能仍可使用。')

h=history()
st.subheader('ETF份额及净申赎代理')
if h.empty:
    st.info('暂无份额历史。先在左侧抓取交易所数据，或导入CSV。')
else:
    h['date']=pd.to_datetime(h['date']);h=h.sort_values(['code','date'])
    h['prev_shares']=h.groupby('code')['shares'].shift()
    h['delta_shares']=h['shares']-h['prev_shares']
    h['pct_change']=100*h['delta_shares']/h['prev_shares']
    h['name']=h['code'].map(ETFS)
    latest=h.sort_values('date').groupby('code').tail(1).copy()
    st.dataframe(latest[['date','code','name','shares','delta_shares','pct_change','source']],hide_index=True,use_container_width=True)
    fig=px.line(h,x='date',y='shares',color='name',markers=True,title='四只ETF份额变化（交易所原始单位；各交易所单位可能不同）')
    st.plotly_chart(fig,use_container_width=True)
    st.warning('注意：上交所/深交所接口的份额计量单位可能不同，不能直接跨市场求和。仅在同一基金、同一来源及一致单位下计算份额变化。')
    st.markdown('**净申赎金额估算**：`(当日份额 − 前日份额) × 当日基金单位净值`。当前版本未自动接入与份额日期对齐的正式净值，故不输出人民币净申赎金额，也不计算未经校准的国家队评分。')
    st.download_button('导出份额历史CSV',h.to_csv(index=False).encode('utf-8-sig'),'etf_shares.csv','text/csv')

st.divider()
st.markdown('**解读规则**：指数下跌 + 多只ETF份额同步增长 → 疑似逆势承接；指数上涨 + 多只ETF份额同步下降 → 疑似赎回。必须结合实际份额披露日期、净值与汇金定期持仓验证，不可认定为国家队买卖。')
