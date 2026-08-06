# Panel cross-check sheet — VIPER VT-23A (CNC Lathe 2, 10.1.10.52)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-06 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | GEOM X | 2.5722 | 25722 |  |
| 2 | 1 | GEOM Z | 0.0037 | 37 |  |
| 3 | 1 | GEOM R | 0.0316 | 316 |  |
| 4 | 1 | TIP T | 3 | 3 |  |
| 5 | 2 | GEOM X | 2.8674 | 28674 |  |
| 6 | 2 | GEOM Z | 0.0177 | 177 |  |
| 7 | 2 | GEOM R | 0.0156 | 156 |  |
| 8 | 2 | TIP T | 3 | 3 |  |
| 9 | 3 | GEOM X | -0.7137 | -7137 |  |
| 10 | 3 | GEOM Z | 3.6515 | 36515 |  |
| 11 | 4 | GEOM X | -0.4395 | -4395 |  |
| 12 | 4 | WEAR Z | 0.0010 | 10 |  |
| 13 | 4 | GEOM Z | 2.1945 | 21945 |  |
| 14 | 4 | TIP T | 2 | 2 |  |
| 15 | 5 | GEOM X | 0.0023 | 23 |  |
| 16 | 5 | GEOM Z | 2.4257 | 24257 |  |
| 17 | 5 | TIP T | 1 | 1 |  |
| 18 | 6 | GEOM X | 0.0022 | 22 |  |
| 19 | 6 | GEOM Z | 3.7777 | 37777 |  |
| 20 | 6 | TIP T | 2 | 2 |  |
| 21 | 7 | GEOM X | -0.0037 | -37 |  |
| 22 | 7 | GEOM Z | 5.4849 | 54849 |  |
| 23 | 7 | TIP T | 2 | 2 |  |
| 24 | 8 | GEOM X | 0.0022 | 22 |  |
| 25 | 8 | GEOM Z | 1.8936 | 18936 |  |
| 26 | 8 | GEOM R | 0.0156 | 156 |  |
| 27 | 8 | TIP T | 2 | 2 |  |
| 28 | 9 | GEOM Z | 1.1782 | 11782 |  |
| 29 | 9 | TIP T | 2 | 2 |  |
| 30 | 10 | GEOM X | 1.3481 | 13481 |  |
| 31 | 10 | GEOM Z | -0.0040 | -40 |  |
| 32 | 11 | GEOM X | 3.7745 | 37745 |  |
| 33 | 11 | GEOM Z | 0.0181 | 181 |  |
| 34 | 12 | GEOM X | 0.4688 | 4688 |  |
| 35 | 12 | GEOM Z | -0.0148 | -148 |  |
| 36 | 12 | GEOM R | 0.0160 | 160 |  |
| 37 | 12 | TIP T | 3 | 3 |  |
| 38 | 53 | GEOM X | 4.4125 | 44125 |  |
| 39 | 53 | GEOM Z | -0.7973 | -7973 |  |
| 40 | 59 | GEOM Z | 13.7037 | 137037 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe52-capability-sweep-20260806.json`

---
**VERIFIED 2026-08-06 (dbc00per, viewer vs fresh live read): ALL ROWS MATCH — bank map LOCKED.**
