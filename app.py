"""CSI 300 ETF share monitor V2. Uses exchange share observations (10k shares)."""
import datetime as dt
from io import StringIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ETFS = {'510300': '华泰柏瑞沪深300ETF', '510330': '华夏沪深300ETF',
        '510310': '易方达沪深300ETF', '159919': '嘉实沪深300ETF'}
LOCAL = Path(__file__).resolve().parent / 'data' / 'shares.csv'
REMOTE = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/shares.csv'
COLS = {'date', 'code', 'shares_10k', 'source'}
TODAY = pd.Timestamp.now(tz='Asia/Shanghai').tz_localize(None).normalize()

st.set_page_config(page_title='沪深300 ETF资金观察', layout='wide', initial_sidebar_state='collapsed')
st.title('沪深300 ETF资金观察')
st.caption('四只沪深300ETF · 交易所披露份额（万份） · 不代表中央汇金交易流水')

@st.cache_data(ttl=300, show_spinner=False)
def remote_csv():
    import requests
    r = requests.get(REMOTE, timeout=15, headers={'Cache-Control': 'no-cache'})
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text), dtype={'code': str})

@st.cache_data(ttl=300, show_spinner=False)
def local_csv():
    return pd.read_csv(LOCAL, dtype={'code': str})


def prepare(raw):
    if not COLS.issubset(raw.columns):
        raise ValueError('缺少 date、code、shares_10k、source 字段')
    d = raw[list(sorted(COLS))].copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce').dt.normalize()
    d['code'] = d['code'].astype(str).str.strip().str.zfill(6)
    d['shares_10k'] = pd.to_numeric(d['shares_10k'], errors='coerce')
    d = d[d['code'].isin(ETFS) & d['date'].notna() &
          d['shares_10k'].gt(0) & d['date'].le(TODAY)].copy()
    # Reject grossly implausible legacy unit mistakes; do not silently rescale.
    suspect = d['shares_10k'].gt(1e8)
    if suspect.any():
        st.warning(f'已隔离 {int(suspect.sum())} 条疑似单位错误记录（超过1亿万份），请核对原始CSV。')
        d = d[~suspect].copy()
    d = d.drop_duplicates(['date', 'code'], keep='last').sort_values(['code', 'date'])
    return d.reset_index(drop=True)

with st.sidebar:
    st.header('设置')
    mode = st.radio('份额数据来源', ['GitHub自动采集', '仓库本地CSV', '上传CSV'])
    uploaded = st.file_uploader('上传CSV', type='csv') if mode == '上传CSV' else None
    if st.button('立即刷新'):
        remote_csv.clear()
        local_csv.clear()
        st.rerun()

try:
    if mode == 'GitHub自动采集':
        raw = remote_csv()
    elif mode == '仓库本地CSV':
        raw = local_csv()
    else:
        if uploaded is None:
            st.info('请先上传CSV')
            st.stop()
        raw = pd.read_csv(uploaded, dtype={'code': str})
    d = prepare(raw)
except Exception as exc:
    st.error(f'读取失败：{exc}')
    st.stop()
if d.empty:
    st.warning('没有有效份额数据。')
    st.stop()

max_date = d['date'].max()
st.caption(f'最新披露日期：{max_date:%Y-%m-%d} ｜ {len(d)}条记录 ｜ 数据：{mode}')
if (TODAY - max_date).days > 5:
    st.warning('最新数据超过5个自然日，请检查采集任务和交易所披露情况。')

codes = st.multiselect('监测ETF', list(ETFS), default=list(ETFS),
                       format_func=lambda c: f'{c} {ETFS[c]}')
period = st.select_slider('图表时间范围（自然日）', options=[7, 14, 30, 60, 90, 180, 365], value=60,
                          format_func=lambda n: f'{n}日')
if not codes:
    st.info('请至少选择一只ETF。')
    st.stop()

# All metrics computed on the full history, never on chart-filtered rows.
d['name'] = d['code'].map(ETFS)
d['prev_date'] = d.groupby('code')['date'].shift(1)
d['prev_shares'] = d.groupby('code')['shares_10k'].shift(1)
d['delta_10k'] = d['shares_10k'] - d['prev_shares']
d['delta_pct'] = d['delta_10k'] / d['prev_shares'] * 100
d['gap_days'] = (d['date'] - d['prev_date']).dt.days

# Period comparison: latest observation at or before cutoff; indicate missing baselines.
def compare(sub, n):
    last = sub.iloc[-1]
    base = sub[sub['date'] <= last['date'] - pd.Timedelta(days=n)]
    if base.empty:
        return None
    b = base.iloc[-1]
    return last['shares_10k'] - b['shares_10k'], (last['shares_10k'] / b['shares_10k'] - 1) * 100, b['date']

selected = d[d['code'].isin(codes)].copy()
latest = selected.groupby('code', sort=False).tail(1).copy()
rows = []
for _, r in latest.iterrows():
    sub = selected[selected['code'] == r['code']]
    row = {'代码': r['code'], 'ETF': r['name'], '最新日期': r['date'].strftime('%Y-%m-%d'),
           '份额(万份)': r['shares_10k'], '上次变化(万份)': r['delta_10k'],
           '上次变化(%)': r['delta_pct'], '间隔(自然日)': r['gap_days']}
    for days in [5, 10, 20]:
        result = compare(sub, days)
        row[f'{days}日变化(万份)'] = result[0] if result else None
        row[f'{days}日变化(%)'] = result[1] if result else None
    rows.append(row)
summary = pd.DataFrame(rows)

st.subheader('最新份额与多周期变化')
st.dataframe(summary, hide_index=True, use_container_width=True,
             column_config={c: st.column_config.NumberColumn(c, format='%.2f')
                            for c in summary.columns if '(万份)' in c or '(%)' in c})
st.caption('5/10/20日为自然日回看：与截止日前最近一次可用观测比较，不保证恰好5/10/20个交易日。')

# Aggregate only on dates where all four ETFs have a published observation.
wide = d.pivot_table(index='date', columns='code', values='shares_10k', aggfunc='last')
complete = wide.dropna(subset=list(ETFS)) if set(ETFS).issubset(wide.columns) else pd.DataFrame()
if not complete.empty:
    complete = complete.copy()
    complete['合计(万份)'] = complete[list(ETFS)].sum(axis=1)
    st.metric('四只ETF最近共同披露日合计份额', f"{complete['合计(万份)'].iloc[-1]:,.2f} 万份",
              help=f"共同披露日期：{complete.index[-1]:%Y-%m-%d}；仅四只基金同日齐全时合计")
    if len(complete) >= 2:
        change = complete['合计(万份)'].iloc[-1] - complete['合计(万份)'].iloc[-2]
        st.caption(f'相邻两个完整披露日合计变化：{change:+,.2f}万份（{complete.index[-2]:%Y-%m-%d} → {complete.index[-1]:%Y-%m-%d}）')
else:
    st.info('尚无四只ETF同日齐全的记录，暂不计算合计。')

st.subheader('份额变化趋势')
chart = selected[selected['date'] >= max_date - pd.Timedelta(days=period)].copy()
if not chart.empty:
    fig = px.line(chart, x='date', y='shares_10k', color='name', markers=True,
                  labels={'date': '统计日期', 'shares_10k': '份额（万份）', 'name': 'ETF'})
    fig.update_layout(legend=dict(orientation='h', y=-0.30, x=0), margin=dict(l=10, r=10, t=20, b=95),
                      height=470, hovermode='x unified')
    fig.update_xaxes(range=[chart['date'].min() - pd.Timedelta(days=1), chart['date'].max() + pd.Timedelta(days=1)],
                     tickformat='%m-%d')
    st.plotly_chart(fig, use_container_width=True)

st.subheader('相对份额变化（起点=100）')
if not chart.empty:
    rel = chart.copy()
    rel['指数'] = rel.groupby('code')['shares_10k'].transform(lambda x: x / x.iloc[0] * 100)
    fig = px.line(rel, x='date', y='指数', color='name', markers=True,
                  labels={'date': '日期', '指数': '相对份额指数', 'name': 'ETF'})
    fig.update_layout(height=420, legend=dict(orientation='h', y=-0.32, x=0),
                      margin=dict(l=10, r=10, t=20, b=100))
    fig.update_xaxes(tickformat='%m-%d')
    st.plotly_chart(fig, use_container_width=True)

st.subheader('每次披露相对上次披露的份额变化')
changes = chart.dropna(subset=['delta_10k']).copy()
if not changes.empty:
    fig = px.bar(changes, x='date', y='delta_10k', color='name', barmode='group',
                 labels={'date': '统计日期', 'delta_10k': '变化（万份）', 'name': 'ETF'})
    fig.update_layout(height=420, legend=dict(orientation='h', y=-0.32, x=0),
                      margin=dict(l=10, r=10, t=20, b=100))
    fig.update_xaxes(tickformat='%m-%d')
    st.plotly_chart(fig, use_container_width=True)

st.subheader('异常份额变化提示')
alerts = changes[changes['delta_pct'].abs() >= 5].sort_values('date', ascending=False)
if alerts.empty:
    st.success('当前显示区间未发现单次披露份额变化达到±5%的记录。')
else:
    for _, r in alerts.head(12).iterrows():
        st.warning(f"{r['date']:%Y-%m-%d} · {r['code']} · 份额变化 {r['delta_pct']:+.2f}%（{r['delta_10k']:+,.2f}万份；距上次披露 {int(r['gap_days'])} 天）")

if not complete.empty and len(complete) >= 2:
    previous, current = complete.iloc[-2], complete.iloc[-1]
    signs = [(current[c] - previous[c]) for c in ETFS]
    if all(v > 0 for v in signs):
        st.info('最近两个四只ETF同日齐全的披露日：四只份额同步增加。不能据此确认国家队买入。')
    elif all(v < 0 for v in signs):
        st.info('最近两个四只ETF同日齐全的披露日：四只份额同步减少。不能据此确认国家队卖出。')

st.subheader('资金规模与指数联动')
st.info('尚未接入与份额日期严格匹配的ETF单位净值及沪深300指数历史行情，因此不显示未经验证的净申赎金额，也不生成“国家队买卖”结论。')
st.caption('理论估算：份额变化（万份）× 当日每份净值（元）÷ 10,000 = 亿元。此值仅为份额变动对应的参考规模，并非真实资金流水。')
st.caption('ETF份额变化存在申赎确认及披露滞后；跨非交易日或数据缺口的差额不能标为单日变化。')

st.download_button('下载完整份额历史CSV', d[['date', 'code', 'shares_10k', 'source']].to_csv(index=False).encode('utf-8-sig'),
                   file_name='etf_shares_history.csv', mime='text/csv')