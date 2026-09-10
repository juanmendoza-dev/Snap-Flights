# Snap Flights technical review

Reviewed workspace commit **`b26c374`** on **2026-09-09**, including the binary fixture and git history. No pasted bundle arrived. This review contains **39 findings** across seven areas. “Blocker” means the affected feature cannot fulfill its stated contract as written; it does not mean the whole project or chosen stack must be discarded.

The foundation is testable, but it is **not ready to freeze for independent adapter/model work**. Repair identity, rejection representation, write publication and dedup semantics before building consumers on them. Correct the prediction response and evaluation contracts before SF-06.

## Top 10, ranked

1. **Blocker — S1:** Distinct same-carrier itineraries share an ID, so dedup can discard the cheapest fare. [Schema](01-schema.md#s1--distinct-itineraries-collapse-to-the-same-observation)
2. **Blocker — S3:** SF-05 must retain invalid canonical records that its input model cannot represent. [Schema](01-schema.md#s3--invalid-canonical-records-cannot-reach-the-promised-rejection-store)
3. **Blocker — P1:** Empty-store/unknown-route responses require a price and evidence dates that do not exist. [Prediction](03-prediction.md#p1--empty-data-predictions-cannot-satisfy-their-response-type)
4. **Blocker — P6:** Backtest wait purchases use hindsight minima, and the spec directs fixture changes until the model wins. [Prediction](03-prediction.md#p6--backtest-rewards-an-oracle-and-allows-the-test-data-to-be-tuned-to-win)
5. **High — T1:** Readers can see unfinished Parquet files; concurrent writes can overwrite the same part. [Storage](02-storage.md#t1--part-files-are-visible-before-completion-and-concurrent-writers-can-overwrite)
6. **High — T2:** Pre-dedup quality filtering resurrects older versions; explicit filters and health have the same defect. [Storage](02-storage.md#t2--rejected-before-dedup-is-a-store-semantics-defect-with-siblings)
7. **High — S2:** Currency is absent from observation identity and statistical cohorts, permitting invalid monetary comparisons. [Schema](01-schema.md#s2--currency-is-absent-from-identity-and-from-statistical-cohorts)
8. **High — T3:** Batch boundaries change the winning price, and the run-ID tiebreaker does not resolve same-run ties. [Storage](02-storage.md#t3--the-dedup-winner-depends-on-batching-and-is-not-fully-deterministic)
9. **High — P2:** Wait can mean “buy at today's typical low,” including departure day, with no supported future dip. [Prediction](03-prediction.md#p2--the-verdict-rules-confuse-a-price-level-difference-with-a-future-move)
10. **High — T5:** Fixture union mixes synthetic and real prices without prediction-level provenance or reliable real-row precedence. [Storage](02-storage.md#t5--fixture-union-silently-blends-synthetic-and-real-history)

## Solid

- Parquet + DuckDB + cron is a reasonable small-budget backend spine; the current evidence does not justify replacing it with hosted infrastructure.
- Integer minor units and explicit currency, directional routes, source/run provenance, and rejection of naive receipt timestamps are good contracts to keep.
- The explicit Arrow schema, nullable field types, UTC microsecond timestamps, and fixed empty-frame schema avoid real interoperability bugs.
- One shared query builder for list/frame reads, parameterized SQL values, and immutable historical parts are good design choices once boundary checks/publication are repaired.
- Fixed identity vectors, deterministic fixture generation, every-row fixture validation and byte-regeneration tests provide a useful base for independent development.
- Fixed departure month/DOW along a purchase-time curve and one captured as-of date per prediction/request are correct intentions.
- Keeping UI, trained ML and E3–E8 deferred protects the current scope.

## Documents

| Area | Review |
|---|---|
| Identity, currency, canonical/source shapes | [01-schema.md](01-schema.md) |
| Publication, dedup, scan strategy, fixtures, schema evolution | [02-storage.md](02-storage.md) |
| Baseline logic, confidence, cold start and backtesting | [03-prediction.md](03-prediction.md) |
| Frozen contracts, agent ownership and integration | [04-process.md](04-process.md) |
| Contradictions, incomplete instructions and acceptance criteria | [05-specs.md](05-specs.md) |
| Collection state, Oracle budget, recovery and serving limits | [06-architecture.md](06-architecture.md) |
| Implemented validation, filters, clock and CI defects | [07-code.md](07-code.md) |
| Tests run, reproduced failures and limits | [08-verification.md](08-verification.md) |

Existing checks: **142 tests passed, 1 skipped; lint and formatting passed.** Additional probes reproduced bugs those tests do not cover. Source adapters, prediction and API behavior were reviewed as specs; they are not implemented and were not live-tested.

## Information I still need

See [09-information-needed.md](09-information-needed.md) for the missing source payloads/version pins, product/purchase semantics, Oracle account limits, remote integration settings and approval history. No assumptions about those missing facts are presented as verified behavior.
