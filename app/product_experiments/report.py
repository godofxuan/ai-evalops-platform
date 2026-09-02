# ruff: noqa: E501
"""Dependency-free, portable HTML report for a paired experiment."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_experiment_html(result: Mapping[str, Any]) -> str:
    scope = str(result.get("scope", "UNKNOWN"))
    status = str(result.get("status", "UNKNOWN"))
    boundary = (
        "演示通过不等于正式质量提升；它只证明配置、执行、统计和报告链路可重复。"
        if scope == "DEMO"
        else "自动评估不能替代两位独立盲审；人评完成前不得发布正式质量提升结论。"
    )
    raw_rows = result.get("case_comparisons", [])
    rows: Sequence[object] = raw_rows if isinstance(raw_rows, list) else []
    table_rows = "".join(_case_row(row) for row in rows)
    metrics = result.get("automated_assessment", {})
    metrics_json = json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True)
    requirements = result.get("input_requirements", [])
    requirements_json = json.dumps(requirements, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI EvalOps · {_escape(result.get("experiment_id", "experiment"))}</title>
<style>
:root{{--ink:#172033;--muted:#667085;--paper:#fff;--wash:#f2f5f9;--accent:#3157d5;--ok:#147d64;--line:#d9e0ea}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--wash);color:var(--ink);font:15px/1.55 Inter,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:36px 22px}}h1{{font-size:32px;margin:0 0 6px}}h2{{margin-top:30px}}
.sub{{color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:22px 0}}
.card,section{{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 7px 22px #23395d0b}}
.value{{font-size:21px;font-weight:700}}.boundary{{border-left:5px solid var(--accent);background:#eef3ff}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:900px}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{position:sticky;top:0;background:#f8fafc}}code,pre{{font-family:Cascadia Code,Consolas,monospace}}pre{{overflow:auto;background:#101828;color:#e6edf7;padding:16px;border-radius:10px}}
.status{{color:var(--ok)}}
</style>
</head>
<body><main>
<p class="sub">AI EvalOps Platform · paired experiment report</p>
<h1>{_escape(result.get("experiment_id", "experiment"))}</h1>
<p class="status"><strong>{_escape(status)}</strong></p>
<div class="cards">
  <div class="card"><div class="sub">Scope</div><div class="value">{_escape(scope)}</div></div>
  <div class="card"><div class="sub">Paired cases</div><div class="value">{_escape(result.get("case_count", 0))}</div></div>
  <div class="card"><div class="sub">Human review</div><div class="value">{_escape(result.get("human_review_status", "PENDING"))}</div></div>
  <div class="card"><div class="sub">Production ready</div><div class="value">{_escape(result.get("production_ready", False))}</div></div>
</div>
<section class="boundary"><strong>证据边界</strong><br>{_escape(boundary)}</section>
<h2>Required inputs</h2><pre>{_escape(requirements_json)}</pre>
<h2>身份绑定</h2>
<section><div>Dataset SHA-256: <code>{_escape(result.get("dataset_sha256", ""))}</code></div>
<div>EvalOps SHA: <code>{_escape(result.get("evalops_sha", ""))}</code></div></section>
<h2>逐条对比</h2>
<section class="table-wrap"><table><thead><tr><th>Case</th><th>Category</th><th>Baseline answer</th><th>Candidate answer</th><th>Success B→C</th><th>Citation B→C</th><th>Tool error B→C</th><th>Latency B→C</th><th>Cost B→C</th><th>Trace B / C</th></tr></thead>
<tbody>{table_rows}</tbody></table></section>
<h2>机器评估</h2><pre>{_escape(metrics_json)}</pre>
</main></body></html>"""


def _case_row(raw: object) -> str:
    row = raw if isinstance(raw, Mapping) else {}
    values = (
        row.get("case_id", ""),
        row.get("category", ""),
        row.get("baseline_answer", ""),
        row.get("candidate_answer", ""),
        f"{row.get('baseline_task_success', '')} → {row.get('candidate_task_success', '')}",
        f"{row.get('baseline_citation_correctness', '')} → {row.get('candidate_citation_correctness', '')}",
        f"{row.get('baseline_tool_error_rate', '')} → {row.get('candidate_tool_error_rate', '')}",
        f"{row.get('baseline_latency_ms', '')} → {row.get('candidate_latency_ms', '')} ms",
        f"{row.get('baseline_cost_usd', '')} → {row.get('candidate_cost_usd', '')} USD",
        f"{row.get('baseline_trace_id', '')} / {row.get('candidate_trace_id', '')}",
    )
    return "<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in values) + "</tr>"


__all__ = ["render_experiment_html"]
