# Panel cross-check sheet — VIPER VT-15L (CNC Lathe 5, 10.1.10.55)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-06 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | WEAR X | -0.0015 | -15 |  |
| 2 | 1 | GEOM X | 0.9809 | 9809 |  |
| 3 | 1 | GEOM R | 0.0156 | 156 |  |
| 4 | 1 | TIP T | 3 | 3 |  |
| 5 | 2 | GEOM X | 0.4841 | 4841 |  |
| 6 | 2 | GEOM Z | 0.0037 | 37 |  |
| 7 | 2 | GEOM R | 0.0156 | 156 |  |
| 8 | 2 | TIP T | 3 | 3 |  |
| 9 | 3 | WEAR X | -0.0040 | -40 |  |
| 10 | 3 | GEOM X | 0.8168 | 8168 |  |
| 11 | 3 | GEOM Z | -0.6280 | -6280 |  |
| 12 | 3 | GEOM R | 0.0312 | 312 |  |
| 13 | 3 | TIP T | 3 | 3 |  |
| 14 | 4 | GEOM X | 0.1370 | 1370 |  |
| 15 | 4 | GEOM Z | 1.1890 | 11890 |  |
| 16 | 4 | TIP T | 3 | 3 |  |
| 17 | 5 | WEAR X | -0.0005 | -5 |  |
| 18 | 5 | GEOM X | -0.0731 | -731 |  |
| 19 | 5 | GEOM Z | 0.0105 | 105 |  |
| 20 | 6 | GEOM Z | 1.7750 | 17750 |  |
| 21 | 6 | WEAR R | 0.0156 | 156 |  |
| 22 | 6 | GEOM R | 0.0156 | 156 |  |
| 23 | 6 | TIP T | 2 | 2 |  |
| 24 | 7 | GEOM Z | 3.0930 | 30930 |  |
| 25 | 8 | GEOM Z | 2.5240 | 25240 |  |
| 26 | 8 | TIP T | 2 | 2 |  |
| 27 | 9 | WEAR X | 0.0005 | 5 |  |
| 28 | 9 | GEOM X | -0.2350 | -2350 |  |
| 29 | 9 | GEOM Z | 2.0140 | 20140 |  |
| 30 | 9 | GEOM R | 0.0156 | 156 |  |
| 31 | 10 | WEAR X | -0.0030 | -30 |  |
| 32 | 10 | GEOM Z | -0.0357 | -357 |  |
| 33 | 11 | GEOM X | -0.3602 | -3602 |  |
| 34 | 11 | GEOM Z | 0.0030 | 30 |  |
| 35 | 12 | WEAR X | -0.0015 | -15 |  |
| 36 | 12 | GEOM X | 0.6538 | 6538 |  |
| 37 | 12 | WEAR Z | 0.0015 | 15 |  |
| 38 | 12 | GEOM Z | -0.2430 | -2430 |  |
| 39 | 13 | GEOM X | 0.6527 | 6527 |  |
| 40 | 13 | GEOM Z | -0.2520 | -2520 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe55-capability-sweep-20260806.json`
