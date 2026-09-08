---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 82fdf17faf4e6add2f17f1ee6bc91211_6a7e9e02aaca11f18f50525400aeaaa3
    ReservedCode1: tk30iUHUiEk4/7Bn0c1m/rGDFtD3Ef+LWB7xi/LZy5J4o+fxisApI6zoNAF8nhl4D1w97xBrs2AwduoopA1KwO5Wmg9eEnOLuWD/7k2ZCcmg9Bm7l1s22eLDn3drL/CreaXTkWgwicgsMmkn53wWmJNr39qShxuCFhEctRUd2Gn/pM7WAFRt7RZy+nY=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 82fdf17faf4e6add2f17f1ee6bc91211_6a7e9e02aaca11f18f50525400aeaaa3
    ReservedCode2: tk30iUHUiEk4/7Bn0c1m/rGDFtD3Ef+LWB7xi/LZy5J4o+fxisApI6zoNAF8nhl4D1w97xBrs2AwduoopA1KwO5Wmg9eEnOLuWD/7k2ZCcmg9Bm7l1s22eLDn3drL/CreaXTkWgwicgsMmkn53wWmJNr39qShxuCFhEctRUd2Gn/pM7WAFRt7RZy+nY=
---

# Autonomous Software Factory (V1)

> 自治软件创业工厂 · 第一代核心：把「目标」变成「验证通过的应用」。

本项目实现 `D:\visua\111\项目文档.md` 中架构蓝图的 **V1 核心**：

- **数据库 schema**（SQLAlchemy ORM + SQLite）
- **Agent contracts**（统一的 `AgentInput` 输入契约与运行时注入后端）
- **状态机**（Project / Task 双态机 + 迁移表）
- **任务图**（DAG 校验、拓扑排序、就绪任务调度）
- **权限模型**（角色最小权限能力引擎，拒则默认拒绝）
- **第一版 orchestrator**（worktree 隔离 → coder → 机器验证 → 评审 → 修复循环 → 合并 main）

## 架构总览

```
PRD + 任务图(DAG)
      │
      ▼
┌────────────────── SOFTWARE FACTORY ──────────────────┐
│  ┌─────────┐   ┌──────────┐   ┌───────────┐         │
│  │  coder  │ → │ verifier │ → │ reviewer  │ 修复循环 │
│  │(注入缺陷│   │(语法/测试│   │(规则隔离)  │  FAIL→   │
│  │ 演示用) │   │ 机器闸门)│   │           │  重来    │
│  └─────────┘   └──────────┘   └───────────┘         │
│        │               只允许写 worktree                │
│        ▼                                             │
│   worktree(基于 main 快照隔离) ──通过后──► merge → main │
└──────────────────────────────────────────────────────┘
```

- **隔离**：每个任务从 `main` 快照出独立 worktree，`coder` 只能写 worktree（policy 强制）。
- **验证**：机器闸门（语法 + pytest）客观把关；测试失败自动触发 repair 循环。
- **许可**：角色能力 allow-list；`coder` 无网络、无 secrets、无生产访问。
- **持久化**：project / task / review / run / budget 账本全量落库；任务级 `detail`（含种子标记）与 `workdir` 每次执行即提交，崩溃后 `factory run` 自动复位中断态任务并断点续跑。

## 快速开始

```bash
pip install -e .

# 1) 初始化数据库
factory init-db

# 2) 查看某角色的权限边界
factory policy coder

# 3) 端到端演示：示例项目（首个任务故意注入缺陷，流水线必须捕获并修复）
factory demo

# 4) 自定义项目
factory run <task_graph.json> --prd <prd.md>

# 5) 查询项目持久化状态
factory status p_demo_calc
```

## 示例任务图

```jsonc
// examples/sample_project/task_graph.json
{
  "project_id": "p_demo_calc",
  "tasks": [
    { "id": "T001", "title": "implement sample_app package with tests",
      "dependencies": [], "meta": { "target": "all" } },
    { "id": "T002", "title": "harden test suite",
      "dependencies": ["T001"], "meta": { "target": "tests" } }
  ]
}
```

## 测试

```bash
python -m pytest tests -q      # 76 个单元 + E2E 测试
python -m ruff check factory tests   # 静态检查基线：0 告警
```

覆盖：任务图校验（含 UTF-8 BOM 兼容）、状态机、权限策略、预算（token + 运行时长，预算耗尽强制 BLOCKED）、验证管线、崩溃恢复（中断态任务自动复位重跑）、账本审计（每次 coder 花费落库）、以及完整 E2E（种子缺陷 → 修复 → 合并 → main 最终自洽）。

## 上线护栏（CI 契约）

- **退出码即结果**：`factory run` 仅在任务图完整执行（`DONE`）时返回 `0`，任何 `BLOCKED` / 部分产物返回 `1`，可直接接入 CI 判定。
- **预算兜底**：`FACTORY_RUNTIME_BUDGET_S`（默认 1800）在每次 coder 尝试**开始前**预检，预算耗尽立即 BLOCKED，绝不空转。
- **绝不静默合入**：任何未通过机器验证 / 评审的任务都不会写入 `main`；失败修复循环由 `FACTORY_MAX_RETRIES`（默认 3）封顶。
- **空产物安全**：coder 返回失败或空文件集时，评审以「声明文件缺失」REJECT，最终进入 BLOCKED，不会产出半成品。
- **可复现基线**：`pyproject.toml` 中固化 ruff 规则集（E4/E7/E9/F/I，行宽 120），CI 可用同一命令复验。
- **崩溃可恢复**：任务在 `IN_PROGRESS` / `WAITING_VERIFY` / `VERIFY_FAILED` / `WAITING_REVIEW` / `REVIEW_REJECTED` / `BLOCKED` 任一状态中断后，下一次 `factory run` 将其复位为 `READY` 重跑，绝不滞留为永久 BLOCKED。
- **花费可审计**：每次 coder 尝试（token + 运行时长）都镜像写入 `BudgetLedger`（含项目级 `BudgetAccount`），重启后账目完整可查。

## 目录

```
factory/
  config.py        Settings（worktree / 预算上限 / 数据库）
  db.py            引擎与会话管理
  schemas/         输入契约：Evidence / Risk / AgentOutput / TaskGraph
  state_machine.py 双态机 + 迁移表 + 策略闸门
  models/          Project / Task / Review / Run / Budget ORM
  policy.py        角色最小权限能力引擎
  verifier.py     syntax / pytest 机器验证闸门
  agents/          base(契约) / coder(可注入缺陷) / reviewer(规则隔离) / registry
  orchestrator.py  worktree 隔离流水线主循环
  budget.py        预算追踪（防止 agent 失控）
  workflows/       DevelopmentWorkflow（持久化、可续跑）
  cli.py           typer 命令行入口
examples/sample_project/  示例 PRD + 任务图
tests/             76 个单元 + E2E 测试
```
*（内容由AI生成，仅供参考）*
