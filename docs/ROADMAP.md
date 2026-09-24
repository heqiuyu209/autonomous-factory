# Autonomous Factory — 产品路线图（ROADMAP）

> 本文件是项目发展的正式蓝图与版本规划依据。它定义了从 V1 到 V6 的演进路径、
> 每个版本的输入输出契约、验收方向，以及贯穿始终的开发纪律。
> 开发节奏遵循：**小步推进、每步验证、版本管理、大版本打 tag**。

---

## 1. 项目愿景

构建一个 **Autonomous Software Venture Factory（自治软件创业工厂）**：

> 系统自己观察市场 → 找机会 → 判断值不值得做 → 写 PRD → 设计架构 → 开发 →
> Code Review → 测试 → 安全审计 → 性能测试 → 部署 → 收集真实用户反馈 →
> 决定继续、重构还是砍掉项目。

设计原则：**不是设计成一个万能 Agent**，而是设计成一个

```
Agent Organization + Durable Workflow + Independent Verification System
```

核心循环不是 `idea → coding → finished`，而是：

```
市场 → 假设 → 实验 → 产品 → 用户 → 数据 → 新假设 → 继续 / pivot / kill
```

---

## 2. 系统总架构（目标形态）

```
                         ┌───────────────────────┐
                         │    AUTONOMOUS CEO     │
                         │ Portfolio / Governor  │
                         └───────────┬───────────┘
                                     │
              ┌──────────────────────┴──────────────────────┐
              │                                             │
              ▼                                             ▼
     MARKET INTELLIGENCE                            EXISTING PRODUCTS
              │                                             │
              ▼                                             ▼
┌──────────────────────────┐                     ┌─────────────────────┐
│ Market Scout Agents      │                     │ Analytics Agent     │
│ Reddit / GitHub / Search │                     │ Bugs / Usage / $$$  │
│ Reviews / Forums / SEO   │                     │ Retention / Errors  │
└─────────────┬────────────┘                     └──────────┬──────────┘
              │                                             │
              └───────────────────┬─────────────────────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ Opportunity Engine  │
                       │ Cluster + Rank      │
                       └──────────┬──────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ Product Council     │
                       │ GO / TEST / KILL    │
                       └──────────┬──────────┘
                                  │
                             Approved idea
                                  ▼
                 ┌───────────────────────────────┐
                 │ PRODUCT DEVELOPMENT FACTORY   │
                 └──────────────┬────────────────┘
                                ▼
                         Product Manager
                                │
                                ▼
                           Architect
                                │
                      ┌─────────┴─────────┐
                      ▼                   ▼
                Backend Agent        Frontend Agent
                      │                   │
                      ├──── DB Agent ─────┤
                      │                   │
                      └──── DevOps ───────┘
                                │
                                ▼
                            Git / PR
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
             Code Reviewer             Test Agent
                   │                         │
                   ▼                         ▼
             Security Agent            E2E Agent
                   │                         │
                   └───────────┬─────────────┘
                               ▼
                        Performance Agent
                               │
                               ▼
                         Release Manager
                               │
                               ▼
                          STAGING/CANARY
                               │
                               ▼
                         Production Agent
                               │
                               ▼
                         User telemetry
                               │
                               └──────────→ CEO
```

真正重要的是**最后那个箭头**：用户数据回流到 CEO，形成闭环决策。

---

## 3. 版本路线（V0 → V6）

| 版本 | 新增能力 | 输入 → 输出 | 状态 |
|------|----------|-------------|------|
| V0 | 单 Agent + 独立 verifier | 一个 coding task → 代码 | ✅ 已达成 |
| V1 | Planner + Coder + Reviewer + QA | PRD + 任务图 → working application | ✅ v1.0.0 封版 |
| V2 | PM + Architect | 问题描述 → 自动产品 | ✅ v2.0.0 封版 |
| V3 | Market Scout | 互联网 → 自动发现机会 | ⬜ 未开始 |
| V4 | Validation Engine | 机会 → 自动验证市场需求 | ⬜ 未开始 |
| V5 | Deployment + Analytics | 产品 → 用户数据 → 自动迭代 | ⬜ 未开始 |
| V6 | Portfolio CEO | 同时管理 N 个产品，Build/Scale/Kill | ⬜ 未开始 |

### 各版本定义

**V1（已封版 v1.0.0）**
- 输入：PRD + 任务图（DAG）
- 输出：经过独立验证、可用的应用
- 已实现：任务图编排、worktree 隔离、机器验证门（syntax/test/lint）、
  Reviewer、修复循环 + 硬上限、最小权限、预算护栏、崩溃恢复、审计账本、promote、CLI 退出码契约

**V2（当前目标）**
- 输入：一段问题描述（自然语言）
- 新增角色：PM（写 PRD）+ Architect（拆任务图）
- 输出：自动产品（复用 V1 的编码与验证流水线）
- 关键决策：PM 产出的 PRD 与 Architect 产出的任务图是否需要人工确认环节（设计为可配置）

**V3**
- 新增：Market Scout Agent（Reddit / GitHub / Search / Reviews / Forums / SEO 数据源）
- 输出：机会候选列表

**V4**
- 新增：Validation Engine（Opportunity Engine 聚类排序 + Product Council GO/TEST/KILL 决策）
- 输出：通过评审的 Approved idea

**V5**
- 新增：Deployment + Analytics（发布到 STAGING/CANARY → Production，收集用户数据）
- 输出：用户反馈数据回流

**V6**
- 新增：Portfolio CEO（同时管理 N 个产品，自动 Build / Scale / Kill）
- 输出：基于数据的持续决策闭环

---

## 4. 当前定位

- 仓库当前处于 **V1 封版态（v1.0.0）**。
- 下一步开发目标：**V2 — 加入 PM + Architect，从问题描述 → 自动产品**。
- V1 的编码/验证/修复流水线是 V2 的底座，V2 不重写它，只在其前段插入新的能力模块。

---

## 5. 开发纪律（硬性约束）

1. **小步推进**：一次只做一个小的功能点，禁止大跨步一次性改动多个模块。
2. **每步验证**：每修改一个地方，必须多次验证（全量 pytest + ruff），
   确认没有引入新问题后才进入下一步。
3. **git 版本管理**：每个功能点一个独立 commit，commit message 清晰描述改动；
   涉及不完整中间态时明确标注。
4. **大版本打 tag**：每个大版本（V1、V2、…）完成验收后打对应版本 tag
   （v1.0.0、v2.0.0、…）；小步功能迭代使用 patch/minor 版本号管理。
5. **验收线先于开发**：每个大版本开工前，先明确该版本的完成标准与验收指标。
