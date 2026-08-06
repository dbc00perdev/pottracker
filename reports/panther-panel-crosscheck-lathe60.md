# Panel cross-check sheet — PANTHER PROD_2100LYS-2 (CNC Lathe 8, 10.1.10.60)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-05 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | WEAR X | -0.0050 | -50 |  |
| 2 | 1 | GEOM X | 4.0163 | 40163 |  |
| 3 | 1 | GEOM Z | 2.9608 | 29608 |  |
| 4 | 1 | GEOM R | 0.0312 | 312 |  |
| 5 | 1 | TIP T | 3 | 3 |  |
| 6 | 2 | WEAR X | 0.0100 | 100 |  |
| 7 | 2 | GEOM X | 4.4145 | 44145 |  |
| 8 | 2 | WEAR Z | 0.0015 | 15 |  |
| 9 | 2 | WEAR R | -0.0008 | -8 |  |
| 10 | 2 | TIP T | 8 | 8 |  |
| 11 | 3 | GEOM X | 2.7554 | 27554 |  |
| 12 | 3 | GEOM Z | -1.9376 | -19376 |  |
| 13 | 4 | GEOM Z | 5.1361 | 51361 |  |
| 14 | 4 | TIP T | 8 | 8 |  |
| 15 | 5 | GEOM Z | 5.9751 | 59751 |  |
| 16 | 5 | TIP T | 8 | 8 |  |
| 17 | 6 | GEOM X | 1.5750 | 15750 |  |
| 18 | 6 | GEOM Z | 3.3405 | 33405 |  |
| 19 | 6 | TIP T | 7 | 7 |  |
| 20 | 7 | WEAR X | 0.0050 | 50 |  |
| 21 | 7 | GEOM X | -1.3480 | -13480 |  |
| 22 | 7 | GEOM Z | 3.6779 | 36779 |  |
| 23 | 7 | TIP T | 2 | 2 |  |
| 24 | 8 | WEAR X | 0.0010 | 10 |  |
| 25 | 8 | GEOM X | 3.5573 | 35573 |  |
| 26 | 8 | WEAR Z | 0.0075 | 75 |  |
| 27 | 8 | GEOM Z | 2.7165 | 27165 |  |
| 28 | 9 | WEAR X | 0.0060 | 60 |  |
| 29 | 9 | GEOM X | 1.5747 | 15747 |  |
| 30 | 9 | GEOM Z | 5.6004 | 56004 |  |
| 31 | 9 | TIP T | 7 | 7 |  |
| 32 | 10 | WEAR X | -0.0010 | -10 |  |
| 33 | 10 | GEOM X | 1.5747 | 15747 |  |
| 34 | 10 | WEAR Z | 0.0020 | 20 |  |
| 35 | 10 | GEOM Z | 5.5125 | 55125 |  |
| 36 | 10 | TIP T | 7 | 7 |  |
| 37 | 11 | GEOM Z | 3.8343 | 38343 |  |
| 38 | 11 | TIP T | 7 | 7 |  |
| 39 | 12 | GEOM X | 3.8655 | 38655 |  |
| 40 | 12 | GEOM Z | 2.1462 | 21462 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe60-capability-sweep-20260805.json`

---
**VERIFIED 2026-08-06 (dbc00per confirmed the posted 29-register live table accurate): bank map LOCKED.**
