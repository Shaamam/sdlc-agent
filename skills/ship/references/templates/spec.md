# {KEY}: {summary}

Status: draft | approved <date> | approved <date>; revised r<N> per review
Story: https://{site}/browse/{KEY}

## Summary
<2–4 sentences: what changes for whom, and why>

## Acceptance criteria
1. <criterion> *(stated | clarified | derived)*
2. ...

## AC → tests
| AC | Test case | Level | File |
|---|---|---|---|
| 1 | returns 422 when coupon expired | integration | tests/orders/coupon.test.ts |

## Files to touch
- `path/to/file.ext`: <what changes>

## Approach
<the smallest change that meets the criteria, matching local conventions>

## Assumptions
- <decision made without asking, and why>

## Risks
- <what could break, and how the tests or the rollout cover it>

## Out of scope
- <deliberately not done>

## Revision history
- r0 <date>: approved by developer
<!-- r<N> <date> — <what changed> — @<reviewer> <comment url> -->
