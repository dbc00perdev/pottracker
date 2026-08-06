# Panel cross-check sheet — VIPER VT-25BL (CNC Lathe 4, 10.1.10.54)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-06 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | WEAR X | -0.0010 | -10 |  |
| 2 | 1 | GEOM X | 0.3890 | 3890 |  |
| 3 | 1 | GEOM Z | 0.0002 | 2 |  |
| 4 | 1 | GEOM R | 0.0312 | 312 |  |
| 5 | 1 | TIP T | 3 | 3 |  |
| 6 | 2 | WEAR X | 0.0010 | 10 |  |
| 7 | 2 | GEOM X | 1.8950 | 18950 |  |
| 8 | 2 | GEOM Z | -0.0054 | -54 |  |
| 9 | 2 | GEOM R | 0.0156 | 156 |  |
| 10 | 2 | TIP T | 3 | 3 |  |
| 11 | 3 | GEOM X | 2.3910 | 23910 |  |
| 12 | 3 | GEOM Z | 1.1700 | 11700 |  |
| 13 | 4 | WEAR Z | -0.0030 | -30 |  |
| 14 | 4 | GEOM Z | 2.9324 | 29324 |  |
| 15 | 4 | TIP T | 2 | 2 |  |
| 16 | 6 | GEOM Z | 3.7720 | 37720 |  |
| 17 | 6 | TIP T | 2 | 2 |  |
| 18 | 8 | GEOM Z | 5.7920 | 57920 |  |
| 19 | 8 | TIP T | 2 | 2 |  |
| 20 | 9 | WEAR X | 0.0022 | 22 |  |
| 21 | 9 | GEOM X | -0.6310 | -6310 |  |
| 22 | 9 | GEOM Z | 3.3290 | 33290 |  |
| 23 | 9 | TIP T | 2 | 2 |  |
| 24 | 10 | GEOM X | -0.2420 | -2420 |  |
| 25 | 10 | GEOM Z | 2.7609 | 27609 |  |
| 26 | 10 | GEOM R | 0.0156 | 156 |  |
| 27 | 10 | TIP T | 2 | 2 |  |
| 28 | 11 | GEOM X | 0.4540 | 4540 |  |
| 29 | 11 | GEOM Z | 0.0024 | 24 |  |
| 30 | 11 | TIP T | 3 | 3 |  |
| 31 | 12 | GEOM X | 1.0904 | 10904 |  |
| 32 | 12 | WEAR Z | 0.0015 | 15 |  |
| 33 | 12 | GEOM Z | -0.2403 | -2403 |  |
| 34 | 16 | GEOM Z | 13.4378 | 134378 |  |
| 35 | 40 | GEOM Z | 17.5273 | 175273 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe54-capability-sweep-20260806.json`
