# tasks/lessons.md

Captured corrections and rules. Reviewed at session start.

Format: `**Mistake**: ... → **Rule**: ...`

---

**Mistake**: First pass at the FOCAS target function list (Decision-2 brief) included names like `cnc_rdmode`, `cnc_rdtcode`, `cnc_rdsysinfo`, `cnc_rdtoolgrp_id` that look correct but are Series 16/18/21-era names. The FS30i processing DLL (`fwlib30i64.dll`) that serves 0i-MF does not expose them. The extractor flagged them all as NOT FOUND on first run against the real `Fwlib64.h`. → **Rule**: Never add a FOCAS function name to the target list, the spec doc, or the client without first grepping `Fwlib64.h` to confirm it exists. The function-name set differs between FS-16/18/21 and FS30i families, and our docs/training data leak the older names. R9 (FOCAS function name mismatch with reality) is exactly this risk — treat it as a structural hazard, not a one-time mistake.

**Mistake**: Decision-2 brief asked Claude to populate `tasks/spec-focas-calls.md` "verbatim from `C:\Fanuc\FwLib64-runtime\Fwlib64.h`" while the agent was in a Linux container with no Windows mount. → **Rule**: Header / SDK / DLL access lives on the Windows dev box. The agent's job is to write tooling (the extractor) that the operator runs on Windows; the agent does not invent verbatim text it cannot read. Anything claiming to be verbatim from a file the agent didn't read is fabrication.
