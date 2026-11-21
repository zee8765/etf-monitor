"""Four CSI 300 ETFs: exchange-published share monitoring dashboard."""
import datetime as dt
from io import StringIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ETFS = {
    '510300': '华泰柏瑞沪深300ETF',
    '510330': '华夏沪深300ETF',
    '510310': '易方达沪深300ETF',
    '159919': '嘉实沪深300ETF',
}
LOCAL = Path(__file__).resolve().parent / 'data' / 'shares.csv'
REMOTE = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/shares.csv'
COLUMNS = ['date', 'code', 'shares_10k', 'source']

st.set_page_config(page_title='沪深300 ETF份额监测', layout='wide')
st.title('沪深300 ETF 份额监测中心')
st.caption('跟踪四只沪深300ETF交易所披露的基金份额；不代表中央汇金账户流水或实时净申赎。')

@st.cache_data(ttl=300, show_spinner=False)
def load_remote():
    import requests
    response = requests.get(REMOTE, timeout=12, headers={'Cache-Control': 'no-cache'})
    response.raise_for_status()
    return pd.read_csv(StringIO(response.text), dtype={'code': str})

@st.cache_data(ttl=300, show_spinner=False)
def load_local():
    return pd.read_csv(LOCAL, dtype={'code': str})


def clean(df):
    if not set(COLUMNS).issubset(df.columns):
        raise ValueError('CSV必须包含 date、code、shares_10k、source 四列')
    x = df[COLUMNS].copy()
    x['date'] = pd.to_datetime(x['date'], errors='coerce').dt.normalize()
    x['code'] = x['code'].astype(str).str.strip().str.zfill(6)
    x['shares_10k'] = pd.to_numeric(x['shares_10k'], errors='coerce')
    x = x[x['code'].isin(ETFS) & x['date'].notna() & x['shares_10k'].gt(0)].copy()
    x = x[x['date'] <= pd.Timestamp.now(tz='Asia/Shanghai').tz_localize(None).normalize()]
    x = x.drop_duplicates(['date', 'code'], keep='last').sort_values(['code', 'date'])
    return x.reset_index(drop=True)

with st.sidebar:
    st.header('数据设置')
    mode = st.radio('数据来源', ['GitHub自动采集', '本地CSV', '上传CSV'], index=0)
    upload = st.file_uploader('上传CSV', type='csv') if mode == '上传CSV' else None
    if st.button('刷新数据'):
        load_remote.clear()
        load_local.clear()
        st.rerun()
    st.caption('自动采集文件：data/shares.csv；数据单位统一为万份。')

try:
    if mode == 'GitHub自动采集':
        raw = load_remote()
    elif mode == '本地CSV':
        raw = load_local()
    else:
        if upload is None:
            st.info('请先上传CSV文件。')
            st.stop()
        raw = pd.read_csv(upload, dtype={'code': str})
    data = clean(raw)
except Exception as exc:
    st.error(f'数据读取失败：{exc}')
    st.info('检查GitHub仓库的 data/shares.csv 是否已提交，或切换本地/上传CSV。')
    st.stop()

if data.empty:
    st.warning('CSV中没有有效的四只目标ETF份额记录。')
    st.stop()

latest_date = data['date'].max()
today = pd.Timestamp.now(tz='Asia/Shanghai').tz_localize(None).normalize()
lag = (today - latest_date).days
st.caption(f'最新份额统计日：{latest_date:%Y-%m-%d} · 数据记录：{len(data)}条 · 数据来源：{mode}')
if lag > 5:
    st.warning(f'最新份额数据距今已有{lag}个自然日，请检查GitHub Actions。')

with st.sidebar:
    codes = st.multiselect('选择ETF', list(ETFS), default=list(ETFS), format_func=lambda x: f'{x} {ETFS[x]}')
    display_days = st.slider('趋势图显示最近自然日', 7, 180, 60)

if not codes:
    st.info('请至少选择一只ETF。')
    st.stop()

selected = data[data['code'].isin(codes)].copy()
selected['ETF'] = selected['code'].map(ETFS)
selected['prev_date'] = selected.groupby('code')['date'].shift(1)
selected['prev_shares'] = selected.groupby('code')['shares_10k'].shift(1)
selected['change_10k'] = selected['shares_10k'] - selected['prev_shares']
selected['change_pct'] = selected['change_10k'] / selected['prev_shares'] * 100
selected['gap_days'] = (selected['date'] - selected['prev_date']).dt.days

st.subheader('最新份额概览')
latest = selected.groupby('code', sort=False).tail(1).copy()
cols = st.columns(len(latest))
for col, (_, row) in zip(cols, latest.iterrows()):
    with col:
        delta = None if pd.isna(row['change_10k']) else f"{row['change_10k']:+,.2f} 万份"
        st.metric(f"{row['code']} {ETFS[row['code']]}", f"{row['shares_10k']:,.2f} 万份", delta=delta)
        st.caption(f"统计日 {row['date']:%m-%d}" + (f"；距上次记录{int(row['gap_days'])}天" if pd.notna(row['gap_days']) else ''))

st.caption('卡片中的增减是与该基金上一条有效记录相比；如中间缺少交易日，不代表单日变化。')

st.subheader('最新数据明细')
view = latest[['date','code','ETF','shares_10k','change_10k','change_pct','gap_days','source']].copy()
view.columns = ['统计日期','代码','ETF','份额（万份）','较上次变化（万份）','变化率（%）','相隔自然日','来源']
st.dataframe(view, hide_index=True, use_container_width=True, column_config={'统计日期': st.column_config.DateColumn(format='YYYY-MM-DD')})

st.subheader('份额变化趋势')
recent = selected[selected['date'] >= latest_date - pd.Timedelta(days=display_days)].copy()
fig = px.line(recent, x='date', y='shares_10k', color='ETF', markers=True,
              labels={'date':'统计日期','shares_10k':'基金份额（万份）','ETF':'基金'})
fig.update_layout(hovermode='x unified')
st.plotly_chart(fig, use_container_width=True)

st.subheader('各ETF多周期变化')
periods = [1, 5, 10, 20]
rows = []
for code in codes:
    part = selected[selected['code'] == code].sort_values('date')
    last = part.iloc[-1]
    item = {'代码':code, 'ETF':ETFS[code], '最新日期':last['date'].date().isoformat()}
    for n in periods:
        # Compare with the observation at least n calendar days earlier;
        # label explicitly so this is not mistaken for n trading sessions.
        target = last['date'] - pd.Timedelta(days=n)
        older = part[part['date'] <= target]
        if older.empty:
            item[f'{n}自然日变化（万份）'] = None
            item[f'{n}自然日变化率（%）'] = None
        else:
            base = older.iloc[-1]['shares_10k']
            item[f'{n}自然日变化（万份）'] = round(last['shares_10k'] - base, 2)
            item[f'{n}自然日变化率（%）'] = round((last['shares_10k'] / base - 1)*100, 2)
    rows.append(item)
period_table = pd.DataFrame(rows)
st.dataframe(period_table, hide_index=True, use_container_width=True)
st.caption('这里的1/5/10/20是自然日回看窗口，不是交易日；使用窗口起点当日或之前最近一条有效观测。历史不足时留空。')

st.subheader('四只ETF合计份额')
# Summing share counts is arithmetically valid, but not equivalent to RMB flows.
pivot = data.pivot(index='date', columns='code', values='shares_10k')
complete = pivot.dropna(subset=list(ETFS))
if len(complete):
    total = complete[list(ETFS)].sum(axis=1).rename('合计份额（万份）').reset_index()
    st.metric('最新四只合计（仅完整共同日期）', f"{total.iloc[-1,1]:,.2f} 万份")
    st.caption(f"合计对应日期：{total.iloc[-1,0]:%Y-%m-%d}。四只ETF都在该日有数据时才计算，避免混用不同日期。")
    fig_total = px.line(total, x='date', y='合计份额（万份）', markers=True, labels={'date':'统计日期'})
    st.plotly_chart(fig_total, use_container_width=True)
else:
    st.info('目前没有四只ETF在同一日期的完整数据，暂不计算合计。')

st.subheader('数据完整性')
coverage = []
for code in ETFS:
    p = data[data['code'] == code]
    coverage.append({'代码':code, 'ETF':ETFS[code], '记录数':len(p),
                     '最早日期':p['date'].min().date().isoformat() if len(p) else '—',
                     '最新日期':p['date'].max().date().isoformat() if len(p) else '—'})
st.dataframe(pd.DataFrame(coverage), hide_index=True, use_container_width=True)

st.subheader('导出数据')
st.download_button('下载清洗后的份额历史CSV', data.to_csv(index=False).encode('utf-8-sig'),
                   file_name='etf_shares_history.csv', mime='text/csv')

st.divider()
st.info('重要：份额增加/减少只是ETF申购赎回的代理线索，不能识别交易主体。当前没有按统计日期匹配的基金净值，因此不计算人民币净流入或国家队评分。行情价格、指数涨跌与实际持仓需另行接入并校验。')