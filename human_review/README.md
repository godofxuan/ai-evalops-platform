# Human review kit

This directory is intentionally incomplete: there are no real review rows because the comparable A/B packet cannot be generated yet.

When both revisions expose the same harness contract:

1. Run the frozen dataset against A and B and randomize the mapping per case.
2. Give each reviewer the packet without Git SHAs, branch names, or A/B mapping.
3. Each of two distinct reviewers adds one row for A and one row for B for every case to `review_form.csv`.
4. Run `python -m human_review.validate_reviews`.
5. Put disagreements into `adjudication.csv`; adjudication does not overwrite original labels.
6. Reveal the A/B mapping only after both submissions are frozen.

Never paste rows from unit tests into these files. Empty files mean `PENDING`, not zero disagreement.
