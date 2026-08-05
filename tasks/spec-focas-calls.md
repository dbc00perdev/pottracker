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

**Open question O1**: ~~confirm exact `(datano, type)` constants for "current T modal"~~ **RESOLVED — `cnc_modal` does not expose current T on this control at all.** HEAD/NEXT live in the OEM PMC ladder (`R327`/`R325`, raw bytes, panel-confirmed); see the O1 row in the resolution table below. `cnc_modal` is retained only for G-group modal reads.

---

## `cnc_rdmacro`

```c
/* read custom macro variable */
FWLIBAPI short WINAPI cnc_rdmacro( unsigned short, short, short, ODBM * ) ;

typedef struct odbm {
    short   datano;   /* variable number */
    short   dummy;
    long    mcr_val;  /* macro value (mantissa) */
    short   dec_val;  /* decimal-point position; < 0 => vacant */
} ODBM ;
```

**Args**: `(handle, number, length, &out)`. `number` = the macro variable
(#5061-#5063 for the G31 skip position). `length` = **10** (FANUC's documented
data length — NOT `sizeof(ODBM)`, which ctypes pads to 12 for `long` alignment).

**Value decode**: `mcr_val / 10**dec_val`; `dec_val < 0` (== -1) means the
variable is vacant → our `MacroVariable.value = None`. Bound in `client.py`
(`decode_macro` / `read_macros`, default set `_SKIP_MACRO_VARS = (5061,5062,5063)`).

**Use — presetter attribution (#2)**: the tool presetter's G31 touch latches the
skip position into #5061 (X) / #5062 (Y) / #5063 (Z). A genuine change in these
in the same poll cycle as an **H_GEOM** offset change tags that write
`presetter_verified`; no fresh skip = `manual_edit` (R11 trust signal). Scoped to
H_GEOM because only the presetter writes tool-length registers — G31 is *also*
the spindle probe's skip mechanism, so the skip alone only says "a G31 touch
happened." Verified live 2026-07-08: presetting offset #21 (0 → 5.6883) coincided
with #5061 −5.51→−4.01 and #5063 3.93→4.35. Skip vars mirrored in
`shared.focas_macro_var` (migration 0004); attribution tag rides in
`audit_log.after_value` JSONB.

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

> **Reality on this Viper: `cnc_rdmagazine` is `EW_NOOPT` (option unlicensed).**
> The pot table is instead read from the **PMC D-area** via `pmc_rdpmcrng`
> (pot N at D(104+N), packed BCD) — see the **Verified Viper OEM PMC / macro
> bindings** section below, which is the authoritative pot/head/next/skip
> reference. `cnc_rdmagazine` is retained in `client.py` as
> `_read_pots_magazine()` for a future magazine-licensed control (Phase-8
> per-machine dispatch); `read_pots()` uses the PMC path.

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
| O2 | `cnc_rdtofsinfo.ofs_type` value on Viper | **RESOLVED**: `ofs_type=2`. 400 registers. The panel exposes 4 banks (GEOM H, WEAR H, GEOM D, WEAR D) and **all four read** — `type=3/2/1/0` respectively. (Superseded 2026-07-15: the earlier "only types 1,2,3" claim missed type=0.) See "Verified type-code mapping" below. |
| O3 | `IODBTO` union variant name for Viper offsets | DEFERRED to Phase 2 — `cnc_rdtofsr` not yet used; client uses `cnc_rdtofs` (single) per the verified type-code map. |
| O4 | `IODBTLMAG.magazine` value on single-magazine Viper | N/A — magazine option not licensed (see O5/EW_NOOPT). |
| O5 | `IODBTLMAG.tool_index` empty-pot sentinel | N/A for `cnc_rdmagazine` (EW_NOOPT). **RESOLVED via a different path (2026-07-08):** the pot table lives in the **PMC D-area** (D105-128 = pots 1-24, packed BCD), read with `pmc_rdpmcrng`. Empty/reinit pots read their own ordinal and cells are STICKY (identity only, never presence) — so there is no `tool_index`-style "empty sentinel"; **presence = the offset table** (h_geom≠0), correlated per the occupancy model (#3). See the OEM bindings section. `read_pots()` now returns the live PMC pot map (confirmed vs panel). |
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
| WEAR (D) | 2.0000 | type=4 | rejected (EW_ATTRIB) | ~~**NOT READABLE**~~ — **SUPERSEDED 2026-07-15: it is `type=0`, see below** |

Two findings:

1. **H/D type codes are swapped from FANUC standard docs.** Standard docs say type=1=H_GEOM and type=3=D_GEOM. This 0i-MF has them swapped (type=1=D_GEOM, type=3=H_GEOM). Wear codes follow: type=2=H_WEAR.

2. ~~**D_WEAR is structurally unreadable via FOCAS on this control.**~~ **RETRACTED 2026-07-15 — D_WEAR is `type=0` and reads fine.** The original conclusion (license/option limitation, panel-only, UI must show "N/A") was drawn from `cnc_rdtofs(type=4) → EW_ATTRIB` without ever probing `type=0`. A read-only sweep of `type=0..9` on registers 396/50/20 found:

| Panel column | FOCAS type | Reg 396 read (2026-07-15) | Panel @ 396 (orig. cross-check) |
|---|---|---|---|
| GEOM (H) | type=3 | 2.5000 | 3.0000 (register since edited) |
| WEAR (H) | type=2 | 1.2000 | 1.7500 (since edited) |
| GEOM (D) | type=1 | -1.0000 | -0.3000 (since edited) |
| **WEAR (D)** | **type=0** | **2.0000** | **2.0000 ✓ exact match** |

A full `400 registers × 4 banks = 1600` read then completed with **zero rejects** (45.6s). The `type=0` values are small diameter trims on exactly the tools physically in the machine — reg 10 = -0.0130, reg 20 = -0.0057, reg 6 = -0.0007, reg 18 = -0.0005, reg 97 = +0.0034 — and zero on the probe (reg 50), matching the operator's description of WEAR D as the tight-tolerance diameter sizing field.

Combined-bank hypotheses are **refuted**: register 50 has GEOM D = 0.2360 but type=0 = 0 (so type=0 ≠ `D_GEOM+D_WEAR`); register 6 has GEOM H = 3.8360 but type=0 = -0.0007 (so type=0 ≠ a combined H bank). `type=4..9` all reject — 4 is simply not a valid code on this control.

**Corrected mapping (non-standard permutation): `type=0=D_WEAR, type=1=D_GEOM, type=2=H_WEAR, type=3=H_GEOM`.**

**CONFIRMED at the panel by dbc00per's brother, 2026-07-15** — WEAR (D) reads **-0.0130 at register 10** and **-0.0057 at register 20**, exactly matching the `type=0` reads. The mapping `type=0 = D_WEAR` is locked. **DONE 2026-07-28**: `0: RegisterType.D_WEAR` added to `_OFFSET_TYPE_MAP_MEMORY_B`; `read_offsets` = 1600 calls/cycle, measured **46.4s** live (within the 60s cadence). First mirrored cycle re-confirmed by dbc00per at the panel (WEAR(D) −0.0014 @ reg 40, 2.0000 @ reg 396 — exact matches). `cnc_rdtofsr` (range read) returns rc=2 for every type tried — not a working path.

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
               (pot table read from PMC D-area instead; see OEM bindings below)
```

The `assert_expected_control` defaults in `client.py` are calibrated to these values: `cnc_type='0'`, `mt_type='M'`, `series='D4F1'`. Pass `expected_series=None` when adding a new control of unknown subseries.

---

# Verified Viper OEM PMC / macro bindings (authoritative)

Everything the documented FOCAS surface does **not** expose on this control —
loaded/next tool, the pot table — lives in the **PMC ladder** (read-only via
`pmc_rdpmcrng`) or in **custom-macro system vars** (read-only via `cnc_rdmacro`).
These addresses are **OEM-specific to the Mighty Viper ladder** (NOT a FANUC
standard) — re-derive per machine in Phase 8 (AG100) with `probe_pot_table.py` /
`probe_modal_v7.py`; never assume they port. All reads below are non-destructive.

| What | Source | Encoding | `client.py` | Verified |
|---|---|---|---|---|
| **HEAD** — tool in spindle | PMC **R327** (byte) | raw 0..99 | `read_status().current_t_number` (`_PMC_R_HEAD_ADDR`) | panel ✓ (HEAD=T21 & =D104) |
| **NEXT** — pre-selected tool | PMC **R325** (byte) | raw 0..99 | `read_status().next_t_number` (`_PMC_R_NEXT_ADDR`) | panel ✓ (NEXT=T50) |
| **Spindle tool** | PMC **D104** (byte) | **BCD** | (occupancy #3; cross-checks R327) | panel ✓ (T21) |
| **Pot table** — pot N | PMC **D(104+N)** (byte); D105=pot 1 … D128=pot 24 | **BCD** (`decode_pot_bcd`) | `read_pots()` → `read_pots_pmc()` | panel ✓ (pots 1/3/4/5/6/21) |
| **G31 skip position** | macro **#5061** (X) / **#5062** (Y) / **#5063** (Z) | `mcr_val/10^dec_val`; `dec_val<0`=vacant (`decode_macro`) | `read_macros()`; mirror `shared.focas_macro_var` | live ✓ (#5063 moved on a preset) |

`R321` is a fast-mutating **scratch** register the ladder uses while reading
R325/R327 — never bind it (two consecutive reads disagree). Constants:
`_PMC_AREA_R=5`, `_PMC_AREA_D=9`, `_PMC_D_POT_BASE=105`, `_SKIP_MACRO_VARS=(5061,5062,5063)`.

## LG-1000AG bindings — verified per-machine 2026-07-29 (R18 discipline honored)

First contact + `probe_modal_v7` snapshot/diff on the **AG (10.1.10.59**, 0i-MF
`D4F1` **v23.0**, FOCAS licensed, Memory-B 400 regs): one observed tool change
(panel HEAD 20→50, NEXT 50→20) isolated the bindings. **Despite a different
hard-key panel (different ladder build), the AG uses the SAME core addresses:**

| What | AG evidence | Verdict |
|---|---|---|
| HEAD = **R327** raw | `20→50` = panel HEAD | ✓ locked |
| NEXT = **R325** raw | `50→20` = panel NEXT | ✓ locked |
| Spindle = **D104** BCD | `0x20→0x50` | ✓ locked |
| Pot table = **D105–128** BCD | `D123 0x50→0x20` = pot 19 T50→T20; **operator confirmed T20 physically in pot 19** | ✓ locked |
| R321 scratch | flipped mid-read | same trap — never bind |

AG-only extras (newer ladder rev keeps mirrors — noted, NOT bound): **R520** and
**F26** echo HEAD; **D27** echoes the spindle tool. Encoding split identical
(R raw / D BCD). Probe = **T50/H50 on the AG too** (H50 length present
post-teardown, T50 called to spindle during the probe pass).

**AG offset banks:** all four read cleanly via the AP's type-code permutation
(`0=D_WEAR,1=D_GEOM,2=H_WEAR,3=H_GEOM`); values shape-consistent. One-register
panel cross-check still pending before the mapping is called locked on the AG.

**⚠ AG registers 394–398 are RESERVED — Michael's custom offset numbers for his
programs (operator-confirmed 2026-07-29). Never zero/clean/write them; any future
write-path plausibility list must treat 394–398 as protected on the AG.** (They
were nearly cleaned as "test junk" — the no-write gate + flag-don't-guess rule
prevented real damage. Baseline: `reports/ag-first-contact-20260729.json`.)

**Two hardware traps (both bit us — see `tasks/lessons.md`):**
- **BCD, not raw.** T90 is stored as byte `0x90`=144, T33 as `0x33`=51. A raw-value
  search for 90 finds nothing; a `0..99` filter silently rejects any tool ≥ 80.
  Anchor pot searches on a *distinctive* known tool (T90), not T1.
- **`ODBM` length arg is 10, not `sizeof`.** `ctypes.sizeof(ODBM)`=12 (c_int32
  alignment pad); `cnc_rdmacro` wants the unpadded **10**.

## VIPER VT_23 (LATHE, 0i-TF) — offset bank mapping VERIFIED 2026-07-29

First lathe (10.1.10.53, series D6G1 v21.0, 2-axis, mt_type=T). `ofs_type=1`,
**99 registers**, `cnc_rdtofs` type codes **0-7** (8+ reject) — **panel-locked**
via dbc00per's OFFSET/GEOMETRY + OFFSET/WEAR photos vs the read-only sweep
(`reports/vt23-bank-mapping-verified-20260729.json`):

| code | bank | code | bank |
|---|---|---|---|
| 0 | X wear | 1 | X geometry |
| 2 | Z wear | 3 | Z geometry |
| 4 | R (nose radius) wear | 5 | R geometry |
| 6 | tip type | 7 | tip type (dup view) |

Textbook T-series interleave (wear even / geom odd) — the MILLS are the
non-standard ones, not this control. Client work to consume this = lathe
register model (X/Z/R/T per register, not H/D) — docs/11 machine-class split;
never present these as mill banks.

## VT_23 work offsets / WORK SHIFT — verified reads 2026-07-29

`cnc_rdzofs(handle, datano, type, length, IODBZOFS*)` and
`cnc_rdwkcdshft(handle, type, length, IODBWCSF*)` (both verbatim in
`Fwlib64.h`) verified live on the VT_23 against dbc00per's panel values:

* **WORK SHIFT** (`cnc_rdwkcdshft`, type=-1) = X 15.8365 / **Z 19.5044** —
  exact panel match ("T1 sets the workshift"); X equals the panel RELATIVE U.
  NB on this 0i-TF the shop's "G54 workshift" lives HERE, not in the G54 zero
  offset (which reads 0).
* **G55** (`cnc_rdzofs` datano=2) Z = **6.2660** — exact panel match. G56 Z =
  -0.9706 also present.
* **LENGTH TRAP**: both calls require the FULL `4 + 4*MAX_AXIS(32)` = 132-byte
  block — rc=2 (EW_LENGTH) on an axes-sized struct. (Inverse of the ODBM
  10-not-sizeof trap: here it's full-sizeof-not-trimmed.) `data[]` beyond the
  configured axes is uninitialized garbage — decode only axes 0..1.

Artifact: `reports/vt23-workshift-verified-20260729.json`. In the lathe poll
profile since v1.1 (mirror `shared.focas_work_offset`, audited, UI card).

**Active station (turret position) — VERIFIED 2026-07-29:** the FANUC-STANDARD
NC→PMC interface signals (F-area — NC-defined, portable across builders unlike
R/D ladder addresses): **F26–29 = T-code output** (panel T0808 → reads **8** =
station) and **F22–25 = S-code output** (panel S250 → reads **250** exact).
**SUPERSEDED same day by `cnc_rdcommand`** (header-verified; type=-1, block=0
returns all commanded addresses): with panel **T1224** active it returned
**T=1224 exact** (+ S=1300, M=30, O=21) — the FULL Tnnww word, i.e. station
AND active offset, in one documented NC read with ZERO PMC. The F26 signal is
truncated to the station by this ladder (T0808→8, T1224→12 — two-point
verified) and remains a documented fallback only. `read_commanded_t` →
`MachineStatus.current_t_number` carries the full word; the lathe UI splits
nn/ww (hub “S12 · OFS 24”, amber **NO OFFSET** when ww=00 — the T1200 hazard
case) and highlights the active offset register row. `cnc_modal` aux
selectors: dead end (churning counters).

## PANTHER group (3 × 0i-TF Plus lathes) — identity + capability, read 2026-08-05

Full details in `tasks/spec-panther-onboarding.md`; sweep artifacts
`reports/lathe{56,57,60}-capability-sweep-20260805.json`.

| Machine | IP | cnc_type/mt_type | series/version | axes |
|---|---|---|---|---|
| PANTHER JAKE_2100LY (CNC Lathe 6) | 10.1.10.56 | `0` / `T` | **D6G3** / 29.0 | 05 |
| PANTHER JAKE_2100LYS (CNC Lathe 7) | 10.1.10.57 | `0` / **`TT`** | D6G3 / 35.0 | 05 |
| PANTHER PROD_2100LYS-2 (CNC Lathe 8) | 10.1.10.60 | `0` / **`TT`** | D6G3 / 55.0 | 05 |

- `mt_type='TT'` = **two-path lathe** (sub-spindle). All reads so far are the
  DEFAULT PATH; path 2 needs `cnc_setpath` discovery (docs/11 L-O7) — nothing
  models it yet. Identity gates must accept `T` AND `TT` for lathes.
- `ofs_type=1`, `use_no=128`; `cnc_rdtofs` types 0–7 all answer (VT-pattern
  interleave EXPECTED, panel lock pending — sheets in
  `reports/panther-panel-crosscheck-*.md`).
- Tool-life group reads ANSWER (licensed; empty tables) — first controls in
  the fleet where the documented tool-life surface works.
- Program-under-execution surface verified live on .57: `cnc_exeprgname`/`2`,
  `cnc_rdprgnum`, `cnc_rdseqnum`, `cnc_rdexecprog` (block text),
  `cnc_pdf_rdmain` (path `//CNC_MEM/USER/PATH1/O9034`). All header-verified.
- **IP trap**: Lathe 8 was listed at .58 = the AG mill; real IP is .60.

## Unit / increment reads — `cnc_rdparam` + `cnc_rdset` BOUND 2026-08-05

`shared/focas/params.py` (read-only; header lines 12215/12260, IODBPSD shape,
length = 4 + size×axes documented-not-sizeof). Fleet-verified same day
(`reports/fleet-unit-verify-20260805.json`), all six machines:

- **Setting 0000#2 INI = 1** → inch INPUT unit (this is what offsets live in);
- **param 1013 = 0x00 every axis** → IS-B → **0.0001 inch/count** everywhere,
  == `DEFAULT_OFFSET_INCREMENT`;
- **param 1001#0 INM = 0 on ALL SIX** — metric MACHINE (command) system under
  inch input. **INM is NOT the offset unit; never key units off it.** The
  first verifier pass used INM and "found" metric on the operator-verified
  inch mills — the contradiction with known ground truth was the tell.

## Identity vs presence, and presetter attribution (design rules)

- **Pot cell = IDENTITY only.** Cells are sticky: a normally-unloaded pot retains
  its last tool number; a reset reinitialises every pot to its ordinal (pot N→N).
  So the PMC pot value never reliably means "occupied."
- **Offset = PRESENCE.** A tool is real only once the presetter measures it and
  writes its H-geom length; decommissioning zeroes it. Occupancy correlates the
  two via the app's assignment record (T#→h_register; **T≠H**) — occupancy model #3.
- **Presetter vs manual attribution.** The presetter's G31 touch latches #5061-63;
  an **H_GEOM** offset change coincident with a fresh skip = `presetter_verified`,
  no skip = `manual_edit` (R11). Scoped to H_GEOM because G31 is *also* the spindle
  probe's skip. Proven live 2026-07-08 (reg#19 4.6123→4.6130 with skip #5063
  3.2946→3.276 → auto-tagged `presetter_verified`).

---

# Sign-off

- [x] dbc00per: spec reviewed, approved for `client.py` implementation against the function names and struct shapes above. Open questions O1–O8 acceptable as integration-test deliverables.

`shared/focas/client.py` unblocked for Phase 1 read coverage as of this checkbox. `cnc_wrtofs` remains Phase-6-fenced.

---

## Phase 1 sign-off (2026-05-07)

**Smoke**: `reports/viper-smoke-o1-final.json` — clean against the live Mighty Viper LG-1000AP.
- Identity check passed (`cnc_type='0'`, `mt_type='M'`, `series='D4F1'`)
- Offset layout: `ofs_type=2` (Memory B), `use_no=400`
- Status: `current_t_number=17` matches panel HEAD; `next_t_number=85` matches panel NEXT
- Counts: 4 offsets sampled (first/last 5), 2 pots stub, 2 tool-life entries, 0 alarms
- `cnc_rdmagazine` returns `EW_NOOPT` (option absent on this control) — gracefully degraded

**Soak**: `reports/viper-soak-60min.json` — 23/23 cycles successful over 23.4 minutes.
- Success rate: 1.0
- Latency p50=34.1s, p95=35.2s, max=35.4s (dominated by 1200 offset reads — Memory B's 3 type codes × 400 registers)
- Zero errors, zero reconnects
- Operator stopped early when machine cycle finished — no further validation value from idle polling

**Open questions resolution at sign-off:**

| ID | Status | Resolution |
|---|---|---|
| O1 | RESOLVED | PMC R327 (HEAD) / R325 (NEXT) on Mighty Viper class. `cnc_modal` does not expose T on this control; magazine FOCAS calls absent from DLL. Bound via `pmc_rdpmcrng(type_a=5, type_d=0)` in `client.py`. |
| O2 | RESOLVED | `ofs_type=2` (Memory B) on the Viper. Type-code mapping is a non-standard permutation (panel-verified on register 396): type=1=D_GEOM, type=2=H_WEAR, type=3=H_GEOM, **type=0=D_WEAR** (found 2026-07-15; type=4 is simply an invalid code, not a missing option). All 4 banks read, 0 rejects. D_WEAR mapping operator-confirmed (07-15 brother, 07-28 dbc00per); client.py reads all 4 banks as of 2026-07-28. |
| O5 | RESOLVED (2026-07-08) | Magazine option absent (`cnc_rdmagazine` → `EW_NOOPT`), but pot tracking is **not** unavailable: the pot table lives in the PMC D-area (D105-128, BCD). `read_pots()` reads it live (confirmed vs panel). See "Verified Viper OEM PMC / macro bindings". |
| O6 | DEFERRED | Tool-life status bits (`IODBTD.tool_inf` layout). Low priority — Phase 2. |
| O7 | RESOLVED | `cnc_settimeout` units are seconds. Verified by responsive read latency (~10ms/call) at the configured 3-second timeout. |
| O8 | RESOLVED | Offset increment is **0.0001 mm/count** on this control (NOT the FANUC-standard 0.001). Verified via panel cross-check on H50 = 7.4050 mm (FOCAS `type=3` raw=74050) and register 396 four-bank panel readings. |

**Deferred to Phase 2:**

- **Async Poller `run()` exits cleanly after 2-3 cycles** under Python 3.13 with the dedicated single-worker executor — root cause not yet identified. Sync soak (`scripts/focas_soak_simple.py`) is the validated operational path; production poller (`shared/focas/poller.py`) is correct in design but has an untraced async lifecycle bug. See `tasks/lessons.md` for the full discovery story.
- ~~**D_WEAR FOCAS-unreadable**~~: **retracted 2026-07-15** — D_WEAR is `type=0` and reads cleanly on all 400 registers. No option purchase needed. UI shows real D_WEAR values; mapping operator-confirmed and `client.py` binds `type=0` as of 2026-07-28.
- **`cnc_rdparam` not yet bound**: needed to verify `OFFSET_INCREMENT` (parameter 1013) at runtime instead of hard-coding 0.0001. Currently the integration smoke is the cross-check.

Phase 1 is the FOCAS read foundation — sysinfo, status (with HEAD/NEXT), offset layout, offsets, pots (graceful when absent), tool-life, alarms — all working end-to-end against a real Mighty Viper LG-1000AP under sustained polling. Phase 2 builds persistence + diff-and-emit on top of this foundation; Phase 6 adds the write path with read-after-write verification.
