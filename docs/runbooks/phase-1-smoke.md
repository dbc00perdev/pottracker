# Runbook — Phase 1 FOCAS smoke test

Step-by-step guide for running `scripts/focas_smoke.py` against the Mighty Viper LG-1000AP from the Lance dev box. The output JSON is the artifact attached to the Phase 1 gate sign-off and the input that resolves open questions O1, O2, O5, O7 in `tasks/spec-focas-calls.md`.

**Audience**: dbc00per running this at the floor.
**Environment**: Windows 10/11 with `C:\Fanuc\FwLib64-runtime\` populated.
**Time**: ~5 minutes for the smoke, longer for the soak.
**What this does NOT do**: any FOCAS write. Read-only Phase 1 verification.

---

## 0. Before you walk to the floor

These can be done at your desk — they don't need machine access.

### 0.1 Confirm the SDK is installed

```powershell
Test-Path C:\Fanuc\FwLib64-runtime\Fwlib64.dll
Test-Path C:\Fanuc\FwLib64-runtime\fwlibe64.dll
Test-Path C:\Fanuc\FwLib64-runtime\fwlib30i64.dll
Test-Path C:\Fanuc\FwLib64-runtime\Fwlib64.h
```

All four should print `True`. If any are `False`, stop here — re-extract / re-install the SDK before going further.

### 0.2 Pull latest, activate venv, sanity-check

In Git Bash:

```bash
cd /c/Users/dbc00/dev/pottracker
git checkout claude/summarize-build-eWINf
git pull --rebase
source .venv/Scripts/activate     # or `.venv\Scripts\activate` in PowerShell
pip install -e '.[api,dev]' --quiet
pytest -q                          # expect: 198 passed
ruff check .                       # expect: All checks passed
```

If pytest fails, stop. The smoke test depends on the modules under test working correctly.

### 0.3 Verify the script's plumbing without a machine

```bash
python scripts/focas_smoke.py --mock --output /tmp/mock-smoke.json --latency-samples 2
cat /tmp/mock-smoke.json | python -m json.tool | head -40
```

Expected: exit 0, JSON with `"identity_check": {"passed": true, ...}`. This proves the script's report-building works before you stake anything on the real run.

---

## 1. At the floor — pre-flight checks

### 1.1 Confirm Viper is powered on and not in cycle

Look at the operator panel. Mode should be `MEM` (not `AUTO running` — we're polling but want a clean idle baseline). E-stop released. No active alarms.

### 1.2 TCP reachability test

From Windows, in PowerShell:

```powershell
Test-NetConnection -ComputerName 10.1.10.58 -Port 8193
```

`TcpTestSucceeded : True` means FOCAS is reachable. If `False`, check:

| Symptom | Likely cause | Fix |
|---|---|---|
| `PingSucceeded: False` | Network down or wrong VLAN | Cable / switch / VLAN config |
| `PingSucceeded: True, TcpTestSucceeded: False` | Embedded Ethernet not loaded | Power-cycle Viper, check SYS-CONF |
| Long timeout | Firewall on dev box | Allow outbound 8193 to 10.1.10.58 |

Do not proceed past this point if TCP is closed.

### 1.3 Set the DLL path for this shell

```powershell
$env:FOCAS_DLL_DIR = "C:\Fanuc\FwLib64-runtime"
```

Or in Git Bash:

```bash
export FOCAS_DLL_DIR="C:/Fanuc/FwLib64-runtime"
```

(Windows accepts forward slashes here. Either works.)

---

## 2. Run the smoke

### 2.1 The command

```bash
mkdir -p reports
python scripts/focas_smoke.py \
    --ip 10.1.10.58 \
    --port 8193 \
    --machine-id viper-lg-1000ap \
    --output reports/viper-smoke-$(date +%Y%m%d-%H%M%S).json \
    --latency-samples 10 \
    --log-level INFO
```

PowerShell variant:

```powershell
mkdir reports -ErrorAction SilentlyContinue
$ts = Get-Date -Format yyyyMMdd-HHmmss
python scripts/focas_smoke.py `
    --ip 10.1.10.58 `
    --port 8193 `
    --machine-id viper-lg-1000ap `
    --output reports\viper-smoke-$ts.json `
    --latency-samples 10 `
    --log-level INFO
```

### 2.2 What you should see on stderr

```
2026-... INFO focas_smoke connecting to 10.1.10.58:8193 (timeout=3s)
2026-... INFO focas_smoke smoke report written to reports/viper-smoke-...json
```

Total wall time: ~5–60 seconds depending on offset register count and machine responsiveness. The bulk is the offsets read (1600 calls per cycle until `cnc_rdtofsr` ships in Phase 2).

### 2.3 Exit code

| Code | Meaning | Action |
|---|---|---|
| 0 | identity check passed, report written | proceed to step 3 |
| 2 | identity check failed (R9 trip) — connected to wrong control | **stop**, check IP and report findings |
| Anything else (1, 3, …) | uncaught exception | open the report, find the traceback in stderr, file as a Phase-1 bug |

---

## 3. Inspect the report

### 3.1 Quick health check

```bash
python -c "import json; r = json.load(open('reports/viper-smoke-XXXX.json')); print('identity:', r['identity_check']); print('ofs_type:', r['offset_layout']); print('current_t:', r['snapshot']['status']['current_t_number']); print('alarms:', r['snapshot']['alarms']['count'])"
```

Replace `XXXX` with the actual timestamp.

### 3.2 What each field tells you

| JSON path | Resolves | Look for |
|---|---|---|
| `sysinfo` | R9 — control identity | `cnc_type=="0i"`, `mt_type=="M"`, `series=="D4F1"` |
| `offset_layout.ofs_type` | **O2** | concrete int (1, 5, 10, …) — write back to spec doc |
| `offset_layout.use_no` | informational | how many offset entries the control has populated |
| `snapshot.status.current_t_number` | **O1** | non-null number → `cnc_modal(-3, 1)` works; null → re-check FOCAS2 manual constants |
| `snapshot.status.mode` | sanity | `MEM` if the Viper is idle as expected |
| `snapshot.status.emergency_stop` | sanity | should be `false` |
| `snapshot.offsets.count_total` | sanity | should be ~`use_no × 4` |
| `snapshot.offsets.first_5` | sanity | values in plausible mm range (length geom typically negative ~-100 mm) |
| `snapshot.pots.entries[].t_number` | **O5** | scan for empty pots (`null`) and any non-zero raw indices |
| `snapshot.alarms.count` | sanity | should be 0 in idle state |
| `latency_per_call_ms.read_status.p95_ms` | latency doc | record per FOCAS function; alert threshold for production poller is p95 < 500ms |
| `open_questions` | summary | each O# carries a verdict + next-action hint; transcribe to spec doc |

### 3.3 Sanity checks

Before signing off:

- [ ] `identity_check.passed == true`
- [ ] `snapshot.offsets.count_total > 0` (control has offsets configured)
- [ ] At least one pot in `snapshot.pots.entries` has `t_number == 50` (probe locked at T50 per Decision-4)
- [ ] No pot has `t_number == 50` AND a different pot also has `t_number == 50` (probe should appear once)
- [ ] `latency_per_call_ms.read_status.max_ms < 1000` (otherwise something is wrong with the network or the control)

If any of these fail, the report still gets pushed — but flag it in the PR comment so the Phase 1 gate review knows.

---

## 4. Push the report

The report file goes into the PR as the Phase 1 verification artifact.

```bash
git add reports/viper-smoke-*.json
git commit -m "Phase 1 smoke: $(basename reports/viper-smoke-*.json .json)"
git push
```

Once the report is in the PR, comment with the key findings — copy these from `open_questions`:

> Smoke report attached. Findings:
> - O1 current T: <value>
> - O2 ofs_type: <value>, use_no: <value>
> - O5 empty-pot sentinel observed: <value> (client.py treats <=0 as empty — match? yes/no)
> - O7 settimeout: connection succeeded with 3s timeout, units assumed seconds
> - Latency p95: status=<n>ms, pots=<n>ms, alarms=<n>ms, offsets=<n>ms

---

## 5. The 60-minute soak

Same script in a loop, every 60 seconds. Quick PowerShell:

```powershell
$end = (Get-Date).AddMinutes(60)
while ((Get-Date) -lt $end) {
    $ts = Get-Date -Format yyyyMMdd-HHmmss
    python scripts/focas_smoke.py `
        --ip 10.1.10.58 `
        --machine-id viper-lg-1000ap `
        --output reports/soak/viper-soak-$ts.json `
        --latency-samples 5 `
        --log-level WARNING
    Start-Sleep -Seconds 60
}
```

Watch for:
- Memory growth in the python process (Task Manager → Details → python.exe)
- Increasing latency p95 over the hour (lock contention or DLL leak)
- Identity check flipping to `passed: false` mid-run (control rebooted? handle stale handling kicks in?)

After the hour:

```bash
ls reports/soak/ | wc -l                    # expect: 60 reports (one per minute)
cat reports/soak/*.json | jq -s '[.[] | .latency_per_call_ms.read_status.p95_ms] | {min: min, max: max, mean: (add/length)}'
```

If `jq` isn't installed, skip the post-run analysis; the file count alone is the leak/stuck-process signal.

---

## 6. Sign off

After the smoke + soak look good:

1. In `tasks/spec-focas-calls.md`, replace each O1/O2/O5/O7 placeholder with the verified value
2. In `tasks/todo.md`, check off the smoke + soak + latency-doc rows under Phase 1
3. Comment "Phase 1 ready to merge" on PR #1
4. I'll squash-merge and delete the branch

---

## Failure modes and what to do

| Symptom | Likely cause | Action |
|---|---|---|
| `FocasNoDllError: FOCAS DLLs are Windows-only` | Running in WSL or Git Bash on Linux subsystem | Run from native Windows shell |
| `FocasNoDllError: Fwlib64.dll not found` | `FOCAS_DLL_DIR` unset or path wrong | re-set env var per §1.3 |
| `FocasConnectError: connect to 10.1.10.58:8193 failed` | TCP closed | re-run §1.2 pre-flight |
| `FocasError: control identifies as cnc_type='30' ...` | Wrong machine on that IP, or 30i not 0i | check IP, check sysinfo on the actual control panel |
| Identity ok but `current_t_number == null` | **O1 unresolved** — `cnc_modal(-3, 1)` not the right constants for this control | DO NOT block on this; record the value, file a follow-up to test other (datano, type) pairs against FOCAS2 manual |
| `read_offsets` takes 30+ seconds | Expected — Phase 2 switches to `cnc_rdtofsr` for ~10x speedup | Don't bother optimizing in Phase 1; just record the latency |
| Crash with traceback ending in ctypes | Layout drift between `Fwlib64.h` and `shared/focas/ctypes_defs.py` | Re-run extractor (`scripts/extract_focas_signatures.py`), diff against current spec, fix struct definitions |

When in doubt, attach the report + the stderr to PR #1 and ping me.
