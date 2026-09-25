# Portfolio CEO — 组合决策

> 由自治软件工厂 Portfolio CEO（V6）生成：对组合内每个产品给出 Build / Scale / Experiment / Hold / Kill 决策与预算分配。

**3 product(s) in portfolio; 1 get follow-on investment; 1 killed (budget freed)**

| product | action | priority | budget | 依据 |
|---|---|---|---|---|
| p_waitlist | **KILL** | 9 | 0.000 | deployments.json |
| p_meetily | **SCALE** | 8 | 0.600 | analytics.json |
| p_churnfix | **BUILD** | 7 | 0.400 | validations.json |

### 决策明细

## p_waitlist — KILL

- release rolled back: canary CANARY_1 regression: error=0.120

## p_meetily — SCALE

- analytics recommended Scale: double down on distribution

## p_churnfix — BUILD

- validation gate said BUILD -> start build


### 预算分配

| product | weight |
|---|---|
| p_meetily | 0.600 |
| p_churnfix | 0.400 |
| p_waitlist | 0.000 |