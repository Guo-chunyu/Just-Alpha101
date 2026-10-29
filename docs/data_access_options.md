# 2010—2013 严格数据的可验证访问选项

核对日期：2026-10-29。仅使用供应商、交易所及 WRDS 的官方资料；这是访问与字段证据记录，不是已取得数据或严格复现成功的声明。未注册、购买、登录付费账户或下载受限数据。

本次定向核对未找到**当前已获授权且公开可直接取得的完整数据组合**，能同时满足真实成交量加权价、成交美元额、当时可得的历史市值、历史行业分类和退市覆盖。下面的候选需要授权数据导出及进一步核验；公开说明页和少量样本不等于全历史访问权。

## 字段到来源

| 必需字段/证据 | 官方支持的候选 | 已验证与未验证的边界 |
|---|---|---|
| 每笔成交价、股数、时间、市场、sale condition；由此生成真实 `dollar_volume`、`vwap` | NYSE Daily TAQ，直接授权或经 WRDS | 官方说明覆盖 CTA/UTP 综合行情，历史始于 1993；交易记录含价格和数量。2010—2013 在产品历史范围内。需取得实际文件，并按对应年份规范处理条件、撤销/更正和交易时段；尚未核验实际样本与权限。 |
| 历史价格、股份数、公司行动、稳定证券标识、退市事件 | CRSP US Stock，经 WRDS | 官方 CRSP 页面确认历史标识、价格/量、分配、股份数和退市资料。需获取日度数据、历史股份观察与生效区间、证券名称/行业历史、退市文件，并核对单位和多股类口径。历史记录存在不自动证明所有字段是当时可见的数据版本。 |
| TAQ 与 CRSP 按日期连接 | WRDS Daily TAQ–CRSP link | 2022-02 的官方链接说明覆盖 2003 起，要求同时订阅两库，以 symbol root/ticker 和 suffix/share class 配对。需保留未匹配记录、改名和多股类审计，不能仅凭当前 ticker 拼接。 |
| 历史 SIC / 行业中性化标签 | CRSP 历史 SIC 是候选 | 官方资料支持 SIC 历史，不等于已核实“发布时间当时可得”。需要发布/修订证据或允许的数据版本口径。SIC 也不能自动替代原论文的三层行业分类；另造映射必须明确披露。 |

上述前三行的依据：[NYSE Daily TAQ 事实表（2022）](https://beta.nyse.com/publicdocs/nyse/data/Daily_TAQ_Fact_Sheet.pdf)、[NYSE Daily TAQ 产品页](https://beta.nyse.com/data-products/catalog/daily-taq)、[NYSE Daily TAQ 规范 v4.0（WRDS 官方托管）](https://wrds-www.wharton.upenn.edu/documents/1967/Daily_TAQ_Client_Spec_v4.0.pdf)、[CRSP 官方 WRDS 介绍/演示页](https://wrds-www.wharton.upenn.edu/demo/crsp/form/)、[TAQ–CRSP 链接说明 v1.1（2022-02）](https://wrds-www.wharton.upenn.edu/documents/1336/NYSE_Daily_TAQ_to_CRSP_Linking_BPNFjWm.pdf)。

访问要求：WRDS 学术账户依托订阅机构及相应账户资格，不能由“公开网页可访问”推断已获数据使用权；TAQ 与 CRSP 的订阅也需分别确认。[WRDS 账户类型](https://wrds-www.wharton.upenn.edu/pages/about/wrds-account-types/)、[NYSE 学术客户说明](https://beta.nyse.com/market-data/academics)。本会话没有提供这些授权或数据导出。

## Massive（原 Polygon）：行情候选，不能直接认证 PIT 元数据

- 官方说明：上市美股 bars/trades/quotes 的档案始于 2003-09-10；Basic 为两年 bars、Starter 五年、Developer 十年，Advanced/Business 才有完整档案。因滚动窗口，当前十年权限不足以覆盖 2010—2013；OTC 档案仅自 2021-12-31。需要对应许可和 API key，并验证停牌、退市、转 OTC 的实际覆盖。[历史覆盖及权限](https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have)。
- 日 bars 响应提供 `v` 和可选 `vw`。这是 VWAP 的直接字段候选，但必须核对成交筛选、交易时段和调整口径；不能未经验证将不同口径的 `v × vw` 当作真实美元额。[Custom Bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars)。
- Ticker Overview 提供 `market_cap`、股份数、SIC、`active`、`delisted_utc` 及 `date` 参数。但文档明确说明 SEC 字段按 **period of report** 匹配：7 月 31 日提交、报告期为 6 月 29 日的材料会进入 6 月 29 日查询。这允许使用后来披露的信息，不能以 `date` 参数证明 PIT；老日期还可能为空。需另有按 filing/publication date 可用的股份和分类证据。[Ticker Overview](https://massive.com/docs/rest/stocks/tickers/ticker-overview)。
- All Tickers 支持非活跃证券；这只是发现退市证券的机制，尚不证明目标历史全量覆盖或含完整退市回报。[All Tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers)。

## Nasdaq 历史 intraday：本次未确证目标年份可取得

现行 Nasdaq 官方产品页将 Historical TotalView-ITCH 描述为订阅者通过安全网站/SFTP 获取的 Nasdaq 订单和成交档案，并写明始于 **2014**。它不是已证明覆盖所有交易场所的美国综合成交源。[现行 Nasdaq 股票数据产品页](https://www.nasdaq.com/products/data/equities/nasdaq)。

搜索索引中的旧官方 ITCH FAQ 曾列出 4.0（2009 起）及 4.1（2010 起）档案；但本次直接打开该 PDF 已重定向至 Nasdaq Data Link NTV 页面。因此旧索引只能提示可能存在旧档案，不能认证当前 2010—2013 的可交付范围或访问权。需要供应商明确确认旧版本、月份、场所范围及许可。[旧 FAQ 地址](https://www.nasdaqtrader.com/Content/TechnicalSupport/FAQs/ITCH_FAQ.pdf)、[当前重定向产品](https://data.nasdaq.com/databases/NTV)。

## 未来开展严格数据研究所需的材料

1. 已获许可的 TAQ + CRSP（含链接和历史描述/退市文件）导出，或能够逐项证明相同字段与历史覆盖的其他合法导出；范围需包括 2010—2013 以及评估前的 500 个 XNYS 交易日。
2. 来源、数据版本、下载日期、覆盖股票及排除记录、价格/量单位和复权规则；成交聚合规则；历史股份和分类的生效及可用时点证据。
3. 退市、IPO、换码、合并、多股类及未匹配记录的处置依据。对动态成员池还需项目现有严格完整面板检查之外的明确适配，不能为通过检查填造 IPO 前记录。

用户已确认没有额外授权数据库，当前交付保留公开数据研究版本并明确差距。未来如果获得授权导出，再按以上材料开展审计。仅购买一个标称“历史数据”的套餐，也不足以自动消除行业分类、信息时点或退市缺口。本次没有找到可立即替代这些输入的公开完整数据，不应修改现有 provenance 为 true，也不应使用 OHLC 均价、收盘价乘量或当前分类来冒充严格数据。
