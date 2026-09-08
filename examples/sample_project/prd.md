# Sample Product: Calculator Service

> 由自治软件工厂的示例任务图驱动的最小产品。

## Goal

提供一个可复用的 Python 计算模块 `sample_app.calc`，支持加减乘除，
并配套完整的单元测试，验证 `Coder -> Verifier -> Reviewer -> Merge` 流水线。

## Primary metric

- 单元测试全绿（作为 machine verifier 的客观门槛）

## MVP

- `sample_app/__init__.py`：包声明
- `sample_app/calc.py`：`add / sub / mul / div`
- `tests/test_calc.py`：覆盖正常路径与除零异常
