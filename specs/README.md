# Snap Flights — Specs

> Snap Flights is a flight search product with **price prediction as the headline feature**.
> The pitch: *"Book now or wait? Here's what the price will do — and here's how to get it
> cheaper than anywhere else."* Portfolio project, $0 running budget, built to be worked
> on by multiple coding agents in parallel.

This folder is the source of truth for what gets built and in what order. Specs are written
for **coding agents** — plain Markdown, concrete, verifiable. No prose that can't be acted on.

---

## How the specs are tiered

| Tier | File(s) | What it is |
|------|---------|------------|
| **L0** | `L0-foundation.md` | The contracts every agent must obey: canonical data schema, source-adapter interface, repo layout, naming, the committed fixture dataset. **Read this first, always.** |
| **L1** | `epics/E*.md` | One file per epic. Scope boundary, dependencies, build order, subfeature list. `E1` (pipeline) and `E2` (prediction baseline) are specced in depth; `E3`–`E8` are stubs until their turn. |
| **L2** | `subfeatures/SF-*.md` | The unit of agent work. One subfeature ≈ one spec ≈ one PR ≈ one agent. Each names the exact files it owns so two agents never touch the same file. |

## How an agent uses this folder

1. Read `L0-foundation.md` in full.
2. Read the parent epic (`epics/E*.md`) for context and dependencies.
3. Pick up one `subfeatures/SF-*.md`. Confirm every item in its **Depends on** is done.
4. Work only inside the paths listed in its **Files owned**.
5. Ship when every item in **Done when** is verifiably true.

## Current scope (this pass)

Deep: **L0**, **E1 data pipeline**, **E2 baseline prediction**.
Stubs: **E3** search & discovery, **E4** cheap-fare hunting, **E5** alerts & automation,
**E6** booking handoff, **E7** trip quality, **E8** portfolio polish.

The MVP spine is: **collect fares → store snapshots → baseline prediction → show buy-vs-wait**.
Everything specced now serves that spine.

## MVP subfeatures (one agent each)

| ID | Title | Epic | Depends on |
|----|-------|------|------------|
| SF-01 | Travelpayouts source adapter | E1 | SF-03 |
| SF-02 | fast-flights source adapter | E1 | SF-03 |
| SF-03 | Canonical schema + snapshot store | E1 | — |
| SF-04 | Collection scheduler + route prioritization | E1 | SF-03, (SF-01 or SF-02) |
| SF-05 | Data-quality gates | E1 | SF-03 |
| SF-06 | Baseline percentile / seasonality model | E2 | SF-03 |
| SF-07 | Inference API | E2 | SF-06 |
| SF-08 | Buy-vs-wait UI surface | E2 | SF-07 |

## Open decisions (not yet locked)

- **Tech stack** — language(s), API framework, frontend framework, storage engine,
  orchestrator, package manager. Deliberately deferred; to be decided with a pros/cons
  review before implementation starts. L0 is written stack-neutral; the leading candidate
  from the earlier draft (Python + gradient boosting) is recorded in
  `reference/original-draft-spec.md` but is **not binding**.
- See `L0-foundation.md` § Open decisions for the full list.

## Reference

- `reference/original-draft-spec.md` — the earlier single-file draft. Superseded by this
  folder, kept for the feature ratings and the interview-narrative framing.
