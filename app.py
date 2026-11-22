"""CSI 300 ETF share monitor V4. Uses exchange share observations (10k shares)."""
import datetime as dt
from io import StringIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

ETFS = {'510300': '华泰柏瑞沪深300ETF', '510330': '华夏沪深300ETF',
        '510310': '易方达沪深300ETF', '159919': '嘉实沪深300ETF'}
LOCAL = Path(__file__).resolve().parent / 'data' / 'shares.csv'
REMOTE = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/shares.csv'
COLS = {'date', 'code', 'shares_10k', 'source'}
TODAY = pd.Timestamp.now(tz='Asia/Shanghai').tz_localize(None).normalize()

st.set_page_config(page_title='沪深300 ETF资金观察', layout='wide', initial_sidebar_state='collapsed')
st.title('沪深300 ETF资金观察')
st.caption('顶部：全部直接跟踪沪深300的场内ETF市值占比（需经核验的数据）｜下方：四只代表ETF份额监测')
st.markdown('''<style> .block-container{padding-top:1.3rem;padding-bottom:2rem;max-width:1250px} [data-testid="stMetricValue"]{font-size:clamp(1.35rem,4vw,2.3rem)} @media(max-width:700px){h1{font-size:1.65rem!important}h2{font-size:1.25rem!important}h3{font-size:1.1rem!important} .block-container{padding-left:0.8rem;padding-right:0.8rem} [data-testid="stHorizontalBlock"]{gap:.5rem}} </style>''', unsafe_allow_html=True)

# The historical float-adjusted capitalization is not in ETF share observations.
# A separate, auditable dataset is required for the numerator and denominator.
RATIO_LOCAL = Path(__file__).resolve().parent / 'data' / 'etf_market_ratio.csv'
RATIO_REMOTE = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/etf_market_ratio.csv'
RATIO_COLS = {'date', 'etf_market_cap_yi', 'csi300_float_cap_yi', 'csi300_close'}

COMPONENTS_LOCAL = Path(__file__).resolve().parent / 'data' / 'etf_market_components.csv'
COMPONENTS_REMOTE = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/etf_market_components.csv'

@st.cache_data(ttl=300, show_spinner=False)
def components_remote_csv():
    import requests
    r = requests.get(COMPONENTS_REMOTE, timeout=12, headers={'Cache-Control': 'no-cache'})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text))

INDEX_LOCAL = Path(__file__).resolve().parent / 'data' / 'csi300_index_history.csv'
INDEX_REMOTE = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/csi300_index_history.csv'

@st.cache_data(ttl=300, show_spinner=False)
def index_history_remote():
    import requests
    r = requests.get(INDEX_REMOTE, timeout=12, headers={'Cache-Control': 'no-cache'})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text))

def components_panel():
    """One shared time axis, two Y axes; never substitute four ETFs for the full-market ratio."""
    try:
        idx_raw = pd.read_csv(INDEX_LOCAL) if INDEX_LOCAL.exists() else index_history_remote()
        if idx_raw is None or not {'date', 'csi300_close'}.issubset(idx_raw.columns):
            st.warning('沪深300指数历史数据尚未采集成功。')
            return
        idx = idx_raw[['date', 'csi300_close']].copy()
        idx['date'] = pd.to_datetime(idx['date'], errors='coerce').dt.normalize()
        idx['csi300_close'] = pd.to_numeric(idx['csi300_close'], errors='coerce')
        idx = idx.dropna().drop_duplicates('date', keep='last').sort_values('date')
        idx = idx[(idx['date'] <= TODAY) & idx['csi300_close'].gt(0)]
        if idx.empty:
            st.warning('没有可用的沪深300指数数据。')
            return
        choices = ['2024年至今', '2026年', '近1年', '近6个月', '近3个月']
        choice = st.radio('时间范围', choices, horizontal=True, key='components_period', index=0)
        last = idx['date'].max()
        starts = {
            '2024年至今': pd.Timestamp('2024-01-01'),
            '2026年': pd.Timestamp('2026-01-01'),
            '近1年': last - pd.DateOffset(years=1),
            '近6个月': last - pd.DateOffset(months=6),
            '近3个月': last - pd.DateOffset(months=3),
        }
        cutoff = starts[choice]
        view = idx[idx['date'] >= cutoff]
        fig = make_subplots(specs=[[{'secondary_y': True}]])
        fig.add_trace(go.Scatter(
            x=view['date'], y=view['csi300_close'],
            name='沪深300指数（点）', mode='lines',
            line={'color': '#7bbcf4', 'width': 2.3},
            hovertemplate='%{x|%Y-%m-%d}<br>沪深300：%{y:,.2f}点<extra></extra>'
        ), secondary_y=False)
        # Orange is deliberately absent until the verified all-ETF ratio exists.
        # Both series will occupy this same subplot, with independent left/right scales.
        fig.update_yaxes(title_text='沪深300指数（点）', secondary_y=False,
                         automargin=True)
        fig.update_yaxes(title_text='全部沪深300ETF市值占比（%）', secondary_y=True,
                         ticksuffix='%', showgrid=False, automargin=True)
        fig.update_xaxes(
            range=[max(cutoff, idx['date'].min()), last + pd.Timedelta(days=2)],
            rangeslider={'visible': True, 'thickness': 0.10},
            tickformat='%Y-%m')
        fig.update_layout(
            height=460, margin={'l':8,'r':8,'t':12,'b':75},
            hovermode='x unified', dragmode='pan',
            legend={'orientation':'h','y':-0.34,'x':0})
        st.plotly_chart(fig, use_container_width=True,
                        config={'scrollZoom':True, 'displaylogo':False,
                                'displayModeBar':False})
        st.caption(f"指数覆盖：{idx['date'].min():%Y-%m-%d} 至 {last:%Y-%m-%d}，共{len(idx)}个有效交易日。橙线将在真实全市场占比数据齐备后叠加到同一张图的右轴。")
    except Exception as exc:
        st.warning(f'指数图读取失败：{exc}')


@st.cache_data(ttl=300, show_spinner=False)
def ratio_remote_csv():
    import requests
    r = requests.get(RATIO_REMOTE, timeout=12)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text))

def clean_ratio(raw):
    if not RATIO_COLS.issubset(raw.columns):
        raise ValueError('市值CSV需要 date,etf_market_cap_yi,csi300_float_cap_yi,csi300_close 四列')
    x = raw[list(sorted(RATIO_COLS))].copy()
    x['date'] = pd.to_datetime(x['date'], errors='coerce').dt.normalize()
    for c in RATIO_COLS - {'date'}:
        x[c] = pd.to_numeric(x[c], errors='coerce')
    x = x.dropna(subset=list(RATIO_COLS))
    x = x[(x['date'] <= TODAY) & (x['etf_market_cap_yi'] > 0) &
          (x['csi300_float_cap_yi'] > 0) & (x['csi300_close'] > 0)]
    if x.duplicated('date').any():
        raise ValueError('市值CSV存在重复日期，请先核对')
    x['ratio_pct'] = x['etf_market_cap_yi'] / x['csi300_float_cap_yi'] * 100
    if (x['ratio_pct'] >= 100).any():
        raise ValueError('存在占比≥100%的异常值，请核对分子、分母及单位')
    return x.sort_values('date')

def ratio_panel():
    st.subheader('沪深300 ETF市值占沪深300流通市值比例')
    st.caption('蓝线：沪深300指数；橙线：全部直接跟踪沪深300的场内ETF合计市值 ÷ 沪深300成分股流通市值合计 × 100%。不含增强ETF和联接基金。')
    with st.expander('数据来源与导入说明', expanded=False):
        st.write('需要同日、同口径的真实历史数据。分子应覆盖当日所有直接跟踪沪深300的场内ETF（不含增强ETF、联接基金），逐只用份额×对应日期净值计算；分母必须为沪深300成分股流通市值合计，不能用指数点位或成交额代替。')
        st.code('date,etf_market_cap_yi,csi300_float_cap_yi,csi300_close', language='text')
        st.caption('市值单位均为亿元，指数单位为点；可将CSV提交到仓库 data/etf_market_ratio.csv 自动展示。仅接受已核实涵盖全部符合条件ETF的同口径数据。')
    upload = st.file_uploader('可选：上传已核实的市值历史CSV', type='csv', key='ratio_csv')
    try:
        if upload is not None:
            raw_ratio = pd.read_csv(upload)
            label = '本次上传文件（仅当前会话）'
        elif RATIO_LOCAL.exists():
            raw_ratio = pd.read_csv(RATIO_LOCAL)
            label = '仓库本地CSV'
        else:
            raw_ratio = ratio_remote_csv()
            label = 'GitHub历史市值CSV'
        if raw_ratio is None:
            st.info('蓝线与橙线共用一张图和时间横轴：蓝线使用左侧指数点位，橙线使用右侧百分比。当前尚无核实的全市场占比数据，暂不绘制橙线。')
            components_panel()
            return
        x = clean_ratio(raw_ratio)
        if x.empty:
            st.warning('市值CSV中没有通过校验的有效记录。')
            return
        periods = {'全部': None, '近1年':365, '近6个月':183, '近3个月':92, '近1个月':31}
        choice = st.radio('市值图时间范围', list(periods), horizontal=True, key='ratio_period')
        days = periods[choice]
        view = x if days is None else x[x['date'] >= x['date'].max() - pd.Timedelta(days=days)]
        latest = x.iloc[-1]
        a, b = st.columns(2)
        a.metric('最新市值占比', f"{latest['ratio_pct']:.3f}%")
        b.metric('沪深300收盘点位', f"{latest['csi300_close']:,.2f}")
        fig = make_subplots(specs=[[{'secondary_y': True}]])
        fig.add_trace(go.Scatter(x=view['date'], y=view['csi300_close'], name='沪深300指数',
                                 mode='lines', line={'color':'#42a5f5','width':2.4},
                                 hovertemplate='%{x|%Y-%m-%d}<br>指数：%{y:,.2f}点<extra></extra>'), secondary_y=False)
        fig.add_trace(go.Scatter(x=view['date'], y=view['ratio_pct'], name='全部沪深300ETF市值占比',
                                 mode='lines', line={'color':'#ff9f43','width':2.4},
                                 hovertemplate='%{x|%Y-%m-%d}<br>占比：%{y:.3f}%<extra></extra>'), secondary_y=True)
        fig.update_yaxes(title_text='指数（点）', secondary_y=False)
        fig.update_yaxes(title_text='市值占比（%）', ticksuffix='%', secondary_y=True)
        fig.update_xaxes(rangeslider={'visible': True, 'thickness':0.09}, tickformat='%Y-%m',
                         range=[view['date'].min(), view['date'].max() + pd.Timedelta(days=1)])
        fig.update_layout(height=490, margin={'l':5,'r':5,'t':15,'b':85},
                          hovermode='x unified', dragmode='pan',
                          legend={'orientation':'h','y':-0.30,'x':0})
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'displaylogo': False})
        st.caption(f"数据：{label}｜最后日期：{latest['date']:%Y-%m-%d}｜{len(x)}个观测日。该占比要求覆盖当日全部直接跟踪沪深300的场内ETF，排除增强ETF和联接基金；请核验CSV来源和覆盖率。")
        st.download_button('下载市值占比计算结果', x.to_csv(index=False).encode('utf-8-sig'),
                           'etf_market_ratio_checked.csv', 'text/csv')
    except Exception as e:
        st.warning(f'市值图暂无法显示：{e}。原有ETF份额监测仍可使用。')

@st.cache_data(ttl=300, show_spinner=False)
def all_etf_remote_csv():
    import requests
    url = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/all_csi300_etf_market.csv'
    r = requests.get(url, timeout=12)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text), dtype={'code':str})

def all_etf_panel():
    st.subheader('全市场沪深300ETF候选基金市值采集进度')
    path = Path(__file__).resolve().parent / 'data' / 'all_csi300_etf_market.csv'
    try:
        raw = pd.read_csv(path, dtype={'code':str}) if path.exists() else all_etf_remote_csv()
        if raw is None:
            st.info('自动采集程序已配置，等待首次运行生成候选ETF市值文件。')
            return
        needed = {'date','code','name','market_cap_yi'}
        if not needed.issubset(raw.columns):
            st.warning('候选ETF文件格式不完整。')
            return
        x = raw.copy()
        x['date'] = pd.to_datetime(x['date'], errors='coerce')
        x['market_cap_yi'] = pd.to_numeric(x['market_cap_yi'], errors='coerce')
        x = x.dropna(subset=['date','market_cap_yi'])
        x = x[x['market_cap_yi'] > 0]
        if x.empty:
            st.warning('尚无有效候选ETF市值。')
            return
        daily = x.groupby('date').agg(
            候选ETF市值合计_亿元=('market_cap_yi','sum'),
            当日基金数量=('code','nunique')).reset_index()
        st.metric('最新候选ETF数量', int(daily.iloc[-1]['当日基金数量']))
        st.metric('最新候选ETF市值合计（亿元）',
                  f"{daily.iloc[-1]['候选ETF市值合计_亿元']:,.2f}")
        st.caption('此处按基金名称筛选沪深300ETF候选名单，尚未逐只核实跟踪标的和历史覆盖率；不同日期基金数量可能变化。不能把候选市值直接当作全市场完整市值。')
        st.dataframe(daily.tail(30).sort_values('date', ascending=False),
                     hide_index=True, use_container_width=True)
        st.download_button('下载候选ETF明细', x.to_csv(index=False).encode('utf-8-sig'),
                           file_name='all_csi300_etf_candidates.csv', mime='text/csv')
    except Exception as exc:
        st.warning(f'候选ETF数据尚不可用：{exc}')

def denominator_status():
    st.subheader('沪深300流通市值分母采集状态')
    path = Path(__file__).resolve().parent / 'data' / 'csi300_float_cap_observed.csv'
    try:
        if path.exists():
            cap = pd.read_csv(path)
        else:
            import requests
            url = 'https://raw.githubusercontent.com/zee8765/etf-monitor/main/data/csi300_float_cap_observed.csv'
            r = requests.get(url, timeout=10)
            if r.status_code == 404:
                st.info('正在尝试获取沪深300历史成分股自由流通市值；公开接口暂未提供完整300只成分股的可核验日期。')
                return
            r.raise_for_status()
            cap = pd.read_csv(StringIO(r.text))
        required = {'date', 'constituent_count', 'csi300_float_cap_yi'}
        if not required.issubset(cap.columns):
            st.warning('流通市值文件格式不完整。')
            return
        cap['date'] = pd.to_datetime(cap['date'], errors='coerce')
        cap = cap.dropna(subset=['date']).sort_values('date')
        cap = cap[cap['constituent_count'].eq(300) & cap['csi300_float_cap_yi'].gt(0)]
        if cap.empty:
            st.info('尚无覆盖全部300只成分股的有效流通市值日期。')
            return
        st.caption(f"已采集 {len(cap)} 个300成分股齐全的历史观测日期，最新 {cap['date'].iloc[-1]:%Y-%m-%d}。仍需核验指数自由流通口径及ETF覆盖率后才能发布正式占比。")
        st.dataframe(cap.tail(10).sort_values('date', ascending=False), hide_index=True, use_container_width=True)
    except Exception as exc:
        st.info(f'流通市值数据暂不可用：{exc}')

ratio_panel()
all_etf_panel()
denominator_status()
st.divider()

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
    d = raw[['date', 'code', 'shares_10k', 'source']].copy()
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

codes = st.multiselect('监测ETF（可只选一只，手机查看更清楚）', list(ETFS), default=list(ETFS),
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
# Weekday gaps are preliminary only: exchange holidays require a trading calendar.
def weekday_missing(prev, current):
    if pd.isna(prev) or pd.isna(current):
        return 0
    return max(0, len(pd.bdate_range(prev, current)) - 2)

d['missing_weekdays'] = [weekday_missing(a, b) for a, b in zip(d['prev_date'], d['date'])]
d['alert_10pct'] = d['delta_pct'].abs().ge(10)
d['suspect_gap'] = d['missing_weekdays'].gt(0)
d['comparison_type'] = '相邻披露（未核实交易日）'
d.loc[d['suspect_gap'], 'comparison_type'] = '跨工作日缺口'
d.loc[d['prev_date'].isna(), 'comparison_type'] = '无上期记录'
# Do not call a multi-weekday gap a one-day flow. Weekends alone are normal.



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
    row = {'代码': r['code'], 'ETF': r['name'], '最新日期': r['date'].strftime('%Y-%m-%d'), '比较类型': r['comparison_type'],
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
st.caption('柱形表示相邻两次实际披露的差额；如中间缺少工作日，该差额属于跨期变化，并非单日申赎。')
chart_mode = st.radio('变化图显示方式', ['分别查看（手机推荐）', '四只同图'], horizontal=True)

changes = chart.dropna(subset=['delta_10k']).copy()
if not changes.empty:
    if chart_mode == '分别查看（手机推荐）':
        focus = st.selectbox('选择柱状图ETF', codes, format_func=lambda c: f'{c} {ETFS[c]}')
        changes = changes[changes['code'].eq(focus)]
    fig = px.bar(changes, x='date', y='delta_10k', color='name', barmode='group',
                 labels={'date': '统计日期', 'delta_10k': '变化（万份）', 'name': 'ETF'})
    fig.update_layout(height=420, legend=dict(orientation='h', y=-0.32, x=0),
                      margin=dict(l=10, r=10, t=20, b=100))
    fig.update_xaxes(tickformat='%m-%d', type='date', tickangle=-35)
    fig.update_traces(hovertemplate='%{x|%Y-%m-%d}<br>变化：%{y:,.2f} 万份<extra></extra>')
    st.plotly_chart(fig, use_container_width=True)

st.subheader('数据质量检查')
quality = selected[selected['prev_date'].notna()].copy()
large = quality[quality['alert_10pct']].copy()
# Distinguish large changes that span missing weekdays from adjacent observations.
large['核验提示'] = large['suspect_gap'].map({True: '跨工作日缺口，不能视为单日变化', False: '变化较大，需核对交易所原始披露'})
gaps = quality[quality['suspect_gap']].copy()
st.metric('单次变化≥10%（含跨期）', len(large))
st.metric('疑似缺失工作日区间', len(gaps))
st.metric('重复日期代码', int(raw.duplicated(['date', 'code']).sum()) if {'date', 'code'}.issubset(raw.columns) else 0)
st.caption('工作日缺口为周一至周五的初步筛查，未扣除中国法定休市日；跨缺口的变化不等于单日净申赎。异常阈值仅用于提示，不代表数据错误。')
if not large.empty:
    st.warning('存在单次披露变化达到10%的记录，请逐条与交易所核对。')
    st.dataframe(large[['date','code','name','prev_date','shares_10k','delta_10k','delta_pct','gap_days','missing_weekdays','核验提示']].sort_values('date', ascending=False),
                 hide_index=True, use_container_width=True)
if not gaps.empty:
    st.info('以下区间疑似存在工作日数据缺口，可能包含交易所休市日。')
    st.dataframe(gaps[['code','name','prev_date','date','missing_weekdays','delta_10k']], hide_index=True, use_container_width=True)
if large.empty and gaps.empty:
    st.success('未发现超过10%的单次份额变化或疑似工作日缺口。')

st.subheader('核验清单与数据下载')
review = quality[(quality['alert_10pct']) | (quality['suspect_gap'])].copy()
if not review.empty:
    review['核验原因'] = review.apply(lambda r: ('变化≥10%；' if r['alert_10pct'] else '') + ('中间疑似缺失工作日' if r['suspect_gap'] else ''), axis=1)
    st.download_button('下载待核验记录CSV', review[['date','code','name','prev_date','shares_10k','delta_10k','delta_pct','missing_weekdays','核验原因']].to_csv(index=False).encode('utf-8-sig'), 'etf_review.csv', 'text/csv')
st.caption('历史数据只做提示与隔离，不自动修改GitHub仓库中的原始CSV。')

st.subheader('申赎金额参考估算（可选净值CSV）')
st.caption('上传含 date、code、nav 三列的CSV，nav为对应统计日期每份基金单位净值（元）。不使用实时市价代替净值。')
nav_file = st.file_uploader('上传已核实的历史单位净值CSV', type='csv', key='nav_upload')
if nav_file is not None:
    try:
        nav = pd.read_csv(nav_file, dtype={'code':str}, encoding='utf-8-sig')
        if not {'date','code','nav'}.issubset(nav.columns):
            raise ValueError('CSV必须包含 date、code、nav')
        nav['date'] = pd.to_datetime(nav['date'], errors='coerce').dt.normalize()
        nav['code'] = nav['code'].astype(str).str.zfill(6)
        nav['nav'] = pd.to_numeric(nav['nav'], errors='coerce')
        nav = nav.dropna(subset=['date','nav'])
        nav = nav[nav['code'].isin(ETFS) & nav['nav'].gt(0)]
        if nav.duplicated(['date','code']).any():
            raise ValueError('净值CSV存在同一日期、同一ETF的重复记录，请先核实')
        estimates = selected.merge(nav[['date','code','nav']], on=['date','code'], how='inner')
        estimates = estimates[estimates['delta_10k'].notna() & estimates['missing_weekdays'].eq(0)].copy()
        estimates['估算变化(亿元)'] = estimates['delta_10k'] * estimates['nav'] / 10000
        if estimates.empty:
            st.warning('没有可对齐且无疑似工作日缺口的份额变化与净值数据。')
        else:
            st.dataframe(estimates[['date','code','name','delta_10k','nav','估算变化(亿元)','delta_pct','alert_10pct']],
                         hide_index=True, use_container_width=True)
            st.download_button('下载申赎参考估算CSV', estimates.to_csv(index=False).encode('utf-8-sig'),
                               file_name='etf_estimated_flow.csv', mime='text/csv')
            st.warning('估算仅为份额变化乘以对应日期单位净值，不等于实际申赎现金流或国家队买卖；10%以上变化仍需人工核实。')
    except Exception as exc:
        st.error(f'净值文件无法使用：{exc}')

if not complete.empty and len(complete) >= 2:
    previous, current = complete.iloc[-2], complete.iloc[-1]
    signs = [(current[c] - previous[c]) for c in ETFS]
    if all(v > 0 for v in signs):
        st.info('最近两个四只ETF同日齐全的披露日：四只份额同步增加。不能据此确认国家队买入。')
    elif all(v < 0 for v in signs):
        st.info('最近两个四只ETF同日齐全的披露日：四只份额同步减少。不能据此确认国家队卖出。')

st.subheader('资金规模与指数联动')
st.info('可在上方上传已核实的同日净值CSV进行参考估算；尚未自动接入沪深300指数历史行情，不生成国家队买卖结论。')
st.caption('参考估算：份额变化（万份）× 同日期每份净值（元）÷ 10,000 = 亿元。此值并非真实资金流水；若无净值文件则不生成金额。')
st.caption('ETF份额变化存在申赎确认及披露滞后；跨非交易日或数据缺口的差额不能标为单日变化。')

st.download_button('下载完整份额历史CSV', d[['date', 'code', 'shares_10k', 'source']].to_csv(index=False).encode('utf-8-sig'),
                   file_name='etf_shares_history.csv', mime='text/csv')