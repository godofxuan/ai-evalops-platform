# Integration-fix preregistration addendum

- Registered: 2026-08-11 (Asia/Shanghai)
- Original preregistration commit: `1c87fb218e334790812080701bd74b81488bf19c`
- Failed ordinary CI run: `31418895463`
- New measurement code lock: `0915c10d9176191f4f306590f029ed66809cf161`
- Formal measurement runs completed before this addendum: **0**
- Measurement trigger created before this addendum: **NO**

Ordinary CI, intentionally run before the formal trigger existed, exposed a psycopg client-side
parameter parsing failure. The fixed telemetry SELECT contains a real `LIMIT %s` parameter and four
LIKE patterns. In a psycopg parameterized query, literal percent signs in those patterns must be
written as `%%`; otherwise psycopg treats them as placeholder syntax and raises
`ProgrammingError` before PostgreSQL executes the SELECT.

Run `31418895463` therefore did not produce OFF/ON measurement observations and is not an overhead
qualification attempt. Its telemetry integration step failed, the formal measurement workflow was
never triggered, and no threshold, arm, order, frequency or interpretation was changed after
measurement data.

The allowed fix is exactly:

1. escape the four static LIKE patterns for psycopg while preserving the SQL PostgreSQL receives;
2. add a no-database regression test for the escaped literals; and
3. apply Ruff's formatting to the behavioral source-lock helper without changing its path set or
   decisions.

All original frozen contracts remain unchanged: 5 Hz; exact arm
`fair-q1000-skew_20_to_1-w8-b1`; sample Jobs 100; Block A OFF/ON/ON/OFF; Block B ON/OFF/OFF/ON;
exactly four OFF and four ON; absolute throughput limit 5%; absolute claim-p95 limit 10%; zero
correctness, false-empty, telemetry error, dropped-sample and overflow counts.

The original preregistration remains historical and is not rewritten. The formal workflow must bind
both the original preregistration and this addendum, use the new code lock, and pass ordinary real
PostgreSQL CI before a trigger may be committed.

