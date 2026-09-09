# pipeline

Everything between a fare source and a stored observation. Boundaries are binding
(L0 §1); what goes in each one is:

| Directory | Owns |
|-----------|------|
| `adapters/` | One module per source (`travelpayouts/`, `fastflights/`). Fetches from that source and emits canonical records — no business logic, no prediction, no storage (L0 §5). |
| `schema/` | The canonical fare-observation record and its validators (L0 §3). Single source of truth; every producer and consumer imports from here. |
| `store/` | Read and write the append-only snapshot store — Parquet partitions, the natural key, the dedup rule (L0 §6). |
| `quality/` | The data-quality gates that stamp `data_quality` and `quality_flags` (SF-05). |
| `scheduler/` | Collection orchestration and route prioritization (SF-04). |

Adapters, quality and scheduler are not built in the current pass; the committed fixture
dataset stands in for collected fares.
