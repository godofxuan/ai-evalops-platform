# Integration-fix behavioral source lock

- Superseded implementation lock: `7dca9715fbb5f2a46f648161f8a67d086de9d485`
- New implementation lock: `0915c10d9176191f4f306590f029ed66809cf161`
- Original preregistration: `1c87fb218e334790812080701bd74b81488bf19c`
- Addendum identity: the commit that first adds this file and
  `00A_INTEGRATION_FIX_PREREGISTRATION.md`

Relative to the superseded lock, the only behavioral change is psycopg escaping in the static
telemetry query. Doubling `%` is client parameter syntax; PostgreSQL still receives the same four
`ILIKE '%category%'` patterns. No statement, relation, projection, ordering, row limit, frequency,
transaction, Worker or scheduler behavior changed. The remaining changed Python lines are a new
regression test and Ruff-only formatting of `scripts/behavioral_source_lock.py`.

The complete behavioral path set remains:

```text
app/
scripts/
alembic/
deploy/
.python-version
alembic.ini
pyproject.toml
uv.lock
```

The formal workflow must compare this new lock to its trigger SHA and fail on any later behavioral
delta. Historical evidence subtree locks and race-safe preservation rules from `01_SOURCE_LOCK.md`
remain unchanged.

