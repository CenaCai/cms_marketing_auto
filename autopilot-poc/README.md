# Autopilot PoC — 营销 Agent 本地编排骨架

> 对应交付：《营销 Agent 合并规格 v1.0》§5 端到端主流程（L0–L7）的**最小可跑切片**。
> MVP 渠道裁定（附录 D，2026-09-07 用户裁定）：**email 为主、短信预留接口、email 调起 LP 承接转化**。

---

## 一、这个 PoC 到底是什么意思（大白话）

设想你有一个「营销副驾驶」：你用大白话告诉它「我要给哪群人、推什么、达到什么目标」，
它帮你把这句话**编译成 Mautic 能直接跑的自动化流程图**，并且**自动把合规/频次/归因这些
「容易忘、忘了就出事」的管控塞进流程图里**，最后生成一把「锁」（plan_hash）把
「你审批的那版」和「实际跑的那版」绑死——任何篡改执行引擎都拒跑。

它不是要取代 Mautic，而是坐在 Mautic 前面当「编排层」：
- **环境开关**：先在 `localhost:8080` 跑通，验证无误再切生产 `automarketing.cstsdevops.com`，绝不污染现有 campaign #27 / #42。
- **Goal Intake（目标输入）**：把你给的 Brief 解析成结构化目标 `GoalSpec`（谁能收、发什么渠道、目标指标、调起哪个着陆页）。
- **Plan Compiler（计划编译）**：把 `GoalSpec` 编译成带治理注入的事件图提案 `CampaignProposal`，算出 `plan_hash`，并打印「会发给 Mautic 的 API 调用」。

为什么是这三块？因为合规格里 L0→L7 七层栈，**L0（ Intake）和 L2（Compiler）是 Agent 产出物与
Mautic 之间的两个关键翻译边界**；环境开关则是「本地先验证、生产后上线」的安全闸。PoC 只做这条
最小链路，先证明 email 主渠道闭环能编译出来、能映射成 Mautic API。

---

## 二、目录结构

```
autopilot-poc/
├── config.json        # 环境开关：local(→localhost:8080) / prod(→生产)
├── goal_intake.py     # L0：Brief → GoalSpec（含 MVP 渠道默认值）
├── plan_compiler.py   # L2：GoalSpec → CampaignProposal（治理注入 + plan_hash）
├── run_poc.py         # 运行入口：串起三块，默认 dry-run
├── brief_example.json # 示例 Brief（UEFA EURO 2028 用例）
└── output/            # 编译产物（proposal_<goal_id>.json）
```

---

## 三、怎么在本地跑

```bash
cd autopilot-poc
python run_poc.py                 # 用示例 Brief，local 环境，dry-run（CLI 形态）
python run_poc.py --interactive   # 交互式填 Brief
python run_poc.py --env prod      # 切生产环境（需先填 config.json 凭证）
```

依赖：仅 Python 3 标准库，零第三方包。

## 三-B、活动驾驶舱（Web UI @ :8090，方案 A）

独立进程部署在 `:8090`，经 REST API 调用 `:8080` 的 Mautic（不直接碰 Mautic 库/UI）。

```bash
cd autopilot-poc
python cockpit.py                 # 监听 http://127.0.0.1:8090
python cockpit.py --port 8090 --host 127.0.0.1
```

页面（已美化 + 字段分层 + 多 campaign 自适应）：
- `GET  /`                 驾驶舱首页：Program 列表 + 新建入口
- `GET  /brief`            **运营只填业务意图**（目标/分群/语言/LP/KPI/预算/周期/分波数）；
                           Agent 自动决策项（渠道/频次闸门/护栏/治理注入/mtc*/plan_hash）以只读面板展示，运营不能改
- `POST /brief`            编译 → 生成 **Program（N 个 campaign，各不同策略）** → 跳转
- `GET  /program/<id>`     Program 流水线：各 campaign 状态/策略/事件图/审批/推送
- `POST /program/<id>/campaign/<cid>/approve`  单 campaign 审批门（plan_hash 绑定 + T2/T3/T4 + EXPIRED）
- `POST /program/<id>/campaign/<cid>/push`     单 campaign 推送（plan_hash 校验，无凭证则 dry-run）
- `POST /program/<id>/complete`                **标记某 campaign 完成 → 按达成率/退订率确定性改写下游**
                           （频次 / 内容变体 / 发送条件 / 落库 tag 分组），并重算 plan_hash
- `GET/POST /proposal/<id>`  遗留单 campaign 提案（run_poc 产出）的审批/推送

多 campaign 自适应规则（确定性、可审计，写入 program.changelog，不靠 LLM 临场发挥）：
- 达标（≥目标）：保持，略降本（降频）
- 未达标（≥50%）：提频 + 换内容变体 + urgency tag
- 乏力（<50%）：大幅提频 + 扩分组 tag(broaden/reengage) + 换内容
- 退订率超阈(>0.3%)：降频 + suppression tag（收窄）

新增模块：
- `approval_gate.py` — L3 审批门（plan_hash 绑定 + 分级 + 超时 EXPIRED，绝不默认批准）
- `mautic_client.py` — 经 `/s/api/v2` + `applyAction` 推送（Basic Auth，dry-run 感知）
- `adaptive.py` — 多 campaign 编排：Goal→Program(N 策略)，上游完成后确定性改写下游（频次/内容/条件/tag）+ 重算 plan_hash
- `plan_compiler.py` — 扩展 `compile` 吃 richer strategy（分群/内容变体/发送条件/落库 tag），事件图新增 `tag.write` 节点
- `cockpit.py` — `:8090` 服务（标准库 `http.server`，零依赖，含设计系统 + 字段分层）

### 在 Mautic `/s/campaigns` 里加入口（可选，零耦合）
在 Mautic 菜单加一项外链到 `http://localhost:8090/`，运营在 Mautic 内即可发现驾驶舱，
但逻辑/状态全在编排层，Mautic 升级不影响驾驶舱。


---

## 四、它验证了什么（email 主渠道闭环）

1. `channels=["email"]`、`reserved_channels=["sms"]` —— 主触达是邮件，短信只留占位节点（`enabled:false`）。
2. 邮件节点携带 `cta.landing_page_url` + 拼接 `mtc_campaign/wave/variant/locale` 的 `tracked_url` —— **email 内链接调起 LP 承接转化**，归因靠 `mtc_*` 反填（Mautic 无点击 webhook，见规格附录 B）。
3. 决策入口后确定性插入 4 类治理节点：护栏 → 频次闸门 → 锚点仲裁 →（业务）→ 渠道记账。
4. 输出 `plan_hash`，把审批内容与执行内容绑定。

---

## 五、已知边界（PoC 不做）

- L1 策略合成、L3 审批门、L5 观测、L6 复盘、L7 报告等层未实现（仅留接口/占位）。
- `--push` 的 HTTP 实现未展开；默认 dry-run 只打印 API 调用清单。
- 真实 Mautic 事件图写入须走 `applyAction`（普通 API 改不了事件图，见规格附录 B）。
- 凭证留空：本机 `localhost:8080/s/` 通常也需 Basic Auth，请在 `config.json` 填入。
