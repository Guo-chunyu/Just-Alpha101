# 数据接口与严格验收

标准长表：每行一个 `date × symbol`。CSV 使用 UTF-8 和 ISO 日期；Parquet 推荐 datetime 日期类型。股票代码保持字符串。记录不得重复，OHLC 必须为正且高低价范围一致，成交量必须有限且非负。日历按 XNYS 检查特殊休市，不用简单工作日替代。

| 字段 | 类型 | 含义 |
|---|---|---|
| date | 日期 | 交易日，无时区、日粒度 |
| symbol | 字符串 | 稳定股票标识；需在来源说明中解释改名、合并 |
| open/high/low/close | 数值 | 调整口径一致的价格 |
| volume | 数值 | 与价格口径一致并有说明的成交股数 |
| dollar_volume | 数值 | 实际成交美元额；若为 close×volume 必须标为代理 |
| vwap | 数值 | 真实日内成交量加权价，不能用 HLC3 替换 |
| cap | 数值 | 当时可得的历史市值，仅 Alpha56 需要 |
| sector/industry/subindustry | 字符串 | 每个交易日当时可得的分类，禁止静默填当前分类 |

仅有基本 OHLCV 可以计算部分因子。引擎根据公式依赖检查字段；缺少数据时抛出 `MissingFieldError`，实验脚本记入 `factor_coverage.csv`。提供真实 `vwap × volume` 可以推导美元成交额，前提是二者调整/单位口径一致；引擎不会自己使用收盘价代理。

## WIKI 适配器的明确选择

原始 `adj_*` 用于公式价格和成交股数，`raw close × raw volume` 用于**显式美元成交额代理**。WIKI 历史复权结果是事后版本，不等于每天当时可获得的截面价格；尤其绝对价格和价格阈值因子会受到复权基准影响。

完整历史筛选只是让日线诊断实验不必猜测缺失退市价格；它使用未来是否完整的信息，带来幸存者偏差，不通过严格成员/退市验收。选取规则和所有被排除代码都保留。原数据存档含约数千只股票，不意味着它无缺失或无幸存者偏差。

## 审计用元数据

`--provenance` 接受 JSON。键包括 `source`、`source_page`、`archive_sha256`、`adjustment`、`processed_sha256` 及以下证据声明。`processed_sha256` 必须是本次导入 CSV/Parquet 文件的 SHA-256；不匹配时停止，不会替换已有结果。哈希只能证明文件身份，不能替代来源真实性审核。

```json
{
  "vwap_is_trade_weighted": false,
  "dollar_volume_is_actual": false,
  "cap_is_point_in_time": false,
  "industry_is_point_in_time": false,
  "corporate_actions_documented": false,
  "adjustments_point_in_time": false,
  "membership_and_delistings_verified": false
}
```

只能在核实来源和时点口径后将对应值设为 true。字段存在或声明为 true 都不够：程序同时检查有效数值、非空分类、评估交易日、每股票完整观察、以及评估前**最近连续 500 个 XNYS 交易日**。程序能验证结构和记录一致性，无法验证供应商的每笔数据真伪；人工证据审核仍然必需。

当前严格模式采用完整面板的保守验收，真实动态成员池需要进一步实现成员有效区间与退市事件适配器，不能简单把 IPO 前空值填满。`strict_data_ready` 只代表本项目的公开字段/质量要求；`exact_paper_replication_verifiable` 始终为 false，因为原作者的完整交易配置没有披露。

```powershell
python scripts/audit_data.py --data your_panel.parquet --provenance source.json --output reports/custom_audit.json --strict
python scripts/run_experiments.py --data your_panel.parquet --provenance source.json --require-strict-data --config configs/experiment.json --output reports/custom_run
```

独立审计命令未通过时退出码为 2；实验命令带 `--require-strict-data` 时也会在不合格输入上停止。默认存档诊断样本不能通过严格验收。自有数据需要同步调整配置中的时间、样本描述和预热区间。每次实验会重新生成本次输入的审计，记录输入文件哈希；自定义输入不会沿用 WIKI 的来源说明。运行目录若已有实验结果会拒绝覆盖；确实要替换时使用 `--overwrite`，只替换已知实验输出，保留其他文件。数据校验和严格检查在替换结果之前执行。

没有授权数据库时，继续使用当前明确差距的公开研究版本。未来有数据条件时可参考[字段与授权来源核查](data_access_options.md)，该文档不代表已获得订阅或数据。

## 结果读取

- `metrics.csv`：每因子 × 每候选 × 每期间 × 每成本，包括零持仓日。
- `factor_coverage.csv`：全部 101 因子的字段缺失、平均信号覆盖率和实际持仓天数。
- `daily_*.csv.gz`：每因子的每日组合 P&L、换手和资产数；这是派生研究数据，不是原始行情。
- `paper_comparison.json`：描述统计和论文式回归，负/零平均收益明确不进入 log-return 回归。
- `run_manifest.json`：配置、代码摘要、版本与执行约定。
- `data_audit.json`：数据来源、哈希、筛选名单和逐项验收。

当前不计算 cents-per-share。价格复权后的名义份额不能被当作真实成交股数；需要未复权执行账本、公司行动换股和成交数量才能加入这一指标。
