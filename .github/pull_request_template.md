## Issue

Closes #

Use `Closes #<issue number>` so GitHub closes the issue only after this pull request reaches `main`.

## What changed

- Describe the user-visible or internal change.

## Verification

- [ ] `python scripts/verify_issues.py --issue <issue number>` passes.
- [ ] `python scripts/verify_issues.py --issue <issue number> --full --frontend` passes before merge.
- [ ] GitHub Python, frontend, and container checks pass.
- [ ] Any manual UI check that cannot be automated is described below.

If `verify_issues.py` has no entry for this issue yet, add the issue-specific checks in this pull request before merging.

## Manual UI check

Not required / describe what was checked and the result.

## Remaining limitations

None / list anything deliberately left for a later issue.
