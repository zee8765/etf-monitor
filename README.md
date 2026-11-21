# 国家队 ETF 监测系统（可运行原型）

## 启动

Python 3.10+：

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

浏览器访问终端给出的地址，通常为 http://localhost:8501 。

## 数据源

- 东方财富 ETF 行情（AKShare `fund_etf_spot_em`）：公开网页接口，盘中可能延迟、限流或报 502。60 秒缓存；**不保证稳定或真实逐笔实时**。
- 上交所 ETF 份额（`fund_etf_scale_sse`）：按指定统计日期抓取。
- 深交所 ETF 份额（`fund_scale_daily_szse`）：按日期区间抓取，单次不超过约 6 个月。

数据源文档：
https://akshare.akfamily.xyz/data/fund/fund_public.html

## 核心限制

1. **ETF份额不是盘中实时申赎流水**，通常需等待交易所披露。
2. 不同交易所原始份额单位可能不同，**本原型不跨交易所合并份额**；原始值展示时请核对单位。
3. 本原型没有自动获取与份额日期对齐的基金净值，**不展示不可靠的人民币净申赎金额**。
4. 历史持仓及中央汇金账户流水不在这些免费接口中；“国家队”仅是研究框架，无法据此识别真实交易主体。
5. 公开网页接口可能变更、被封禁或不可用。请遵守数据源服务条款；正式部署应采用获授权数据。
6. SQLite 数据保存在工作目录 `etf_monitor.sqlite3`。部署到无持久化磁盘的平台会丢失数据；请挂载持久卷或改用托管数据库。

## CSV 手工回补

CSV UTF-8 文件表头：`date,code,shares`。例如：

```csv
date,code,shares
2026-11-19,510300,100000000
2026-11-20,510300,101000000
```

示例数字是虚构数据，不能当作真实份额。导入的 shares 必须与同基金既有记录保持同一计量单位。

## 部署

将目录上传 GitHub，Streamlit Community Cloud 选择 `app.py` 部署。公开服务需注意数据授权、网络可达性、持久化存储；不应假定社区云能长期保留本地 SQLite。

## 验证

- `python -m py_compile app.py` 检查语法。
- 启动后点击左侧交易所采集按钮；观察是否成功以及数据日期。
- 若行情接口不可用，界面显示错误而不生成虚构数据。
