# Recommendation Flow Audit

## Current product surfaces
- Pitch page `ActionBrief`: consumes `GET /api/intel/priority-actions`.
- Pitch page `StatsPostIt`: consumes `GET /api/intel/gw`.
- Pitch page `TransferScratchpad`: consumes `GET /api/transfers/suggestions`.
- Strategy page captain block: consumes `GET /api/optimization/captain`.
- Strategy page transfer/bench/fixture surfaces: consume current optimization and intel endpoints.
- Review page: consumes `decision_log` and post-GW resolution state.

## What existed before this pass
- Captain scoring used a lightweight multiplier stack around xPts, FDR, home, and DGW.
- Transfer scoring used 1-GW and 3-GW xPts deltas, affordability, and hit cost.
- Priority actions rebuilt captain, transfer, injury, bench, and chip logic independently.
- Review logging stored recommendation text plus a small amount of bandit metadata.
- Frontend components were already stable and product-facing, but they received uneven recommendation metadata.

## Main gaps identified
- Recommendation logic was fragmented across routes and engines.
- Advanced signals such as minutes risk, simulation EV, and calibrated risk were not consistently present.
- Recommendation payloads lacked consistent confidence, floor/ceiling, and validation completeness.
- Existing logging could not fully explain which signals were used when a recommendation was made.

## Build-on-top approach
- Keep the current components and product flows.
- Introduce one shared synthesis layer behind captain, transfers, and action cards first.
- Emit richer metadata while preserving backward-compatible payloads.
- Run in shadow mode by default so live GW behavior can be compared safely before fully switching outputs.
