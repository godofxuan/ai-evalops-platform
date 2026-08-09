# v0.1.0 RC current-candidate load status

结论：最终 Candidate 2 没有完成正式 32-arm load protocol。当前 formal status 是 `NOT_RUN`，不是
`VERIFIED`。

## Current evidence

- targeted source: `246252e30e63f046a4a1fb5d684a35449aaef9e3`;
- workflow: `31319556885`, FAILED by frozen 20:1 fairness check;
- preserved bot commit: `f1a276f`;
- artifact: `targeted-gh-31319556885-1`, 280 KB;
- digest: `ed75825c310e52d31e8c0bb54432411bd31f57f520a244462c9aefdf06f68d58`;
- completed: 12 arms in repetition 1, 1,200/1,200 unique terminal Jobs;
- correctness: lost/duplicate durable result/orphan/empty-while-eligible all zero;
- blocker: `skew_20_to_1/w8` secondary durable claim position 4, required `<= 2`.

The partial 4-to-8 ratios were 0.8952 single-Tenant, 0.9083 balanced and 0.8907 for 20:1. They are `LIMITED`
diagnostics because repetitions 2–4 and many-small-Tenants did not run.

## Historical evidence boundary

Source `6acf72c3aa73c9fdc1664fe4e847fc8b8e90efd7`, run `31274490704`, remains a complete historical broken-fair
32-arm bundle with 16,000 unique terminal Jobs and severe 4/8-worker regression. Source
`15e7ac2e28b70430acd0bff88ee6cc78e5b86a86` remains the historical pre-fair baseline. Different runner CPUs weaken
cross-runner causality; neither bundle is current Candidate 2 throughput.

Allowed claim: the current candidate passed the completed arms' correctness reconciliation but failed its fairness
gate. Forbidden claim: current 32-arm VERIFIED, current linear scaling, or current 1/2/4/8 formal throughput.
