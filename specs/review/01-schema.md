# Schema and identity

Review baseline: `b26c374`. Findings distinguish the implemented schema from future adapter/model requirements.

### S1 — Distinct itineraries collapse to the same observation
- **Severity:** blocker
- **Where:** `specs/L0-foundation.md` §6; `pipeline/schema/identity.py:NATURAL_KEY_FIELDS`; SF-02 Behavior; `SnapshotStore.write()`.
- **What's wrong:** An itinerary's identity contains stops and first marketing carrier, but no flight/leg identifier, departure time, fare product, or `source_native_id`. Two BA nonstop JFK–LHR options on the same departure date and fetch day have the same ID. SF-02 explicitly emits the cheapest three itineraries. If these are returned cheapest first, last-occurrence batch dedup can retain the most expensive of three and discard the cheapest. This is a deterministic key collision, unrelated to SHA-256 collision probability.
- **Why it matters:** SF-06 cannot recover the cheapest itinerary after the store has discarded it. The headline recommendation can use $600 even though the adapter returned a $400 option in the same response.
- **Recommended fix:** Before collecting real data, add an `itinerary_key` required for `price_kind=itinerary` and absent for calendar aggregates. Derive it from validated ordered legs: airport endpoints, flight identifier, scheduled departure with an explicitly defined timezone, and any fare-product distinction actually available. Include it in the natural key. If the selected source cannot supply reliable identity, explicitly change its output contract to one cheapest aggregate per defined shape; do not label three indistinguishable rows as separate itineraries. Update L0, hash vectors, Arrow/frame schemas and fixture version together. Add a two-flight/same-carrier/same-stops test that preserves both prices and selects the cheaper downstream.
- **Confidence:** high — follows directly from the key and write reducer. A pinned fast-flights response will determine which itinerary fields are available.

### S2 — Currency is absent from identity and from statistical cohorts
- **Severity:** high
- **Where:** L0 §6; `pipeline/schema/record.py:CurrencyCode`; SF-06-build §3.2–3.3 and §4.5; SF-07-build §6.
- **What's wrong:** Same-day USD and EUR prices have the same observation ID. The proposed modal-currency filter works within each `(route, depart_date, fetched_date)` group, but subsequent distributions drop the currency dimension. Different groups can select different currencies and then be pooled. A user-supplied price's currency is not checked against the cohort at all. The schema checks three uppercase letters, not ISO membership; `ZZZ` validates.
- **Why it matters:** EUR 400 can be ranked against USD observations and a USD curve can be returned with the requested currency label. A source returning another currency can also overwrite the USD observation before modeling.
- **Recommended fix:** Pin the current product to USD explicitly at adapter acceptance, feature loading, current-price resolution and API validation. Reject unsupported API currencies with a documented error; quarantine a source response that violates the requested currency. Add currency to observation identity before supporting more than one currency. Replace modal selection with filtering by the requested currency before any minimum/dedup aggregation; retain currency in every future cohort key. Parse source amounts with `Decimal` and an explicit minor-unit exponent/rounding policy. Do not use `int(float_price * 100)`.
- **Confidence:** high — identity and cohort omissions are explicit. Real response fixtures would validate the amount parser requirements.

### S3 — Invalid canonical records cannot reach the promised rejection store
- **Severity:** blocker
- **Where:** SF-05 Record-level checks and rejected-record retention; L0 §5 Fetch result; `pipeline/schema/record.py:FareObservation`; SF-03 store input type.
- **What's wrong:** Adapters must return `FareObservation` objects, but construction rejects nonpositive prices, malformed airports, invalid enums and missing required fields. SF-05 expects to receive those same failures, mark them `schema_invalid`/`nonpositive_price`, and persist them as canonical records. Adding `data_quality=rejected` does not relax construction. There is no representation for malformed input or its raw payload.
- **Why it matters:** A source returns a zero price or missing airport. The adapter either raises before the gate, discards the row, or bypasses validation. None fulfills the audit promise. SF-05 cannot implement its done-when criteria against the frozen interface.
- **Recommended fix:** Keep canonical fare rows strict. Add a separate rejection envelope and quarantine store: source, run ID, received timestamp, request scope, sanitized raw payload, parser/schema version, structured violations. Let adapters return valid candidates plus rejected inputs; let SF-05 attach semantic quality flags only to representable canonical rows. Persist both streams and count both in run summaries. Distinguish a rejected but structurally valid fare from a payload that cannot become a fare. Assign the new types and storage ownership before SF-01/02/05 start.
- **Confidence:** high — the contradiction is executable through ordinary model construction.

### S4 — The two sources are not yet proven to describe the same route or fare
- **Severity:** high
- **Where:** L0 §2–5; SF-01 Source facts/Behavior; SF-02 Behavior; SF-06 prefer-itinerary collapse.
- **What's wrong:** The contract says airport-to-airport, while the documented Travelpayouts month-matrix parameters describe city/country codes. The spec does not pin an endpoint/version, airport enforcement, one-way selection, market, affiliate-cache scope, pagination, or response validity checks. The provider's example also carries `trip_class`, `return_date`, `found_at`, `actual`, and an offset timestamp. These require explicit handling, not just price/date mapping. [Travelpayouts API reference](https://travelpayouts.github.io/slate/#the-calendar-of-prices-for-a-month).
- **Why it matters:** Relabeling a city-wide NYC–London cached cheapest as JFK–LHR makes it incomparable with an exact-airport itinerary. Echoing a one-way/economy request onto a returned round-trip/business result invents provenance. Repeatedly fetching stale cache entries creates apparently fresh observations.
- **Recommended fix:** Add a source-contract acceptance task before freezing adapters. Pin the exact endpoint and parameters; obtain sanitized response fixtures proving airport scope, one-way/economy shape, currency, pagination and empty/error responses. Validate returned scope rather than blindly echoing the request. Normalize `found_at` offsets to UTC and calculate age from the receipt timestamp; preserve unknown age as unknown. Keep `depart_date` as the provider's travel date with a documented local-calendar convention, never the UTC date of a converted departure instant. If airport scope cannot be established, represent city scope separately or exclude that endpoint from airport predictions.
- **Confidence:** high that mapping evidence is missing; medium on the exact production mismatch until live payloads are supplied. The documentation alone does not prove the chosen account's behavior.

### S5 — The sanctioned constructor hashes before normalization
- **Severity:** medium
- **Where:** `pipeline/schema/record.py:build_observation`; `FareObservation.model_config`; `pipeline/schema/identity.py:_encode`.
- **What's wrong:** The helper hashes raw arguments, then Pydantic trims/coerces fields. Passing `carrier_primary=" BA "` creates a record with carrier `BA` and an ID calculated from the padded string. `validate()` subsequently reports `observation_id_mismatch`. Coercible integer/date inputs create similar opportunities because annotations do not enforce runtime types.
- **Why it matters:** An adapter can use the sole sanctioned constructor and still emit an internally inconsistent record; a harmless source-format variation changes dedup behavior.
- **Recommended fix:** Validate and normalize a separate input model first, then derive the route and hash from that model's typed fields, then build the immutable output. Alternatively reject noncanonical inputs consistently, including whitespace and coercible numeric strings. Add normalization-equivalence tests and the invariant `validate(build_observation(...)) == []` for every accepted input shape. Keep the existing fixed hash vectors for already canonical inputs.
- **Confidence:** high — reproduced with padded carrier text.

The Arrow field/type/nullability pin is sound. The problems are missing semantic distinctions and enforcement, not a reason to replace Arrow or use floats for stored money. See [C1/C2](07-code.md) for validation bypasses, integer bounds and UUID/path enforcement.
