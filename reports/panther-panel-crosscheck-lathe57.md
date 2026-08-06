# Panel cross-check sheet — PANTHER JAKE_2100LYS (CNC Lathe 7, 10.1.10.57)

Gate stage 6 (`docs/10` par.7). Values below were READ from the control
2026-08-05 (read-only sweep). At the OFFSET screen, confirm each panel
value matches the DECODED column exactly (decoded at 0.0001 inch/count,
IS-B + inch input, fleet-verified via params 1013 / setting INI).
TIP rows are integer codes, not distances.

A mismatch on ANY row = STOP: the bank map is not locked for this
machine; report which row and what the panel shows instead.

| # | Register | Panel field | Expected panel value | Read raw | OK? |
|---|---|---|---|---|---|
| 1 | 1 | WEAR X | 0.0050 | 50 |  |
| 2 | 1 | GEOM X | 4.0288 | 40288 |  |
| 3 | 1 | GEOM Z | 2.9456 | 29456 |  |
| 4 | 1 | GEOM R | 0.0312 | 312 |  |
| 5 | 1 | TIP T | 3 | 3 |  |
| 6 | 2 | GEOM X | 3.9628 | 39628 |  |
| 7 | 2 | WEAR Z | -0.0090 | -90 |  |
| 8 | 2 | GEOM Z | 0.0275 | 275 |  |
| 9 | 2 | TIP T | 3 | 3 |  |
| 10 | 3 | GEOM Z | 4.1977 | 41977 |  |
| 11 | 4 | WEAR X | -0.0015 | -15 |  |
| 12 | 4 | GEOM X | 3.9188 | 39188 |  |
| 13 | 4 | WEAR Z | 0.0020 | 20 |  |
| 14 | 4 | GEOM Z | 0.0175 | 175 |  |
| 15 | 4 | GEOM R | -0.0005 | -5 |  |
| 16 | 5 | GEOM Z | 4.7862 | 47862 |  |
| 17 | 6 | GEOM X | 4.9632 | 49632 |  |
| 18 | 6 | WEAR Z | 0.0020 | 20 |  |
| 19 | 6 | GEOM Z | 0.0175 | 175 |  |
| 20 | 6 | GEOM R | -0.0020 | -20 |  |
| 21 | 6 | TIP T | 7 | 7 |  |
| 22 | 7 | WEAR X | 0.0070 | 70 |  |
| 23 | 7 | GEOM X | -1.3415 | -13415 |  |
| 24 | 7 | GEOM Z | 3.4823 | 34823 |  |
| 25 | 7 | TIP T | 2 | 2 |  |
| 26 | 8 | WEAR X | 0.0055 | 55 |  |
| 27 | 8 | GEOM X | 3.4770 | 34770 |  |
| 28 | 8 | WEAR Z | -0.0050 | -50 |  |
| 29 | 8 | GEOM Z | 2.7106 | 27106 |  |
| 30 | 9 | GEOM X | 1.5745 | 15745 |  |
| 31 | 9 | GEOM Z | 5.2488 | 52488 |  |
| 32 | 9 | TIP T | 7 | 7 |  |
| 33 | 10 | GEOM Z | 3.5822 | 35822 |  |
| 34 | 10 | TIP T | 7 | 7 |  |
| 35 | 11 | GEOM Z | 4.0600 | 40600 |  |
| 36 | 11 | TIP T | 7 | 7 |  |
| 37 | 12 | GEOM X | 3.8822 | 38822 |  |
| 38 | 12 | WEAR Z | 0.0040 | 40 |  |
| 39 | 12 | GEOM Z | 2.1684 | 21684 |  |
| 40 | 12 | TIP T | 3 | 3 |  |

Checked by: ____________  Date: ____________

Source artifact: `reports/lathe57-capability-sweep-20260805.json`

---
**VERIFIED 2026-08-05 (dbc00per, CNC Screen Display screenshots — GEOMETRY G001-G018 + WEAR W001-W018 vs simultaneous reads): ALL CELLS MATCH — bank map LOCKED.**
