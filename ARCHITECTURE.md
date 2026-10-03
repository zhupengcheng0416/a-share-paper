# 三项目整合与零费用部署

主链路：时点一致的已收盘 A 股行情/元数据 → 两个股票池 → V3 支撑阻力 + AlphaMaster 特征/公式 + PA_Agent 客观结构事实 → 固定规则与风险预算 → 决策快照 → 富途模拟订单生命周期 → 邮件反馈。

## 实际接入的上游模块

| 项目 | 接入内容 | 当前验证范围 |
|---|---|---|
| Detect_support_and_resistance_levels | 原版 SREngine/V3Fusion、ATR、因果枢轴、成交量剖面 | 320根合成日线检测；不移植未验证的胜率标定文件 |
| AlphaMaster | 原版65个特征、词表版本、StackVM算子与公式执行 | 因果前缀测试；CPU有界因子搜索，训练/验证/保留测试分段 |
| PA_Agent | 原版已收盘快照、EMA/ATR、K线几何、市场结构辅助事实 | 无界面运行；程序客观依据接入；LLM调用0次 |

`upstream-lock.json` 固定具体提交和每份来源文件 SHA256。所选源码及原始许可证保存在 `vendor/`；PA_Agent 工具包有一处记录过的修改：EventBus 改为按需导入，避免云端计算加载 Qt。其余接入源码未修改。派生源码随工程完整提供；保留各上游 GPL/AGPL 许可证。

`paper/integrations.py` 支持批量分析及SQLite完整输入/决策留档。输入仍使用原来的文件协议；新增要求：至少260根完整日线、每根 `closed:true`、`adjust_mode` 为 `hfq_point_in_time` 或 `qfq_asof_session`。调整口径必须由数据适配器实际验证，字段标签不能代替数据核验。禁止将当前前复权快照作为历史时点回测数据。

`paper/mining.py` 提供免费CPU有界搜索：使用上游特征和算子，最多256个候选；训练筛选前10，验证选一个，独立测试只评价一次；分段间清除5根。目标是信号当日之后的次日开盘到再下一交易日开盘收益。输出是预测相关系数，不是交易回测收益。上游完整强化学习训练器保留源码，但未接入云端任务；其原生多空/期货收益评价不能直接用于A股。当前搜索是单只输入股票研究，未宣称全市场挖掘完成。

所有挖掘产物默认 `research_only`，禁止自动晋升为可交易模型。读取公式核对词表、上游提交、冻结日期；缺失模型仍显示65特征已计算，但没有模型信号。整合扫描把原规则 ENTRY 记录为 `base_signal`，研究阶段输出 WATCH，禁止将未回测的附加因子直接交给券商执行。

## 如何运行

在工程根目录，Python3.12 CPU环境：

```text
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-research.txt
python -m unittest discover -s tests -v
node tests/test_worker.mjs
python -m paper.integrations --input validated-session.json --output state/report.json
python -m paper.mining --input one-symbol-history.json --output state/research-factor.json --limit 192
```

因子搜索至少700根有效日线。不存在行情文件时运行失败，不会自动补合成行情。合成数据只存在测试代码内。

## 免费云端拆分

- Cloudflare Workers：状态控制页、鉴权与富途 REST 只读连接。云端刷新令牌和读取A股模拟账户已实测成功；当前授权仅 `quote:read`，没有下单验证。
- GitHub Actions：准备了公开仓库标准 Ubuntu runner 的手动验证工作流，固定20分钟超时，无付费模型、无大规格runner、无缓存和artifact上传。公开仓库标准runner计算免费；当前无可用自有仓库，所以工作流尚未上线。官方依据：https://docs.github.com/en/billing/concepts/product-billing/github-actions
- 整套PyTorch和Python支撑阻力引擎不能直接在普通Workers运行。Workers限制：https://developers.cloudflare.com/workers/platform/limits/
- 免费行情、财报公开日期、行业/市值历史覆盖仍需核验，不能用收费行情补齐。完整市场计算耗时与额度尚未实测，超预算时暂停。

## 原功能交付状态

已实现：双股票池规则、缺失数据拦截、基本选股规则、风险预算/熔断模块、三个项目的研究接入、快照留档、富途云端只读连接、可上传的免费云端验证工作流。

未完成：真实全市场数据适配与覆盖统计；策略参数/收益回测；A股T+1/涨跌停/费用/滑点完整撮合；EXIT、部分成交与断线对账；邮件outbox投递；模拟订单写权限和自动下单；电脑关机后的定时任务部署。当前没有任何模拟或真实订单提交。
