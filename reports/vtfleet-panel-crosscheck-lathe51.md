# Panel cross-check sheet — VIPER VT-21 (CNC Lathe 1, 10.1.10.51)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-06 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | WEAR X | -0.0105 | -105 |  |
| 2 | 1 | GEOM X | -0.1028 | -1028 |  |
| 3 | 1 | GEOM R | 0.0313 | 313 |  |
| 4 | 1 | TIP T | 3 | 3 |  |
| 5 | 2 | WEAR X | -0.0010 | -10 |  |
| 6 | 2 | GEOM X | 0.8467 | 8467 |  |
| 7 | 2 | GEOM Z | 0.0055 | 55 |  |
| 8 | 2 | GEOM R | 0.0156 | 156 |  |
| 9 | 2 | TIP T | 3 | 3 |  |
| 10 | 3 | GEOM X | -1.0442 | -10442 |  |
| 11 | 3 | GEOM Z | 0.9824 | 9824 |  |
| 12 | 4 | WEAR X | 0.0085 | 85 |  |
| 13 | 4 | GEOM X | -0.5150 | -5150 |  |
| 14 | 4 | GEOM Z | 3.0205 | 30205 |  |
| 15 | 4 | GEOM R | 0.0156 | 156 |  |
| 16 | 4 | TIP T | 2 | 2 |  |
| 17 | 5 | GEOM Z | 3.0074 | 30074 |  |
| 18 | 6 | WEAR X | -0.0025 | -25 |  |
| 19 | 6 | GEOM X | -0.2400 | -2400 |  |
| 20 | 6 | GEOM Z | 2.5468 | 25468 |  |
| 21 | 6 | GEOM R | 0.0156 | 156 |  |
| 22 | 6 | TIP T | 2 | 2 |  |
| 23 | 8 | GEOM Z | 3.2385 | 32385 |  |
| 24 | 10 | GEOM Z | 6.3025 | 63025 |  |
| 25 | 11 | WEAR X | -0.0310 | -310 |  |
| 26 | 11 | GEOM X | 0.2795 | 2795 |  |
| 27 | 11 | GEOM Z | -0.0015 | -15 |  |
| 28 | 12 | GEOM X | 1.4632 | 14632 |  |
| 29 | 12 | WEAR Z | -0.0010 | -10 |  |
| 30 | 12 | GEOM Z | -0.2310 | -2310 |  |
| 31 | 13 | GEOM X | -0.5923 | -5923 |  |
| 32 | 13 | GEOM Z | -0.2405 | -2405 |  |
| 33 | 24 | WEAR X | 0.0110 | 110 |  |
| 34 | 24 | GEOM X | -0.5065 | -5065 |  |
| 35 | 24 | GEOM Z | 1.9070 | 19070 |  |
| 36 | 26 | WEAR X | 0.0045 | 45 |  |
| 37 | 26 | GEOM X | -0.2400 | -2400 |  |
| 38 | 26 | GEOM Z | 3.0658 | 30658 |  |
| 39 | 36 | GEOM Z | 1.3021 | 13021 |  |
| 40 | 40 | GEOM X | 1.0946 | 10946 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe51-capability-sweep-20260806.json`
