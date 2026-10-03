# A股量化模拟盘 · 三项目整合版

控制端：https://a-share-paper-control.zhupengcheng0416.workers.dev

2026-10-03：已接入所指定的三个GitHub项目的分析模块，并完成合成数据联调。Cloudflare直连富途REST只读授权和A股模拟账户读取已实测成功。当前没有实时全市场数据、自动模拟交易或邮件投递；没有订单提交。

## 原需求与架构

- 科技股与总市值≤70亿元两个股票池，记录行业、市值、财报公开日期及数据来源。
- 固定版本的规则与模型；不让大模型临场决定交易。
- 排除ST、停牌、新股和低流动性；缺失/无效/未来数据阻断。
- 风控预算、现金占用、重复订单键、熔断与完整SQLite决策快照。
- 仅允许SIMULATE，预算0元，不启用付费模型/行情/服务器。
- 最终目标为电脑关机后云端运行，邮件发往zhupengcheng0416@163.com。

详细模块、免费云端拆分、接口及未完事项见 [ARCHITECTURE.md](ARCHITECTURE.md)。其中不移植未验证的上游胜率，也不把原来的期货多空逻辑当作A股交易回测。

## 当前可运行功能

`paper/integrations.py`：原版V3Fusion支撑阻力、AlphaMaster65特征与冻结公式、PA_Agent已收盘K线客观结构事实；批量研究与快照留档。研究信号不会提交订单。

`paper/mining.py`：CPU有界特征/算子搜索，最多256候选，训练/验证/独立保留测试分段；输出预测相关系数和不可交易的研究产物。完整强化学习训练尚未接入。

`paper/core.py`：原选股规则与风险预算；`config.json` 除模拟范围、零费用要求和70亿元边界外仍为工程草案，未经收益回测。

`cloudflare/worker.mjs`：鉴权控制端、富途云端只读预检。令牌保存在Cloudflare加密secret，不在交付包内。

`.github/workflows/research.yml`：免费公开仓库标准Ubuntu runner手动验证工作流，尚未发布到用户自有仓库；无付费模型调用、无付费runner、无artifact上传。

`vendor/`、`upstream-lock.json`、`LICENSE`、`NOTICE.md`：上游来源、锁定提交、源码哈希、许可证及一处无界面适配修改记录。

## 验证与运行

Python3.12，工程目录执行：

```text
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-research.txt
python -m unittest discover -s tests -v
node tests/test_worker.mjs
python -m paper.service check
python -m paper.integrations --input validated-session.json --output state/report.json
python -m paper.mining --input one-symbol-history.json --output state/research-factor.json
```

17项Python测试与8项Worker检查通过。测试使用明确标记的合成数据，不代表真实全市场或券商成交验证。

输入包含dataset_kind=completed_session、session、source、coverage、stocks。每只股票含code/name/industry/market_cap_cny/is_st/suspended/listing_days/roe/fundamental_asof/session/source/adjust_mode/bars；每根日线含date/open/high/low/close/volume/turnover_cny/closed。分析至少260根，挖掘至少700根；fundamental_asof须为公开可获得日期，复权口径须有时点证据，子集不能称为全市场。

## 待部署条件

先提供自有免费公开GitHub仓库地址，再上传源码和配置云端任务。随后接真实免费行情并验证完整市场覆盖、策略回测、A股T+1/涨跌停/成交费用、EXIT与订单对账、邮件outbox、模拟写权限及小规模干跑。

`deploy/`、`paper/futu_gateway.py` 保留早期Linux/OpenD方案作为参考，当前不要求购买或申请VM，不沿用Oracle注册路径。主要路线为Cloudflare REST控制端+免费Python云端运行器。
