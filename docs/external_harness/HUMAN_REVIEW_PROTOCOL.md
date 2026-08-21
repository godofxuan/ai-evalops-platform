# Blinded human-review protocol

Status: **PENDING**. No person has submitted a review.

Two distinct reviewers must each score both hidden answers A and B for every frozen case. Required dimensions are groundedness, citation correctness, tool correctness, safety/refusal behavior, and overall pass/fail/needs-adjudication. The mapping from A/B to baseline/candidate stays outside reviewer files until both reviewers submit.

Completion requires exactly two distinct reviewer IDs, exact case coverage, four rows per case (two answers × two reviewers), no duplicates, and one packet ID. Agreement and Cohen's kappa are computed only after those conditions pass. Any disagreement or `needs_adjudication` row enters the adjudication file.

Unit tests use fictional reviewer IDs solely to test validation. They are not review evidence and must never be copied to `HUMAN_REVIEW_RESULTS.md`.
