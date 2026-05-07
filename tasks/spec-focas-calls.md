# tasks/spec-focas-calls.md

FOCAS function spec for **Lance Mighty Viper LG-1000AP, FANUC 0i-MF**, served by `fwlib30i64.dll` (FS30i-family processing DLL).

## Status

**Decision-2: ready for sign-off.** All 20 v1 functions verified present in the header. Hand-merged from `tasks/spec-focas-calls.generated.md` (extractor commit `c065cef`).

Once dbc00per signs off on this doc, `shared/focas/client.py` is unblocked. Phase 6 write paths remain blocked behind Phase 1 / Phase 6 gates regardless.

## Source attestation

- Header: `C:\Fanuc\FwLib64-runtime\Fwlib64.h` on the Lance dev box
- Runtime DLLs (loaded at client startup): `Fwlib64.dll` (front-end), `fwlibe64.dll` (TCP/IP), `fwlib30i64.dll` (processing for FS30i family inc. 0i-MF)
- Extractor: `scripts/extract_focas_signatures.py`, commit `c065cef`
- Raw extraction artifact (audit trail): `tasks/spec-focas-calls.generated.md`

## Forbidden function names

The following names are **NOT exposed by `fwlib30i64.dll`** and must not appear in `client.py` or anywhere else in `shared/focas/`. Each was tried in the first extractor pass and flagged NOT FOUND:

| Forbidden | Reason | Use instead |
|---|---|---|
| `cnc_rdsysinfo` | FS-16/18/21-era name | `cnc_sysinfo`, `cnc_sysinfo_ex` |
| `cnc_rdmode` | FS-16/18/21-era name | `cnc_statinfo` (`ODBST.aut` + `ODBST.run`) |
| `cnc_rdtcode` | FS-16/18/21-era name | `cnc_modal` with T-aux type |
| `cnc_rdtoolgrp_id` | FS-16/18/21-era name | `cnc_rdngrp` + `cnc_rdgrpid` / `cnc_rdgrpid2` + `cnc_rdusegrpid` |

R9 mitigation lives here. If a future contributor wants to add a FOCAS function, the function must appear below with its verbatim signature first.

---

# 1. Connection lifecycle

## `cnc_allclibhndl3`

```c
/*---------------------*/
/* Ethernet connection */
/*---------------------*/

/* allocate library handle 3 */
FWLIBAPI short WINAPI cnc_allclibhndl3( const char *, unsigned short, long, unsigned short * );
```

**Args**: `(ip_addr, port, timeout, &handle_out)`. Port = 8193 for the Viper. Timeout in seconds (per FOCAS2 docs — verify on first call). Handle is `unsigned short` written to the last arg.

**Use**: Once per machine at poller startup. Return short = error code; 0 on success.

## `cnc_freelibhndl`

```c
/* free library handle */
FWLIBAPI short WINAPI cnc_freelibhndl( unsigned short ) ;
```

**Use**: Once per machine at poller shutdown. Always called from a `finally`/`__aexit__` to avoid handle leaks across reconnects.

## `cnc_settimeout`

```c
/* set timeout for socket */
FWLIBAPI short WINAPI cnc_settimeout( unsigned short, long );
```

**Args**: `(handle, timeout)`. Per FOCAS2 docs, the timeout argument is in seconds, applies to subsequent calls on this handle.

**Use**: Once after `cnc_allclibhndl3`. Default we'll set: 3 seconds. Beyond that, the circuit breaker takes over.

---

# 2. System info

## `cnc_sysinfo`

```c
/* read CNC system information */
FWLIBAPI short WINAPI cnc_sysinfo( unsigned short, ODBSYS * ) ;

typedef struct odbsys {
    short   addinfo ;       /* additional information  */
    short   max_axis ;      /* maximum axis number */
    char    cnc_type[2] ;   /* cnc type <ascii char> */
    char    mt_type[2] ;    /* M/T/TT <ascii char> */
    char    series[4] ;     /* series NO. <ascii char> */
    char    version[4] ;    /* version NO.<ascii char> */
    char    axes[2] ;       /* axis number<ascii char> */
} ODBSYS ;
```

**Use**: Once at startup. Verify `cnc_type == "0i"`, `mt_type == "M"`, `series == "D4F1"` (Viper SYS-CONF), `version == "15.0"`. Mismatch → refuse to start poller; log clearly. R9 detection lives here.

## `cnc_sysinfo_ex`

```c
/* read CNC system path information */
FWLIBAPI short WINAPI cnc_sysinfo_ex( unsigned short, ODBSYSEX * ) ;
```

`ODBSYSEX` is large — full def in `tasks/spec-focas-calls.generated.md`. Notable fields: `max_axis`, `max_path`, `path[MAX_CNCPATH]` per-path info.

**Use**: Optional, supplemental. v1 single-path Viper is single-path; we'll log `max_path` and `ctrl_path` at startup as a sanity check.

---

# 3. Machine status

## `cnc_statinfo`

```c
/* read CNC status information */
FWLIBAPI short WINAPI cnc_statinfo( unsigned short, ODBST * ) ;

typedef struct odbst {
    short dummy[2];     /* dummy                    */
    short aut;          /* selected automatic mode  */
    short manual;       /* selected manual mode     */
    short run;          /* running status           */
    short edit;         /* editting status          */
    short motion;       /* axis, dwell status       */
    short mstb;         /* m, s, t, b status        */
    short emergency;    /* emergency stop status    */
    short write;        /* writting status          */
    short labelskip;    /* label skip status        */
    short alarm;        /* alarm status             */
    short warning;      /* warning status           */
    short battery;      /* battery status           */
} ODBST ;
```

**Use**: Every poll cycle. This is the canonical status read. Maps to our `MachineStatus` Pydantic model:

| `ODBST` field | `MachineStatus` field | Notes |
|---|---|---|
| `aut` | `mode` | 0=MDI, 1=MEM, 2=*** (third), 3=EDIT, 4=HND, 5=JOG, 6=Teach in JOG, 7=Teach in HND, 8=INC, 9=REF, 10=RMT — **verify on first read against FOCAS2 doc** |
| `run` | `running` | 0=STOP, 1=HOLD, 2=STaRT, 3=MSTR (restart), 4=hold reset (verify) |
| `emergency` | `emergency_stop` | 0=normal, 1=E-stop |
| `alarm` | (separate field — propagate to AlarmEntry list) | nonzero = alarm active |

**Mode lockout (R6)**: writes are refused when `aut == 1 (MEM)` AND `run == 2 (STaRT)`. The writer reads this immediately before any `cnc_wrtofs`.

## `cnc_statinfo2`

```c
/* read CNC status information */
FWLIBAPI short WINAPI cnc_statinfo2( unsigned short, ODBST2 * ) ;
```

`ODBST2` is similar but adds `tmmode` (T/M switch state on TT controls — irrelevant for Viper which is M-only) and `restart` (SBK edit state).

**Use**: Optional. Stick with `cnc_statinfo` for v1. Reserved for future TT/multi-mode controls.

---

# 4. Modal info (current T)

## `cnc_modal`

```c
/* read modal data */
FWLIBAPI short WINAPI cnc_modal( unsigned short, short, short, ODBMDL * ) ;

typedef struct odbmdl {
    short   datano;
    short   type;
    union {
        char    g_data;
        char    g_rdata[12];
        char    g_1shot;
        struct { long aux_data; char flag1; char flag2; } aux;
        struct { long aux_data; char flag1; char flag2; } raux1[25];
    } modal;
} ODBMDL ;
```

**Args**: `(handle, datano, type, &out)`. `datano` selects which modal to read (e.g., aux T). `type` selects category — 0/1/2/3 per FOCAS2 doc.

**Use**: Read current T number once per poll cycle by calling with the T-aux modal selector. Decode `modal.aux.aux_data` (long) → `MachineStatus.current_t_number`.

**Open question O1**: confirm exact `(datano, type)` constants for "current T modal" against the FOCAS2 developer manual. Provisional values to verify on first run: `datano = -3` (T modal), `type = 1` (current). The header doesn't expose constants for these — they live in the FOCAS2 manual.

---

# 5. Tool offsets

## `cnc_rdtofsinfo`

```c
/* read tool offset information */
FWLIBAPI short WINAPI cnc_rdtofsinfo( unsigned short, ODBTLINF * ) ;

typedef struct odbtlinf {
    short   ofs_type;
    short   use_no;
} ODBTLINF;
```

**Use**: Once at startup, again on machine config change. **Decision-3 resolved at runtime here.**

- `ofs_type` selects which member of the `IODBTO` union (below) holds offsets for this control. For 0i-MF mill, the expected value corresponds to one of the `m_*` variants (`m_ofs`, `m_ofs_a`, `m_ofs_b`, `m_ofs_c`, or one of the `_at`/`_bt`/`_ct` cutter-tip variants).
- `use_no` = number of offset entries in use (≤ 400 on the Viper per `docs/02-data-model.md`).

**Open question O2**: empirical determination of `ofs_type` on the Viper. First integration test (Phase 1 gate) reads this and writes the resulting union-member name into `tasks/spec-focas-calls.md` under this section. No assumption is hard-coded in `client.py`.

## `cnc_rdtofs`

```c
/* read tool offset value */
FWLIBAPI short WINAPI cnc_rdtofs( unsigned short, short, short, short, ODBTOFS * ) ;

typedef struct odbtofs {
    short   datano ;    /* data number */
    short   type ;      /* data type */
    long    data ;      /* data */
} ODBTOFS ;
```

**Args**: `(handle, num, type, length, &out)`. `num` = offset register number (1..400). `type` = bank selector (geom-H, wear-H, geom-D, wear-D — exact integer values from FOCAS2 manual). `length = sizeof(ODBTOFS) = 8`. `data` is a raw integer at the control's offset increment.

**Unit conversion**: `data` is an integer count of the FANUC offset-increment parameter (typically 0.001 mm → divide `data` by 1000). The increment is read from FANUC parameter 1013 / 1006 — confirm at runtime on the Viper. **All conversion happens at the FOCAS boundary in `client.py`, never in business logic.**

**Use**: Single-register lookup, fallback / spot-check path. Steady-state polling uses `cnc_rdtofsr`.

## `cnc_rdtofsr`

```c
/* read tool offset value(area specified) */
FWLIBAPI short WINAPI cnc_rdtofsr( unsigned short, short, short, short, short, IODBTO * ) ;
```

`IODBTO` is a union over many variants — full def in `tasks/spec-focas-calls.generated.md`. The variants we care about for 0i-MF mill:

| Variant | Layout | Likely match |
|---|---|---|
| `m_ofs[5]` | M Each — 5 longs per record, each is a separate offset bank | candidate |
| `m_ofs_a[5]` | M-A All — 5 longs per record (geom-H, wear-H, geom-D, wear-D, +1) | candidate |
| `m_ofs_b[10]` | M-B All — 10 longs (extended) | possible |
| `m_ofs_c[20]` | M-C All — 20 longs | unlikely |

**Use**: Range read, every poll cycle. Significantly fewer round-trips than 400× `cnc_rdtofs`. Decoded into our `OffsetRegister` model.

**Args**: `(handle, num_start, num_end, type, length, &out)`. `length` is the total byte length of the buffer caller must allocate. Convention: read in chunks of e.g. 50 registers per call, depending on observed latency.

**Open question O3**: confirm the union variant the Viper uses, by reading `cnc_rdtofsinfo.ofs_type` on first connection. Once empirically determined, the union member name is recorded here.

## `cnc_wrtofs`

```c
/* write tool offset value */
FWLIBAPI short WINAPI cnc_wrtofs( unsigned short, short, short, short, long ) ;
```

**Args**: `(handle, num, type, length, value)`. Single-register write. `value` is the raw integer at the control increment (mm × 1000 typically).

**PHASE 6 ONLY.** Captured here for completeness and so the spec doc is self-contained, but `client.py` does not import or wrap this until Phase 6. Two-stage UI confirmation, mode lockout via `cnc_statinfo`, read-after-write via `cnc_rdtofs`, drift abort, audit log — all per `docs/03-focas-integration.md` and `docs/07-risks.md` R6.

---

# 6. Magazine / pot table

## `cnc_rdmagazine`

```c
/* read magazine management data */
FWLIBAPI short WINAPI cnc_rdmagazine( unsigned short, short *, IODBTLMAG * ) ;

typedef struct iodbtlmag {
    short magazine;
    short pot;
    short tool_index;
} IODBTLMAG;
```

**Args**: `(handle, &num_inout, &out)`. Per FOCAS2 docs the second arg is in/out: caller passes the requested entry count, control writes back actual count returned. The third arg is an array of `IODBTLMAG` records — caller allocates `num_inout` records.

**Decoded to our model**: each record → one `PotEntry`. `tool_index` corresponds to the T number stored in that pot (or 0 / -1 for empty — verify).

**Open question O4**: exact semantics of `magazine` field on the Viper (single-magazine machine — likely always 0 or 1). Empirically determined on first read.

**Open question O5**: `tool_index` encoding — does 0 mean "empty pot" or is there a sentinel like -1? Verify on first read; update `PotEntry.t_number = None` mapping accordingly.

---

# 7. Tool life management

Polled every cycle. Sequence:
1. `cnc_rdngrp` — total group count
2. For each group: `cnc_rdgrpid` (or `cnc_rdgrpid2`) — group ID
3. `cnc_rdusegrpid` once per cycle — currently-in-use / next / selecting groups
4. For each tool in each group: `cnc_rd1tlifedata` — per-tool life data + H/D codes

## `cnc_rdngrp`

```c
/* read tool life management data(number of tool groups) */
FWLIBAPI short WINAPI cnc_rdngrp( unsigned short, ODBTLIFE2 * ) ;

typedef struct odbtlife2 {
    short   dummy[2] ;  /* dummy */
    long    data ;      /* data */
} ODBTLIFE2 ;
```

**Use**: `data` = number of tool life groups defined on the control. Cap iteration loops. If 0 → tool life management is disabled or empty; skip the rest of section 7.

## `cnc_rdgrpid`

```c
/* read tool life management data(tool group number) */
FWLIBAPI short WINAPI cnc_rdgrpid( unsigned short, short, ODBTLIFE1 * ) ;

typedef struct odbtlife1 {
    short   dummy ; /* dummy */
    short   type ;  /* data type */
    long    data ;  /* data */
} ODBTLIFE1 ;
```

**Args**: `(handle, group_index, &out)`. `data` = group ID for that index slot.

**Use**: Iterate `1..ngrp`, collect group IDs. Use for reverse lookup (tool → group).

## `cnc_rdgrpid2`

```c
/* read tool life management data(tool group number) 2 */
FWLIBAPI short WINAPI cnc_rdgrpid2( unsigned short, long, ODBTLIFE5 * ) ;

typedef struct odbtlife5 {
    long    dummy ; /* dummy */
    long    type ;  /* data type */
    long    data ;  /* data */
} ODBTLIFE5 ;
```

**Use**: Same as `cnc_rdgrpid` but accepts a `long` group index for >32K groups. Probably unnecessary on the Viper (group counts are small). Capture it here for future-proofing; v1 uses `cnc_rdgrpid`.

## `cnc_rdusegrpid`

```c
/* read tool life management data(used tool group number) */
FWLIBAPI short WINAPI cnc_rdusegrpid( unsigned short, ODBUSEGR * ) ;

typedef struct odbusegr {
    short   datano; /* dummy */
    short   type;   /* dummy */
    long    next;   /* next use group number */
    long    use;    /* using group number */
    long    slct;   /* selecting group number */
} ODBUSEGR;
```

**Use**: Once per poll cycle. UI shows operator which group is currently in use, which is queued.

## `cnc_rd1tlifedata`

```c
/* read tool life management data(tool data1) */
FWLIBAPI short WINAPI cnc_rd1tlifedata( unsigned short, short, short, IODBTD * ) ;

typedef struct iodbtd {
    short   datano;     /* tool group number */
    short   type;       /* tool using number */
    long    tool_num;   /* tool number */
    long    h_code;     /* H code */
    long    d_code;     /* D code */
    long    tool_inf;   /* tool information */
} IODBTD;
```

**Args**: `(handle, group_num, tool_using_num, &out)`. Per-tool-within-group data.

**This is the call that wires our tool life model to FANUC truth.** Returned fields:
- `tool_num` → T number
- `h_code` → H **register number** (not value), maps to `tooling.assignment.h_register`
- `d_code` → D **register number**, maps to `tooling.assignment.d_register`
- `tool_inf` → bitfield: lifetime expired flag, skip flag, etc. (decode per FOCAS2 doc)

**Open question O6**: `tool_inf` bit layout on 0i-MF. Verify against FOCAS2 manual.

---

# 8. Alarms

## `cnc_rdalmmsg`

```c
/* read alarm message */
FWLIBAPI short WINAPI cnc_rdalmmsg( unsigned short, short, short *, ODBALMMSG * ) ;

typedef struct odbalmmsg {
    long    alm_no;
    short   type;
    short   axis;
    short   dummy;
    short   msg_len;
    char    alm_msg[32];
} ODBALMMSG ;
```

32-char alarm message. Use only as fallback if `cnc_rdalmmsg2` is rejected by the control for some reason.

## `cnc_rdalmmsg2` (preferred)

```c
/* read alarm message */
FWLIBAPI short WINAPI cnc_rdalmmsg2( unsigned short, short, short *, ODBALMMSG2 * ) ;

typedef struct odbalmmsg2 {
    long    alm_no;
    short   type;
    short   axis;
    short   dummy;
    short   msg_len;
    char    alm_msg[64];
} ODBALMMSG2 ;
```

**Args**: `(handle, type, &num_inout, &out)`. `type` selects alarm category (-1 = all). `num_inout` is in/out per FOCAS2 docs — caller passes max records, control writes actual.

**Use**: Every poll cycle. Decoded to `AlarmEntry { code=alm_no, axis, message=alm_msg }`. 64-char message preferred over 32-char.

---

# Open questions for sign-off

The questions above are gathered here for visibility. None block writing `client.py` against the verified signatures — they're either runtime determinations or FOCAS2 manual lookups that resolve before / during the first integration test.

| ID | Question | Status / resolution |
|---|---|---|
| O1 | `cnc_modal` `(datano, type)` constants for current T | **RESOLVED — but not via `cnc_modal`.** Empirically determined that the FS30i + Mighty Viper random-ATC stack exposes head/next tool only as **PMC R-area bytes**, not as NC modal data. `cnc_modal(-3, 1)` returned 0 with a tool loaded; `cnc_rdtdiseltool` returned `EW_NOOPT`; no `#4xxx` / `#5xxx` system macro carried the panel value (probes v1..v6 all whiffed). All seven documented magazine-state functions (`cnc_rdcurmgr`, `cnc_rdcurpot`, `cnc_rdpotinfo`, `cnc_rdmagsts`, `cnc_rdspmaint`, `cnc_rdmgrptool`, `cnc_rdmagazine`) are absent or return `EW_NOOPT`. Resolution path: snapshot/diff full PMC state across a tool change (`probe_modal_v7.py`) isolated 4 changed bytes; `probe_modal_v8.py` + operator panel cross-check confirmed **R327 = HEAD, R325 = NEXT** (single bytes, range 0..99 for tool IDs). `R321` is a fast-mutating scratch register the ladder uses while reading R325/R327 — DO NOT bind it. Bound in `client.py` via `pmc_rdpmcrng(type_a=5, type_d=0, addr_s=R327)` as the head read. |
| O2 | `cnc_rdtofsinfo.ofs_type` value on Viper | **RESOLVED**: `ofs_type=2`. 400 registers. The panel actually exposes 4 banks (GEOM H, WEAR H, GEOM D, WEAR D), but `cnc_rdtofs` accepts only types 1, 2, 3 (type=4 returns EW_ATTRIB). See "Verified type-code mapping" below. |
| O3 | `IODBTO` union variant name for Viper offsets | DEFERRED to Phase 2 — `cnc_rdtofsr` not yet used; client uses `cnc_rdtofs` (single) per the verified type-code map. |
| O4 | `IODBTLMAG.magazine` value on single-magazine Viper | N/A — magazine option not licensed (see O5/EW_NOOPT). |
| O5 | `IODBTLMAG.tool_index` empty-pot sentinel | N/A — `cnc_rdmagazine` returns `EW_NOOPT` (rc=6) on this Viper. The magazine option isn't licensed. `read_pots()` now returns `()` gracefully. Pot tracking via FOCAS is structurally unavailable on this control; alternative paths (`cnc_rdparam` for pot-table parameters, or operator-driven manual assignment) need design work for v1. |
| O6 | `IODBTD.tool_inf` bit layout on 0i-MF | OPEN — tool life management not yet exercised; will surface when we have a tool life group configured. |
| O7 | `cnc_settimeout` timeout units (sec vs ms) | **RESOLVED**: seconds. Connection succeeded with `timeout_seconds=3`. Reads do not stall for thousands of seconds. |
| O8 | Offset increment for long → mm conversion | **RESOLVED**: `0.0001` mm/count, NOT the FANUC standard 0.001. Panel `H50 = 7.4050 mm` matches FOCAS `type=3 raw=74050 × 0.0001`. Phase 2 hardening: bind `cnc_rdparam` and read parameter 1013 to verify at startup. |

# Verified type-code mapping (Lance Viper, ofs_type=2)

Phase 1 panel cross-check completed via two probes — register 50 (only GEOM banks non-zero) and register 396 (all four banks distinct non-zero values):

| Panel column | Panel @ 396 (mm) | FOCAS type | FOCAS raw | Verified mapping |
|---|---|---|---|---|
| GEOM (H) | 3.0000 | type=3 | 30000 | `type=3 → H_GEOM` ✓ |
| WEAR (H) | 1.7500 | type=2 | 17500 | `type=2 → H_WEAR` ✓ |
| GEOM (D) | -0.3000 | type=1 | -3000 | `type=1 → D_GEOM` ✓ |
| WEAR (D) | 2.0000 | type=4 | rejected (EW_ATTRIB) | **NOT READABLE** |

Two findings:

1. **H/D type codes are swapped from FANUC standard docs.** Standard docs say type=1=H_GEOM and type=3=D_GEOM. This 0i-MF has them swapped (type=1=D_GEOM, type=3=H_GEOM). Wear codes follow: type=2=H_WEAR.

2. **D_WEAR is structurally unreadable via FOCAS on this control.** The panel stores and displays it (register 396 shows WEAR(D)=2.0000) but `cnc_rdtofs(type=4)` returns `EW_ATTRIB` (rc=4) regardless of value. This is a license/option limitation on the Lance Viper's FOCAS configuration. UI must display "N/A" for D_WEAR rows on machines with `ofs_type=2`; audit log will have no D_WEAR entries.

`client.py` records the verified mapping in `_OFFSET_TYPE_MAP_MEMORY_B` with type=4 deliberately omitted. `read_offsets` performs `use_no × 3 = 1200` calls per cycle on the Viper (3 readable banks × 400 registers).

# Verified control identity (Lance Mighty Viper LG-1000AP)

From the Phase 1 integration smoke against `10.1.10.58:8193` on 2026-05-06:

```
ODBSYS:
  cnc_type   = ' 0'    -> stripped = '0' (FANUC right-justifies to 2 chars)
  mt_type    = ' M'    -> stripped = 'M'
  series     = 'D4F1'  (0i-MF model variant identifier)
  version    = '15.0'
  max_axis   = 32      (firmware capability; 4 actually configured)
  axes       = '04'    (4 axes configured)
  addinfo    = 1026

ODBTLINF:
  ofs_type   = 2       (Memory Type B: length + diameter, no geom/wear split)
  use_no     = 400

cnc_rdmagazine: returns EW_NOOPT (rc=6) — option not licensed
```

The `assert_expected_control` defaults in `client.py` are calibrated to these values: `cnc_type='0'`, `mt_type='M'`, `series='D4F1'`. Pass `expected_series=None` when adding a new control of unknown subseries.

---

# Sign-off

- [x] dbc00per: spec reviewed, approved for `client.py` implementation against the function names and struct shapes above. Open questions O1–O8 acceptable as integration-test deliverables.

`shared/focas/client.py` unblocked for Phase 1 read coverage as of this checkbox. `cnc_wrtofs` remains Phase-6-fenced.
