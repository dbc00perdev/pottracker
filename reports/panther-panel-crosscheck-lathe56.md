# Panel cross-check sheet — PANTHER JAKE_2100LY (CNC Lathe 6, 10.1.10.56)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-05 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | WEAR X | 0.0080 | 80 |  |
| 2 | 1 | GEOM X | 3.2829 | 32829 |  |
| 3 | 1 | GEOM Z | 2.8010 | 28010 |  |
| 4 | 1 | GEOM R | 0.0310 | 310 |  |
| 5 | 1 | TIP T | 3 | 3 |  |
| 6 | 2 | WEAR X | 0.0035 | 35 |  |
| 7 | 2 | GEOM X | 3.7349 | 37349 |  |
| 8 | 2 | WEAR Z | 0.0015 | 15 |  |
| 9 | 2 | GEOM Z | 2.7860 | 27860 |  |
| 10 | 2 | TIP T | 3 | 3 |  |
| 11 | 3 | WEAR X | -0.0100 | -100 |  |
| 12 | 3 | GEOM X | 3.8528 | 38528 |  |
| 13 | 3 | GEOM Z | 1.8974 | 18974 |  |
| 14 | 3 | GEOM R | 0.0156 | 156 |  |
| 15 | 3 | TIP T | 3 | 3 |  |
| 16 | 4 | WEAR X | 0.0040 | 40 |  |
| 17 | 4 | GEOM X | 3.6807 | 36807 |  |
| 18 | 4 | WEAR Z | 0.0045 | 45 |  |
| 19 | 4 | GEOM Z | 0.0156 | 156 |  |
| 20 | 5 | WEAR X | 0.0100 | 100 |  |
| 21 | 5 | GEOM X | 4.4197 | 44197 |  |
| 22 | 5 | WEAR Z | 0.0030 | 30 |  |
| 23 | 5 | GEOM Z | 0.0156 | 156 |  |
| 24 | 5 | TIP T | 8 | 8 |  |
| 25 | 6 | GEOM X | 2.5205 | 25205 |  |
| 26 | 6 | GEOM Z | 3.8523 | 38523 |  |
| 27 | 6 | TIP T | 2 | 2 |  |
| 28 | 7 | GEOM Z | 4.6428 | 46428 |  |
| 29 | 7 | TIP T | 7 | 7 |  |
| 30 | 8 | GEOM Z | 5.9947 | 59947 |  |
| 31 | 8 | TIP T | 7 | 7 |  |
| 32 | 9 | WEAR X | 0.0055 | 55 |  |
| 33 | 9 | GEOM Z | 4.3803 | 43803 |  |
| 34 | 9 | TIP T | 7 | 7 |  |
| 35 | 10 | WEAR X | 0.0055 | 55 |  |
| 36 | 10 | GEOM Z | 5.2986 | 52986 |  |
| 37 | 10 | TIP T | 7 | 7 |  |
| 38 | 11 | WEAR X | 0.0055 | 55 |  |
| 39 | 11 | WEAR Z | 0.0020 | 20 |  |
| 40 | 11 | GEOM Z | 4.7441 | 47441 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe56-capability-sweep-20260805.json`
