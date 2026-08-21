# Shadow release gate

Current decision: **INPUT_BLOCKED**

Decision order is fail closed: operational or safety failure → `FAIL`; missing comparable automated input → `INPUT_BLOCKED`; automated pass with incomplete real review → `HUMAN_REVIEW_PENDING`; only all complete and passing → `PASS`.

Current inputs:

- Automated A/B: `INPUT_BLOCKED` (baseline contract absent)
- Real human review: pending
- Trace-correlation mechanism: passed
- Boundary failure tests: passed
- Formal production failure scenarios against A and B: not executed

This is a shadow-only mechanism. It does not deploy, tag, merge, or release anything.
