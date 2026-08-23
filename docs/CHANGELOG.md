# GeoDispatch Changelog

## E2E test log

| Date | Input summary | What happened | How handled |
|------|---------------|---------------|-------------|
| 2026-08-23 | HW-2026-15 heatwave/green/1dev/reach=DATA | HTTP 500: {"detail":"Failed to process decision request"} | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-16 heatwave/red/3dev/reach=DATA+SMS+CONNECTED | HTTP 500: {"detail":"Failed to process decision request"} | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-17 heatwave/orange/2dev/reach=SMS+CONNECTED | HTTP 500: {"detail":"Failed to process decision request"} | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-18 heatwave/green/1dev/reach=DATA | HTTP 500: {"detail":"Failed to process decision request"} | 500s return a clean message; investigate server log |
| 2026-08-23 | test_e2e run (18 batches) | 14/18 passed; batch latency avg 42s, max 105s; ~25s per device over 30 device calls. KNOWN LATENCY RISK: single-device cold latency ~83s (one blocking model call per device on CPU; batch latency scales linearly with device count) — Week 2 to investigate concurrent per-device calls or batching. | Logged; Week 2 to investigate concurrent per-device calls or batching |
| 2026-08-23 | EQ-2026-04 earthquake/red/3dev/reach=SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | EQ-2026-05 earthquake/orange/2dev/reach=SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | EQ-2026-06 earthquake/green/1dev/reach=DATA | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | FL-2026-07 flood/red/2dev/reach=SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | FL-2026-08 flood/orange/1dev/reach=SMS | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | FL-2026-09 flood/green/1dev/reach=DATA | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | FL-2026-10 flood/red/2dev/reach=CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | FL-2026-11 flood/orange/3dev/reach=DATA+SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | FL-2026-12 flood/green/1dev/reach=DATA | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-13 heatwave/red/2dev/reach=SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-14 heatwave/orange/1dev/reach=DATA | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-15 heatwave/green/1dev/reach=DATA | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-16 heatwave/red/3dev/reach=DATA+SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-17 heatwave/orange/2dev/reach=SMS+CONNECTED | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | HW-2026-18 heatwave/green/1dev/reach=DATA | HTTP 500:  | 500s return a clean message; investigate server log |
| 2026-08-23 | test_e2e run (18 batches) | 3/18 passed; batch latency avg 16s, max 111s; ~10s per device over 30 device calls. KNOWN LATENCY RISK: single-device cold latency ~83s (one blocking model call per device on CPU; batch latency scales linearly with device count) — Week 2 to investigate concurrent per-device calls or batching. | Logged; Week 2 to investigate concurrent per-device calls or batching |
