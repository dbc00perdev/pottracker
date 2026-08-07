# spec-machine-archive — app-owned archive for machine-read data

Status: DESIGN (discussion with dbc00per 2026-08-06). Not built. Builds on
spec-offset-export (shipped: G10/CSV/program export via browser download).

## Purpose

One app-owned, append-only root where every machine-read export lands
automatically, organized for humans AND machine-readable for dbc00per's SaaS
builds. Converges with docs/14 (GCG manifests / run archive / setup records).

## Decided

- **Final home = the NAS.** Root is ONE config value, stored as a **UNC
  path** (`\\<nas>\...`), never a mapped drive letter (drive letters are
  per-login and vanish under Task Scheduler / the fleet PC). Interim dev
  location may differ; structure is location-independent.
  (`C:\Users\dbc00\Desktop\Lance_Shop_Files` was a temporary scaffold only.)
- **App-owned root is separate from the human-curated tree** (dbc00per's
  department filing, 01_Engineering…11_IT_Systems). The robot writes ONLY
  under its own root; humans never hand-edit it. No mixing.
- **Two scopes, two branches** — programs are PART-scoped (key = the O-line
  comment, e.g. `O0080(4797)`, parsed by the existing strict
  `parse_program_comment` — never guessed); offset tables / MACRO.TXT /
  EXT_WK2 are MACHINE-scoped:

```
<root>/
  manifest.jsonl               # one JSON line per file written (see below)
  parts/
    4797/
      programs/O0080_VT-23B_rev01_20260806-1712.nc
      setup/                   # future: WCS/work-shift captured during runs,
                               # GCG manifests, sleeve_suite setup records
    _unfiled/VT-21/O0023_20260806.nc   # program w/o comment: filed honestly
  machines/
    VIPER_VT-23B/
      offsets/   offsets_sparse_<ts>.g10.nc + .csv
      macro/     MACRO_<ts>.txt        # cnc_rdmacro sweep (format: match a
      workoffsets/ EXT_WK2_<ts>.txt    #   real panel punch sample first)
```

- **Append-only + revisioned**: never overwrite/delete. New program capture
  is content-hashed against the newest existing revision; identical → skip,
  different → `rev(NN+1)`. The archive doubles as program history (diffable).
- **manifest.jsonl** (the SaaS contract): the archiver appends one line per
  file: `{part, machine, o_number, type, path, sha256, captured_at}` —
  consumers never walk directories or parse filenames.
- **Tracker integration = dual-write copy**: program files ALSO copied to
  `Y:\jobtracker\attachments\<part>\programs\` (additive-only — create
  folders/files, never touch existing) so they appear with the job in the
  tracker. Archive stays canonical. NB tracker coupling rule: before relying
  on tracker UI visibility, check (read-only) whether the tracker indexes
  attachments in its DB or lists the folder.

## Safety classification

All machine contact is READ (program upload, macro reads, offset/work-offset
reads — all bound or probe-verified). New writes = files on the NAS/tracker
share only. No FOCAS write surface.

## Open decisions (dbc00per)

- [ ] NAS hostname/share + where the root sits on it
- [ ] Part-folder key = raw comment text (`4797`, `3878OR_Blank`) — confirm
- [ ] Tracker dual-write on from day one? And target subfolder name
      (`programs\` proposed) inside `attachments\<part>\`
- [ ] Extra manifest fields the SaaS builds want (cheap to add now)
- [ ] Trigger: manual (Export menu "save to archive") vs auto-archive on
      program change (poller sees program_number flip → capture) — proposal:
      both, auto on
- [ ] MACRO.TXT / EXT_WK2.TXT: need one real panel-punched sample of each to
      match the format byte-exactly (round-trip rule) before those exporters
      are built
