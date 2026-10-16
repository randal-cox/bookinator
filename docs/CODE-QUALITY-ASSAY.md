# Code quality assay

Updated 2026-10-16 during the Adversaries milestone.

## Blocking lint

`npm run test:lint` runs Ruff over `bookinator` and `tests`; `npm run check`
includes it. The first run found ten issues: one lambda assignment, one
intentional late import, and eight dead assignments. The narrow cleanup left
Ruff green without automatic or unsafe rewrites.

## Pylint adversary

`npm run audit:pylint` is intentionally diagnostic rather than blocking. The
first full run rated the repository **7.57/10** and produced a large mixed
ledger. Its useful signals include:

- `bookinator/server/__main__.py` is a 13,000-line ownership boundary with
  several functions above Pylint's branch, statement, argument, and local
  variable thresholds;
- callback closures inside chapter loops captured loop state implicitly; the
  inspected callbacks now bind the current record explicitly so a future async
  implementation cannot write into the next chapter;
- broad exception boundaries need individual review to distinguish deliberate
  optional-provider isolation from swallowed programming errors; and
- the request handler and global queue runner are the highest-value extraction
  targets because both combine routing, lifecycle, persistence, and policy.

The raw count is not a release score. Missing docstrings, the existing compact
line style, HTTP method names required by `BaseHTTPRequestHandler`, platform
branches, and imports for optional PyMuPDF/Torch/Transformers environments
produce substantial noise. Pylint must therefore remain an adversarial report
until findings are baselined by rule and ownership; making the entire score
blocking would reward mass suppression rather than better code.

## Next refactoring priorities

1. Extract pipeline ledger storage and compare-and-write policy from the HTTP
   and queue orchestration module.
2. Replace the monolithic POST dispatcher with route handlers whose inputs and
   response schemas can be tested independently.
3. Split chapter-reading orchestration from model transport and normalization.
4. Classify broad exception catches as provider boundary, recovery boundary,
   or defect; narrow every catch that lacks one of those jobs.
5. Add complexity/churn triage so high-change, high-complexity functions receive
   tests and review before stable but merely large legacy sections.

Ruff proves a bounded mechanical floor. Pylint identifies architectural debt.
Neither substitutes for mutation testing, real pipeline acceptance, browser
behavior, or human review of the model's output.
