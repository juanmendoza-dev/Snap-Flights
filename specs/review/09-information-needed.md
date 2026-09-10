# Information I still need

These gaps limit decisions that cannot be established from the workspace. They do not prevent implementing the reproduced foundation fixes.

| Missing information | Decision it controls | Evidence to provide |
|---|---|---|
| Intended authoritative review snapshot | Whether the absent bundle differed from this checkout | Bundle or commit SHA if `b26c374` is not the intended baseline |
| Selected Travelpayouts endpoint/account access and actual responses | Airport vs city scope, one-way/economy filtering, currencies, cache freshness, pagination, affiliate-cache coverage, endpoint rate limit | Exact endpoint/version and request parameters; sanitized successful, empty, paginated, rate-limited and malformed response fixtures with relevant headers. No token needed in review artifacts |
| Selected fast-flights version and transport | Reliable itinerary identity, amount/currency parsing, available flight/leg data, request counting, runtime dependencies | Version/commit pin, chosen direct-fetch configuration, sanitized library response plus underlying request count, documented fallbacks |
| Definition of the product being predicted | Whether cross-source fares are actually comparable | Airport-only vs city scope, allowed stops, baggage/basic-economy treatment, and whether verdict concerns any comparable route cheapest or one selected itinerary |
| Purchase policy and booking deadline | Meaning of wait, expected-low window and realized regret | Latest acceptable purchase time; what a user is expected to do if the target price/window fails; missing-quote behavior |
| Live source coverage over time | Defensible confidence thresholds, request budget, cold-start duration and evaluation feasibility | Budgeted multi-day sample with attempted/completed/empty route/date coverage, repeated cached-quote metadata, failures and source timestamps |
| Actual Oracle tenancy and operational configuration | Applicable $0 resource envelope and recovery guarantees | Account type, home region, console limits, selected shape/image, storage/backups, any existing deployment/restore instructions; no credentials |
| Remote GitHub settings and active agent workflow | Whether integration checks and ownership are enforced | Branch-protection/ruleset settings, required checks, active branch/worktree assignments, and confirmation of the current solo or parallel pass |
| Dispositions of L3's five open questions | Whether assumptions already have owner approval | Accepted decision links/notes so parent specs can be updated rather than re-decided |
| Existing raw-data retention/access constraints | What source payloads can be retained for audit and how long | Applicable provider documentation/account terms and any already accepted retention requirements. No legal conclusion is made from the current source labels |

No real historical performance report is available. A synthetic backtest can verify machinery; it cannot supply the missing real-world accuracy evidence.
