---
slug: composite-integration
validation: lightweight
status: active
---

## Claim

Composite Simpson integration with 20 intervals estimates the integrals of
`x³`, `sin(x)`, and `exp(x)` on `[0, 1]` with absolute error at most `0.0001`
for each function.

## Measurement

Test one function per run using seeds 0, 1, and 2. Compare Simpson and
trapezoid results with the analytic integral, using the same 21 equally spaced
nodes for both rules. Record candidate error, comparator error, seed, and
function.

## Stop condition

Stop after the three functions have been tested. Any candidate error above
`0.0001` falsifies the claim. A missing or invalid result is inconclusive.
Other functions require a separate claim and test.
