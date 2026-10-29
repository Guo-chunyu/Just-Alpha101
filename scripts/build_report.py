"""Build plots and a Chinese research report from saved, unfiltered experiment outputs."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'


def md_table(frame):
    headers = list(frame.columns)
    return '| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n' + '\n'.join(
        '| ' + ' | '.join(map(str, row)) + ' |' for row in frame.itertuples(index=False, name=None))


def main():
    metrics = pd.read_csv(REPORTS / 'metrics.csv')
    coverage = pd.read_csv(REPORTS / 'factor_coverage.csv')
    audit = json.loads((REPORTS / 'data_audit.json').read_text(encoding='utf-8'))
    stats = json.loads((REPORTS / 'paper_comparison.json').read_text(encoding='utf-8'))
    manifest = json.loads((REPORTS / 'run_manifest.json').read_text(encoding='utf-8'))
    baseline = metrics.query("candidate == 'dollar_w1' and period == 'full_2010_2013' and cost_bps == 0")
    figures = REPORTS / 'figures'
    figures.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'figure.facecolor': 'white', 'axes.titleweight': 'bold'})
    blue, orange = '#245B85', '#D57535'
    # Deliberately separate units and label the unequal factor sets.
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.3))
    comparisons = [('Mean gross Sharpe', 2.265, stats['summary']['sharpe']['mean']),
                   ('Mean daily turnover', .5456, stats['summary']['turnover']['mean']),
                   ('Mean pair correlation (%)', 15.86, stats['summary']['pair_correlation']['mean'] * 100)]
    for ax, (label, paper, ours) in zip(axes, comparisons):
        bars = ax.bar(['Paper: 101', f'This study: {len(baseline)}'], [paper, ours], color=[orange, blue], width=.58)
        ax.bar_label(bars, fmt='%.3f', padding=5)
        ax.set_title(label, fontsize=11)
        ax.set_ylim(0, max(paper, ours)*1.22)
        ax.grid(axis='y', alpha=.18)
        ax.set_axisbelow(True)
    fig.suptitle('Reference comparison, not a matched replication', fontsize=14, weight='bold')
    fig.text(.5, .02, 'Different factor sets, universe, inputs and execution. Gross results exclude costs.', ha='center', fontsize=9)
    fig.tight_layout(rect=[0, .06, 1, .93])
    fig.savefig(figures / 'paper_comparison.png', dpi=160)
    plt.close(fig)

    grouped = metrics.groupby(['candidate', 'period', 'cost_bps'], sort=False).agg(
        mean_sharpe=('sharpe', 'mean'), median_sharpe=('sharpe', 'median'),
        mean_annual_return=('annual_return', 'mean'), mean_turnover=('turnover', 'mean'),
        n_factors=('alpha', 'count')).reset_index()
    grouped.to_csv(REPORTS / 'candidate_summary.csv', index=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for ax, period, title in zip(axes, ['full_2010_2013', 'holdout_2013'], ['Full 2010-2013', 'Project holdout: 2013']):
        for basis, color in [('dollar', blue), ('shares', orange)]:
            for cost, style in [(0, '-'), (5, '--')]:
                values = []
                for multiplier in [.8, 1., 1.2]:
                    row = grouped[(grouped.candidate == f'{basis}_w{multiplier:g}') & (grouped.period == period) & (grouped.cost_bps == cost)]
                    values.append(row.mean_sharpe.iloc[0])
                ax.plot([.8, 1., 1.2], values, marker='o', ls=style, color=color, label=f'{basis}, {cost} bps')
        ax.set(title=title, xlabel='Temporal window multiplier', ylabel='Mean individual-factor Sharpe')
        ax.set_xticks([.8, 1., 1.2]); ax.axhline(0, color='#777777', lw=.7); ax.grid(alpha=.2)
    axes[1].legend(fontsize=8, loc='best')
    fig.suptitle('Window perturbations: arithmetic constants remain fixed', weight='bold')
    fig.tight_layout()
    fig.savefig(figures / 'parameter_sensitivity.png', dpi=160)
    plt.close(fig)

    daily = pd.read_csv(REPORTS / 'daily_dollar_w1.csv.gz', parse_dates=['date'])
    sleeves = daily.groupby('date')[['gross_return', 'turnover']].mean()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    for cost, color in [(0, blue), (5, orange), (10, '#7E4F6C')]:
        cumulative = (sleeves.gross_return - sleeves.turnover * cost / 10000).cumsum()*100
        axes[0].plot(cumulative.index, cumulative, label=f'{cost} bps per traded dollar', color=color)
    axes[0].set(title='Equal-weight factor sleeves', ylabel='Cumulative P&L / fixed capital (%)')
    axes[0].xaxis.set_major_locator(mdates.YearLocator())
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[0].legend(fontsize=8); axes[0].grid(alpha=.2)
    axes[1].scatter(baseline.turnover, baseline.sharpe, color=blue, s=28, alpha=.8)
    axes[1].axhline(0, color='#777777', lw=.7)
    axes[1].set(title='Gross Sharpe versus turnover', xlabel='Mean daily turnover', ylabel='Gross Sharpe')
    axes[1].grid(alpha=.2)
    fig.text(.5, .01, 'Sleeves charged independently; internal trade crossing, borrow fees and price impact are not modeled.', ha='center', fontsize=8)
    fig.tight_layout(rect=[0, .04, 1, 1])
    fig.savefig(figures / 'cost_and_turnover.png', dpi=160)
    plt.close(fig)

    correlation = pd.read_csv(REPORTS / 'baseline_correlation.csv', index_col=0)
    fig, ax = plt.subplots(figsize=(10, 8.5))
    im = ax.imshow(correlation, vmin=-1, vmax=1, cmap='RdBu_r')
    ax.set_xticks(range(len(correlation)), correlation.columns, rotation=90, fontsize=6)
    ax.set_yticks(range(len(correlation)), correlation.index, fontsize=6)
    ax.set(title=f'Daily P&L correlations: {len(correlation)} available-input factors', xlabel='Alpha number', ylabel='Alpha number')
    fig.colorbar(im, ax=ax, fraction=.046, pad=.04)
    fig.tight_layout(); fig.savefig(figures / 'factor_correlation.png', dpi=160); plt.close(fig)

    table = grouped[grouped.period.isin(['full_2010_2013', 'holdout_2013']) & grouped.cost_bps.isin([0, 5])].copy()
    table['mean_sharpe'] = table.mean_sharpe.map(lambda x: f'{x:.3f}')
    table['mean_annual_return'] = table.mean_annual_return.map(lambda x: f'{x*100:.2f}%')
    table = table[['candidate', 'period', 'cost_bps', 'mean_sharpe', 'mean_annual_return']]
    table.columns = ['方案', '区间', '单边成本 bps', '因子平均 Sharpe', '因子平均年化算术收益']
    basecov = coverage[(coverage.candidate == 'dollar_w1') & (coverage.status == 'computed')]
    alpha7 = basecov[basecov.alpha == 7].iloc[0]
    missing = coverage[(coverage.candidate == 'dollar_w1') & (coverage.status == 'missing_fields')]
    regression = stats['regressions']['return_volatility']
    slope = regression['coefficients'].get('log_daily_volatility', {}).get('estimate')
    points = [(key, '通过' if value['passed'] else '未通过', value['detail']) for key, value in audit['checks'].items()]
    regression_table = []
    for name, model in stats['regressions'].items():
        coefficients = ', '.join(f'{key}={item["estimate"]:.4f}' for key,item in model.get('coefficients', {}).items())
        regression_table.append([name, model['nobs'], model['excluded'], f'{model.get("r_squared", np.nan):.4f}', coefficients])
    own = stats['summary']
    reference = pd.DataFrame([
        ['因子数量', '101', str(len(baseline))],
        ['平均 Sharpe（毛）', '2.265', f'{own["sharpe"]["mean"]:.3f}'],
        ['平均日换手', '0.5456', f'{own["turnover"]["mean"]:.4f}'],
        ['平均持有期（1/换手，天）', '2.391', f'{own["holding_period"]["mean"]:.3f}'],
        ['平均年化算术收益', '6.015%', f'{own["annual_return"]["mean"]*100:.3f}%'],
        ['平均两两相关性', '15.86%', f'{own["pair_correlation"]["mean"]*100:.2f}%'],
        ['收益—波动率对数回归斜率', '0.761', f'{slope:.3f}' if slope is not None else '不可估计'],
        ['cents-per-share', '0.4814（平均）', '不报告：未重建未复权成交股数'],
    ], columns=['统计量', '论文表格', '本项目诊断样本'])
    text = f'''# Just Alpha101：一次有边界的复现

## 我想回答的问题

我把这次研究拆成三个问题：101 个表达式能否正确变成代码？公开数据能支持多少个因子？在明确的执行和成本假设下，论文中的表现与统计规律还剩多少？这三个问题不能相互替代。

**当前结论：101 个公式已实现，但严格数据验收未通过，尚未达到原论文的收益效果。** 本次真实数据实验能计算 {len(baseline)} 个因子，另有 {len(missing)} 个因缺失字段而跳过。没有用随机数据、HLC3 或当前行业来填补实证缺口。

## 数据和验收

数据来自历史 Quandl WIKI 存档的 Kaggle 镜像。先按 2009 年原始收盘价乘成交量的均值预选 500 只股票，再保留完整历史的 {audit['symbols']} 只，得到 {audit['rows']:,} 条记录。另有 {len(audit['provenance']['continuity_excluded_symbols'])} 只被排除，详见 [股票池清单](universe.csv)。预选流动性只用 2009 年信息，**完整历史筛选使用了未来存续信息，存在幸存者偏差**；这使本实验适合诊断实现和敏感性，不能作为无偏策略收益。

评估窗口为 2010-01-04—2013-12-31，共 1006 个入场日。最后一个区间在 2014-01-02 开盘结束。论文没有披露足以精确匹配的交易区间和股票池。输入含 2007 年以来预热历史，严格检查评估前最近 500 个交易日。

{md_table(pd.DataFrame(points, columns=['检查', '状态', '说明']))}

存档 SHA-256：`{audit['provenance']['archive_sha256']}`。原始行情和处理后行情留在本地，仓库仅保留来源、哈希及派生实验结果。镜像并不是数据提供商的审计认证。

## 方法和防止自我欺骗的约定

每个交易日对信号去截面均值，再按绝对值和归一到总敞口 1；收盘形成信号，下一开盘交易，到再下一开盘计算收益。资金分母保持固定，年化收益为日均 P&L×252，不是 CAGR。换手采用漂移调整后的买卖金额绝对值之和，没有除以二。成本为成交金额每单边 0、5、10 bps；未包括借券费、冲击和融资费，也没有逐标的容量约束。期末保留持仓，未额外收取平仓费。

论文的 42、48、53、54 为 delay-0，本项目统一保守延迟；可计算的 53、54 因而不是原执行假设。算子中的并列排名、极值索引及标准差自由度是公开说明的实现约定，不能假称为未披露的原作者配置。

六组候选为窗口倍率 0.8、1.0、1.2 × 美元成交额代理/成交股数 ADV。**只改变时序算子与 ADV 的窗口，公式中的算术常数保持不变**，例如 `sum(close,8)/8` 在 0.8 倍率下是 `sum(close,6)/8`，不是六日均价。因此这叫算子窗口扰动，而非纯均线周期优化。

2010—2012 为开发描述区间，跨入 2013 的收益区间被剔除；2013 为本项目保留评估区间。不按 2013 选择赢家，全部候选均报告。原公式 2016 年公开且可能已在 2013 年数据上开发，所以这里不是对原始因子的真正事前样本外证明。候选配置是在本项目首次回测前固定，未作第三方公开预注册。

## 实际结果

{md_table(reference)}

以上是不同样本与执行条件下的描述性对照，**不是统计上的通过/失败同口径检验**。完整的分位数、相关性和回归见 [机器可读结果](paper_comparison.json)。尤其是相关性均值接近，并不代表收益、每个因子的表现或所有 101 个因子都复现了。

![论文参考对比](figures/paper_comparison.png)

{md_table(table)}

完整 0/5/10 bps、开发期与保留期、每个因子的结果保留在 [metrics.csv](metrics.csv)，共 {len(metrics):,} 行；未只挑选获利的因子。各候选使用同一诊断股票池。

![参数敏感性](figures/parameter_sensitivity.png)

## 我从差距中得到的理解

1. **表达式不是可交易策略的全部。** 相同的公式，经过不同股票池、排名约定、持仓映射和执行延迟后，会形成不同收益。实现通过测试不能证明实证达到原文。
2. **量纲检查能发现有价值的问题。** 原文 ADV 定义为美元成交额，但 Alpha7 与成交股数比较。在本基线中，Alpha7 虽然信号覆盖率为 {alpha7.mean_signal_coverage:.1%}，实际仅 {int(alpha7.active_days)} / 1006 天有持仓。大量相同常数在去均值后变成现金。完整的数组并不等于有效交易信号。
3. **成本比一个漂亮的毛 Sharpe 更接近交易现实。** 日换手较高时，即使每单边只有几个基点，平均年化成本也会超过平均毛收益；这不是说每个因子都在同一成本下亏损。这里没有内部交叉抵消交易，所以等权因子组合的成本采用各独立子组合成本加总；不能据此断言原论文的实际组合无法获利。
4. **接近一个数字不等于接近研究结论。** 相关性均值相似可能掩盖不同的分布、极值和因子集合，必须同时看收益、换手、相关矩阵和覆盖率。
5. **参数改变不应被包装成改进。** 六组候选差异是敏感性结果；若只发布最好的窗口，会高估稳定性。这里保留所有候选，没有用负收益的绝对值做回归，也没有删掉不赚钱的因子。

![成本与换手](figures/cost_and_turnover.png)

## 论文统计关系的复核

{md_table(pd.DataFrame(regression_table, columns=['回归', '有效样本', '排除数', 'R²', '系数']))}

对数收益回归只包含正日均收益因子；当前非正均值收益因子数为 {stats['n_nonpositive_mean_returns']}，明确排除而不取绝对值。因此回归同样存在选择条件，不能与原文全为正收益的 101 个因子直接等价。相关性回归的两个因子对解释变量进一步去均值，因此截距等于样本平均相关性；这不改变斜率与 R²，但属于本项目的额外中心化约定。因子对并不独立，常规 OLS 的 p 值只能作为描述输出，不能当作稳健推断。

![因子收益相关矩阵](figures/factor_correlation.png)

## 还差什么，怎样继续

要进一步接近原始口径，需要可核验的历史真实 VWAP、逐日实际成交美元额、市值、时点行业层级、成员变动与退市处理。拿到数据后，可通过统一 CSV/Parquet 接口和严格审计命令重新运行，不需要重写 101 个公式。即使字段齐全，原作者未公开的股票池和交易配置仍然阻止逐点精确复制。

软件方面的后续重点应是外部独立实现对照、更细的执行和容量模型，以及未参与原始因子开发的后续时间段。这里不会通过反复试 2013 年参数来宣称完成任务。

## 重现证据和参考

- [实验配置](../configs/experiment.json)、[运行清单与版本/哈希](run_manifest.json)、[数据审计](data_audit.json)、[逐因子覆盖情况](factor_coverage.csv)。
- [三个因子的手算与理解](../docs/understanding.md)、[数据接口](../docs/data_contract.md)。
- [Kakushadze, 101 Formulaic Alphas, v3](https://arxiv.org/pdf/1601.00991)，数学表达式、样本期与表 1—5。
- [Nasdaq WIKI 数据说明](https://data.nasdaq.com/databases/WIKIP)、[本次使用的历史镜像](https://www.kaggle.com/datasets/marketneutral/quandl-wiki-prices-us-equites)。

本报告由实际运行输出生成。执行耗时约 {manifest['elapsed_seconds']:.0f} 秒；性能依机器而异。作者视角是学习与复核，不虚构个人交易经历。
'''
    (REPORTS / 'research_report.md').write_text(text, encoding='utf-8')
    print('Wrote research_report.md, candidate_summary.csv and four figures')


if __name__ == '__main__':
    main()
