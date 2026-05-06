# tasks/spec-focas-calls.md

FOCAS function-name and argument verification for FANUC 30i-B (Viper LG-1000AP, AG100 TBD).

**Status: NOT STARTED.** No FOCAS client code may reference any function below until the row is verified against the FOCAS2 SDK documentation for series 30i-B (not 16/18/21/0i — those have different signatures). See `docs/07-risks.md` R9.

Each row must list: provisional name → confirmed 30i-B name → SDK doc section → arg signature → return shape → tested-on-Viper date.

---

## Reads

| Purpose | Provisional name | Confirmed 30i-B name | SDK section | Args | Return | Verified on Viper |
|---|---|---|---|---|---|---|
| Connect | `cnc_allclibhndl3` | | | | | |
| Disconnect | `cnc_freelibhndl` | | | | | |
| Offset table read (H_geom, H_wear, D_geom, D_wear) | `cnc_rdtofs` | | | | | |
| Tool offset count | `cnc_rdtofsinfo` | | | | | |
| Pot / magazine table | `cnc_rdmagazine` (TBD) | | | | | |
| Tool life data | `cnc_rdtoollife` (TBD) | | | | | |
| Active T number | `cnc_rdcurrent_tcode` (TBD) | | | | | |
| Machine mode (AUTO / MDI / EDIT / MEM) | `cnc_statinfo` | | | | | |
| Alarm status | `cnc_alarm` / `cnc_rdalmmsg` | | | | | |
| Axis position | `cnc_rdposition` (TBD) | | | | | |

## Writes (Phase 6 only — DO NOT IMPLEMENT until Phase 1 read coverage is green)

| Purpose | Provisional name | Confirmed 30i-B name | SDK section | Args | Return | Verified on Viper |
|---|---|---|---|---|---|---|
| Offset write | `cnc_wrtofs` | | | | | |
| Offset write (range) | `cnc_wrtofsr` | | | | | |

---

## Open questions

1. Does 30i-B require a separate `cnc_setpath` call before reads on multi-path controls? Viper is single-path, AG100 unverified.
2. Offset-type encoding (`type` arg in `cnc_rdtofs`): confirm mapping for H_geom / H_wear / D_geom / D_wear on this control's parameter setup.
3. Pot/magazine read function name on 30i-B — `cnc_rdmagazine` is the documented name for some series; verify it exists for 30i-B before relying on it.
4. Does `pyfocas` expose all of the above (Decision-1 input)?

Until every row has a confirmed name and SDK reference, `shared/focas/client.py` does not get written.
