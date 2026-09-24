# Autonomous Software Factory

> 把「目标」变成「验证通过的应用」——自治软件创业工厂（V3 核心）。

Autonomous Software Factory 是一个**任务图驱动**、带**独立验证系统**的编码工厂。它实现了"自治软件公司"架构蓝图的 V4 核心：Market Scout 从互联网信号中收割机会候选，PM 写出 PRD，Architect 将其拆成任务图（DAG），工厂再拉起相互隔离的编码 Agent，用确定性的机器闸门验证每一次改动，由独立评审 Agent 把关，失败自动修复，**只有真正通过验证的代码才会合并进 `main`**——绝不静默合入、不无限重试、每一分花费都有据可查。

设计哲学是 **Agent 组织 + 持久化工作流 + 独立验证系统**，而不是"一个万能 Agent 包办一切"。编码（coder）、验证（verifier）、评审（reviewer）、预算（budget）等角色彼此隔离，**没有任何单一 Agent 掌握最终真相**。

## 核心特性

- **任务图驱动编排** —— 从 JSON/YAML 任务图出发，完成 DAG 校验、环/依赖检查、拓扑排序与就绪任务调度。
- **Git worktree 隔离** —— 每个任务从 `main` 快照出独立 worktree；编码 Agent **只能**在自己的 worktree 内写文件（由策略强制，而非约定）。
- **独立机器验证闸门** —— 按 `syntax` → `test` → `lint` 顺序执行；闸门 **fail-closed**（出现未注册的闸门名直接判失败，绝不静默跳过）。
- **规则隔离的评审 Agent** —— 评审者独立检查规格、diff、闸门与测试；编码产物为空或失败时一律 REJECT，绝不合并。
- **带硬上限的修复循环** —— 验证/评审失败自动触发修复，受 `FACTORY_MAX_RETRIES`（默认 3）封顶；重试耗尽的任务进入 `BLOCKED`，永不挂死。
- **最小权限权限引擎** —— 基于角色的 allow-list，**默认拒绝**；编码 Agent 无网络、无 secrets、无生产访问。
- **预算护栏** —— 任务级 token 与墙钟运行时长预算；预算耗尽立即硬阻断；挂起的编码调用由单次尝试超时（默认 300 秒）回收。
- **崩溃恢复** —— 状态持久化在 SQLite（或 PostgreSQL）；被中断的任务下次运行时自动复位为 `READY` 并续跑，绝不滞留为永久 `BLOCKED`。
- **审计账本** —— 每次编码尝试（token + 运行时长）都镜像写入持久的 `BudgetLedger`，并带项目级账户。
- **里程碑推进** —— `factory promote` 仅在项目完全构建、全部任务 DONE、全部评审 APPROVE 时沿状态机推进至 `PRODUCTION`，每一步落审计行；中途崩溃可从已到达阶段续推。
- **CI 就绪的退出码** —— `factory run` 仅在任务图完整执行（`DONE`）时返回 `0`；任何 `BLOCKED` / 部分产物返回 `1`。
- **PM Agent（V2）** —— 把自然语言问题描述转化为结构化 PRD（`factory plan` 第一步），支持显式约束与验收标准。
- **Architect Agent（V2）** —— 把 PRD 拆解为可直接运行的任务图（DAG），带文件白名单，面向真实代码包（`factory plan` 第二步）。
- **`factory plan` CLI（V2）** —— `factory plan "<目标>"` 一条命令跑完 PM → Architect，产出 `prd.md` + `task_graph.json`，直接喂给 `factory run`。
- **按账户隔离的审计账本（V2 加固）** —— 预算唯一约束按账户隔离，多项目不再冲突；旧库幂等迁移。
- **Market Scout Agent（V3）** —— 从互联网信号收割机会候选；可插拔后端：`recipe`（确定性、免 Key）、`web`（真实 Reddit/GitHub 公开 API + 防御性超时降级）、OpenAI（设 `OPENAI_API_KEY` 启用）。
- **`factory scout` CLI（V3）** —— `factory scout [--backend recipe|web]` 产出 `opportunities.json` + `opportunities.md`；`factory scout --plan` 对选中候选跑 PM → Architect，打通 scout → plan 闭环。
- **Validation Engine（V4）** —— 产品评审闸门：确定性证据门（低于阈值 → `KILL`）、便宜实验门（无转化数据 → `TEST`；低于阈值 → `KILL`）、Devil's Advocate 反对意见与 Judge 综合决策（decision + confidence + evidence）。
- **`factory validate` CLI（V4）** —— `factory validate opportunities.json` 产出 `validations.json` + `validations.md`；支持 `--opp`、`--evidence-threshold`、`--conversion-threshold` 与可重复 `--conversion opp_id=0.083` 喂入模拟实验结果。
- **Deployment Agent（V5）** —— 阶梯发布 `STAGING_SMOKE → SECURITY_GATE → PERF_GATE → CANARY_1/5/25/100 → LIVE`；gate 失败或金丝雀 error/latency/conversion 回退时自动回滚。
- **`factory deploy` CLI（V5）** —— `factory deploy deployment_config.json` 产出 `deployments.json` + `deployments.md`（阶段、决策 `LIVE` / `ROLLED_BACK`、失败阶段与原因）。
- **Analytics Agent（V5）** —— 把遥测（traffic / signup / activation / retention / errors / support / feature requests / revenue / infra cost）转成 signals、issues 与 recommendations（`Bug` / `Feature` / `Experiment` / `Optimization` / `Scale` / `Kill`），重新进入 Planner → Coding 闭环。
- **`factory analyze` CLI（V5）** —— `factory analyze metrics.json` 产出 `analytics.json` + `analytics.md`，带总体健康度（`good` / `degraded` / `critical`）。

## 架构

```
PRD + 任务图 (DAG)
        │
        ▼
┌────────────────────── SOFTWARE FACTORY ──────────────────────┐
│                                                              │
│   ┌────────┐   ┌────────────┐   ┌──────────┐                 │
│   │ coder  │ → │  verifier  │ → │ reviewer │   修复循环       │
│   │(预埋缺陷│   │ 机器闸门    │   │ 规则隔离  │   FAIL ──────┐  │
│   │ 演示用) │   │            │   │          │              │  │
│   └───┬────┘   └─────┬──────┘   └────┬─────┘              │  │
│       │  只允许写 worktree            │                    │  │
│       ▼                              │                    │  │
│  worktree（基于 main 快照）───────────┘                    │  │
│        │                                                    │  │
│        └────────── 通过后 ──► 合并进 main ◄────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

每一次状态迁移都受 **策略 + 证据 + 闸门** 三重把关。数据库（project / task / review / run / budget）是唯一事实来源，重要状态从不依赖聊天记录。

## 快速开始

环境要求：Python **3.11+**。

```bash
# 1) 安装
pip install -e .

# 2) 初始化数据库（默认本地 SQLite ./factory.db）
factory init-db

# 3) 查看某个角色的权限边界
factory policy coder

# 4) 运行内置端到端演示
#    （T001 被刻意预埋了一个缺陷——流水线必须通过验证发现并修复后才能合入）
factory demo

# 5) 查询项目的持久化状态
factory status p_demo_calc

# 6) 将完全构建 + 全部评审通过的项目推进到 PRODUCTION
factory promote p_demo_calc

# 7) 从自定义任务图运行你自己的项目
factory run <task_graph.json> --prd <prd.md>

# 8)（V2）把问题描述变成 PRD + 任务图，然后直接运行
factory plan "做一个带持久化的 CLI 待办应用" --out-dir examples/my_plan
factory run examples/my_plan/task_graph.json --prd examples/my_plan/prd.md

# 9)（V3）侦察互联网信号，产出机会候选
factory scout --backend recipe --out-dir examples/v3_scout
factory scout --backend web --out-dir examples/v3_scout   # 真实 Reddit/GitHub 信号

# 10)（V3）侦察 + 规划一条命令打通（对候选跑 PM → Architect）
factory scout --plan --out-dir examples/v3_scout --plan-out-dir examples/v3_scout/plan

# 11)（V4）验证侦察到的机会（证据门 → TEST/KILL）
factory validate examples/v3_scout/opportunities.json

# 12)（V4）喂入模拟的便宜实验结果以到达 BUILD
factory validate examples/v3_scout/opportunities.json --conversion opp_xxx=0.083

# 13)（V5）发布验证通过的产品（阶梯发布 + 自动回滚）
factory deploy deployment_config.json

# 14)（V5）把用户遥测转成下一轮迭代输入
factory analyze metrics.json
```

> **退出码契约**：`factory run` 仅在所有任务都达到 `DONE` 时返回 `0`；任何 `BLOCKED` 或部分产物返回 `1`——可以直接接入 CI 判定。

## 示例任务图

```jsonc
// examples/sample_project/task_graph.json
{
  "project_id": "p_demo_calc",
  "name": "Sample Calculator Service",
  "tasks": [
    { "id": "T001", "title": "implement sample_app package with tests",
      "dependencies": [], "meta": { "target": "all" } },
    { "id": "T002", "title": "harden test suite (regression guard)",
      "dependencies": ["T001"], "meta": { "target": "tests" } }
  ]
}
```

每个任务都可以携带 `acceptance` 验收标准与 `files` 文件白名单。编排器解析依赖、调度就绪任务，并且**只有**验证闸门通过且评审 APPROVE 的任务才会被合并。

## 测试与静态检查

```bash
python -m pytest tests -q          # 170 passed, 1 skipped（v5.0.0，Py3.11 实测）
python -m ruff check factory tests # 确定性 lint 基线：0 告警
```

覆盖范围：任务图校验（含 UTF-8 BOM 兼容）、状态机、权限策略、预算（token + 运行时长，耗尽 → 硬 `BLOCKED`）、验证管线、崩溃恢复（中断任务自动复位续跑）、审计账本、执行墙钟护栏、fail-closed 闸门、里程碑推进（资格校验 + 断点续推）、完整 E2E（预埋缺陷 → 修复 → 合并 → `main` 最终自洽），以及 scout 后端（recipe/web/非法名）、scout→plan 管线、WebBackend 降级、Validation Engine 闸门（证据/KILL、无数据 TEST、转化 BUILD/KILL、Devil's Advocate 反对意见、CLI 契约）、Deployment 阶梯（gate 失败/金丝雀指标回退 → 自动回滚、CLI 契约）、Analytics 规则引擎（健康判定、issue/recommendation 产出、CLI 契约）。

CI（`.github/workflows/ci.yml`）在 Python 3.11 / 3.12 上运行：`ruff check` + `pytest --cov=factory`。

## 上线护栏（CI 契约）

- **退出码即结果** —— 只有整个任务图 `DONE` 才视为绿；任何其他结果都是非零退出码。
- **绝不静默合入** —— 未通过验证/评审的代码永远不会进入 `main`；修复循环由 `FACTORY_MAX_RETRIES` 封顶。
- **预算兜底** —— `FACTORY_RUNTIME_BUDGET_S` 在每次编码尝试**开始前**预检；预算耗尽立即 `BLOCKED`，绝不空转。
- **空产物安全** —— 编码输出为空或失败时，评审以「声明文件缺失」REJECT，最终进入 `BLOCKED`，绝不产出半成品。
- **墙钟护栏** —— `FACTORY_ATTEMPT_TIMEOUT_S` 限定单次编码尝试上限；挂起的 LLM 调用被回收为预算事件。
- **验证门 fail-closed** —— `FACTORY_VERIFY_GATES` 中出现未注册的闸门名时直接判失败（宁可红灯，绝不假装"已验证"）。
- **崩溃可恢复** —— 任务在 `IN_PROGRESS` / `WAITING_VERIFY` / `VERIFY_FAILED` / `WAITING_REVIEW` / `REVIEW_REJECTED` / `BLOCKED` 任一状态中断后，下一次 `factory run` 会将其复位为 `READY` 重跑。
- **花费可审计** —— 每次编码尝试（token + 运行时长）都落入 `BudgetLedger`，并带项目级账户。
- **推进有据** —— `factory promote` 仅在「项目存在、所有任务 DONE、所有评审 APPROVE」时推进；每一步写 `kind=PROMOTE` 审计行。
- **基线可复现** —— ruff 规则集（E4/E7/E9/F/I，行宽 120）固化在 `pyproject.toml`，CI 可用同一命令复验。

## 目录结构

```
autonomous-factory/
├── factory/                 # 核心实现
│   ├── cli.py               # typer CLI（init-db / run / demo / status / policy / promote）
│   ├── config.py            # 环境变量驱动的配置
│   ├── db.py                # SQLAlchemy 引擎与会话管理
│   ├── orchestrator.py      # worktree 隔离流水线主循环
│   ├── state_machine.py     # 项目/任务状态机 + 迁移表
│   ├── verifier.py          # syntax / pytest / lint 机器验证闸门
│   ├── policy.py            # 最小权限权限引擎
│   ├── budget.py            # token + 运行时长预算追踪
│   ├── safety.py            # id / 路径安全检查
│   ├── execution.py         # 墙钟单次尝试护栏
│   ├── agents/              # base（契约）/ coder / reviewer / registry
│   ├── models/              # Project / Task / Review / Run / Budget ORM
│   ├── schemas/             # Evidence / Risk / AgentOutput / TaskGraph
│   └── workflows/           # DevelopmentWorkflow（持久化、可续跑、promote）
├── examples/sample_project/ # 内置 PRD + 任务图演示
├── tests/                   # 单元 + E2E 测试套件
├── factory_runtime/         # 运行时工作区（worktree 与产物，git 忽略）
└── .github/workflows/       # CI 流水线
```

## 配置说明

所有配置都由环境变量驱动，每个变量都是可选的（有合理的本地默认值）。密钥只能来自环境——绝不能写进代码。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `FACTORY_DATABASE_URL` | `sqlite:///./factory.db` | 持久化状态存储。生产环境可指向 PostgreSQL：`postgresql+psycopg://user:pass@host:5432/factory` |
| `FACTORY_WORKSPACE` | `./factory_runtime` | 项目 worktree 与运行产物的存放位置 |
| `FACTORY_MAX_RETRIES` | `3` | 每个任务的最大修复次数，超出后硬 `BLOCKED` |
| `FACTORY_TOKEN_BUDGET` | `120000` | 任务级 token 预算 |
| `FACTORY_RUNTIME_BUDGET_S` | `1800` | 任务级墙钟运行时长预算 |
| `FACTORY_ATTEMPT_TIMEOUT_S` | `300` | 单次尝试墙钟上限（挂起的 LLM 调用会被回收） |
| `FACTORY_VERIFY_GATES` | `syntax,test,lint` | 逗号分隔、按顺序执行的验证闸门；未知名称 fail-closed |
| `FACTORY_ISOLATION` | `worktree` | 每项目/每任务沙箱的隔离模式 |

可直接复制 `.env.example` 作为配置模板。

### 接入真实 LLM 后端

默认情况下，编码 Agent 使用确定性的进程内 `RecipeBackend`——非常适合演示与 CI，零外部依赖。要让工厂接入真实模型，安装 `llm` 扩展并设置 OpenAI 兼容变量：

```bash
pip install -e ".[llm]"

export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini
```

一旦设置了 `OPENAI_API_KEY`，编码 Agent 就会改用 OpenAI 兼容后端，不再使用 recipe 后端。密钥只放在你的环境变量里，绝不提交进仓库。

## 项目状态

- **v5.0.0** —— V5 发布：Deployment Agent（阶梯发布 `STAGING_SMOKE → SECURITY_GATE → PERF_GATE → CANARY_1/5/25/100 → LIVE`，gate 失败或金丝雀 error/latency/conversion 回退时自动回滚；`factory deploy` CLI）+ Analytics Agent（遥测 → signals / issues / recommendations `Bug` / `Feature` / `Experiment` / `Optimization` / `Scale` / `Kill` 重新进入 Planner → Coding；`factory analyze` CLI，健康度 `good` / `degraded` / `critical`）。
- **v4.0.0** —— V4 发布：Validation Engine 把 scout 机会候选转成 BUILD / TEST / KILL 决策——确定性证据门 + 转化门、Devil's Advocate 反对意见、Judge 置信度；`factory validate` CLI（validations.json/.md，`--conversion` 喂入模拟实验）。
- **v3.0.0** —— V3 发布：Market Scout Agent（`factory scout`），recipe/web/OpenAI 三种后端，WebBackend 真实抓取 Reddit/GitHub + 防御性降级，`factory scout --plan` 打通 scout → plan 闭环（opportunities.json → PRD + 任务图）。
- **v2.0.0** —— V2 发布：PM Agent（问题描述 → PRD）、Architect Agent（PRD → 任务图）、`factory plan` CLI、按账户隔离的预算账本唯一约束 + 旧库幂等迁移。`factory plan "<目标>"` 产出的 PRD + 任务图可直接喂给 `factory run`。
- **v1.0.0** —— V1 核心发布：任务图工厂、worktree 隔离、机器验证闸门、评审、预算护栏、崩溃恢复、审计账本、里程碑推进、CI 退出码契约、可插拔 LLM 后端，并附正式路线图（`docs/ROADMAP.md`）与变更日志（`CHANGELOG.md`）。
- V5 之后的路线图（Portfolio CEO）见 [docs/ROADMAP.md](docs/ROADMAP.md)。本仓库交付的是"工厂"本身；每个路线图阶段以打 tag 的大版本形式发布。

## License

以 [MIT License](LICENSE) 发布。
