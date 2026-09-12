# AI EvalOps：新的评测入口

本轮新增“运行比较 → 查看失败原因 → 盲审校准 → 完整回归”流程。

```powershell
uv sync --locked --all-groups
uv run --no-sync python -m scripts.evaluation_workflow demo --task agent --output-dir artifacts/first-run --include-private
uv run --no-sync python -m scripts.evaluation_workflow verify --bundle artifacts/first-run
```

打开输出目录的 `report.html`。演示为明确标记的 fixture，不调用真实模型；真实数据使用 `--include-private` 后不得公开。

- [完整使用说明](docs/evaluation-workflow.md)：真实目标、OTLP 轨迹、评分、人评及恢复操作。
- [实施与学习记录](docs/reviews/evaluation-workflow-execution.md)：每项修改的原因、遇到的问题、验证及未完成外部条件。
- [评分设计](docs/reviews/learning-grading-notes.md)：评分有效性与工程正确性的区别。
- [轨迹兼容与限制](docs/reviews/trace-diagnostics-notes.md)：开放协议兼容的真实范围。

本功能不修改历史 gold 和质量门槛，不把诊断一致率当业务提升；未完成的人评、真实业务 A/B 和数据库验收保持明确状态。原 README 是历史证据中的冻结文件，所以本入口单独提供，不篡改旧清单。
