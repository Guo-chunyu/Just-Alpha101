# Just Alpha101

**从 101 个公式出发，学习如何把一个量化想法变成可以检查的研究。**

这是对 Zura Kakushadze《[101 Formulaic Alphas](https://arxiv.org/abs/1601.00991)》的大学生研究项目：独立实现全部公式，用真实美股数据做参数敏感性与成本实验，写清楚自己的理解和没有复现的部分。

> **当前不是严格成功复现。** 101 个公式已实现并测试；现有数据只能支持其中 52 个因子的诊断实验，其余 49 个明确跳过。严格数据验收未通过，平均毛 Sharpe 也没有达到论文水平。

| 已完成的内容 | 证据 |
|---|---|
| 101 个公式、安全表达式引擎与完整窗口算子 | [源码](src/just_alpha101/formulas.py)、[测试](tests) |
| 真实数据：486 只美股、857,304 条输入记录 | [数据审计](reports/data_audit.json)、[股票池](reports/universe.csv) |
| 2010-01-04—2013-12-31，1,006 个入场日 | 最后一个区间于 2014-01-02 开盘结束 |
| 6 组候选 × 3 个成本档位 × 3 个统计区间 | [2,808 行逐因子结果](reports/metrics.csv) |
| 78 项本地测试通过 | 算子手算、全部公式因果性、回测、时间边界、错误输入 |
| 原文差距、手算例子与研究反思 | [完整研究报告](reports/research_report.md)、[我的理解](docs/understanding.md) |

## 先看结果

| 描述性指标 | 原论文（101 个因子） | 本项目基线（52 个可计算因子） |
|---|---:|---:|
| 平均毛 Sharpe | 2.265 | 0.468 |
| 平均年化算术收益 | 6.015% | 1.279% |
| 平均日换手 | 0.5456 | 0.8319 |
| 平均两两收益相关性 | 15.86% | 14.61% |

**因子集合、股票池、数据和执行方式都不同，上表只是参考对照。** 相关性接近不能替代收益与数据标准。每单边 5 bps 成本后，本项目平均因子 Sharpe 约为 -3.113。结果没有经过按收益删选或符号翻转。

![论文与本项目的参考对比](reports/figures/paper_comparison.png)

## 这次研究的几个收获

- **先检查量纲。** 原文 `adv20` 写作平均美元成交额，却有与成交股数比较的公式；保留字面口径，并将成交股数口径单独做敏感性实验。
- **先检查什么时候能知道数据。** 收盘产生的信号统一延迟到下一开盘执行。论文四个 delay-0 因子因此有执行差异，不假设能提前知道当天收盘信息。
- **完整信号不等于有效交易。** Alpha7 在基线中信号覆盖完整，但只在 43 / 1,006 天持仓。去均值会把全体相同的常数信号变成现金。
- **参数改变不等于改进。** 窗口倍率 0.8、1.0、1.2 是算子窗口扰动，公式里的算术常数保持不变。全部候选及保留期结果均保留。
- **成本与样本偏差必须写出来。** 诊断股票池经过完整历史筛选，存在未来存续信息与幸存者偏差。毛收益也不能代表扣费后表现。

![参数与成本敏感性](reports/figures/parameter_sensitivity.png)

## 本地复现

在 Python 3.13 上测试。以下为 PowerShell；其他系统把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m pytest -q

# 下载约 463 MB 历史存档，生成本地面板与审计
.\.venv\Scripts\python.exe scripts/prepare_data.py

# 显式替换仓库附带的实验输出；不会删除原始行情或数据审计
.\.venv\Scripts\python.exe scripts/run_experiments.py --overwrite
.\.venv\Scripts\python.exe scripts/build_report.py
```

首轮下载和解析需一些时间，实测六组实验约数分钟，取决于电脑性能。原始 ZIP 和 Parquet 不上传 GitHub；存档 SHA-256、源地址、版本、配置与代码摘要已记录。数据镜像发生变化时，应先对比校验值，不能默认得到完全相同结果。

严格验收命令：

```powershell
.\.venv\Scripts\python.exe scripts/audit_data.py --strict
```

当前数据应返回退出码 **2**，因为缺少真实 VWAP、实际美元成交额、时点市值/行业、完整退市及当时可得的复权数据。它不会把代理字段认证为原始字段。

只检查部分因子时，使用独立目录避免混入正式结果：

```powershell
.\.venv\Scripts\python.exe scripts/run_experiments.py --alphas 1,4,101 --baseline-only --output reports/debug_run
```

也支持接入自己的 CSV/Parquet（含真实 VWAP、市值和行业层级时可运行全部 101 个）。见 [数据契约与审计接口](docs/data_contract.md)。

## 目录

```text
configs/experiment.json       首次回测前固定的候选配置
src/just_alpha101/            公式、算子、数据审计、回测、统计
tests/                       手算、边界、未来扰动与集成验证
scripts/                     数据准备、审计、实验和报告生成
reports/                     全量汇总、每日因子组合收益、图表与中文报告
docs/                        研究设计、数据接口和理解
data/                        本地原始及处理后行情（Git 忽略）
```

## 复现边界

论文使用 WorldQuant 专有数据。评估期公开，但准确股票池、持仓构建和执行参数未完整公开；文中的“2,000 只高流动性美股”只是例子。现有 WIKI 存档含复权 OHLCV，无法提供真实日内 VWAP、完整历史行业层级和市值。当前 52 个因子的结果也仍依赖成交额代理、事后复权以及有偏的完整历史股票池。

2013 是本项目内部保留区间，不能称为原始因子的真正事前样本外区间：原公式在 2016 年公开，可能已使用过更早历史。没有通过反复筛选 2013 参数来包装成功。合成数据只用于软件测试，不进入收益报告。

暂未计算真实 cents-per-share、借券费、冲击或容量；组合成本采用独立因子子组合加总，没有内部交易抵消。后续需要合格数据和更完整的执行账本，而不只是更多调参。

This is a transparent educational reproduction, not a claim of matching the proprietary paper backtest. All 101 formulas are implemented; 52 are evaluated on the explicitly limited public-data diagnostic cohort.

## 来源与许可

- [原论文](https://arxiv.org/abs/1601.00991)、[Nasdaq WIKI 说明](https://data.nasdaq.com/databases/WIKIP)、[本次历史数据镜像](https://www.kaggle.com/datasets/marketneutral/quandl-wiki-prices-us-equites)。
- 独立编写的项目代码和文档采用 [MIT](LICENSE)；第三方原始公式材料、论文和行情的权利不因此改变。详见 [NOTICE](NOTICE)。
- 研究报告没有虚构个人交易经历；使用 AI 辅助实现、审阅和文稿整理，结论以公开的实际运行结果为依据。
