# 08 — Glossary

Definitions of FANUC, machinist, and project-specific terms used in the documentation. Internal reference; serves as onboarding for any contributor not deep in CNC.

---

## FANUC / control terms

**ATC** — Automatic Tool Changer. The mechanism that swaps tools between the spindle and the carousel/magazine.

**Random-access ATC** — A tool changer where any pot can hold any tool, and the control tracks the mapping dynamically. The machine moves the carousel to the closest pot containing the requested T-number, regardless of where it was last stored. Contrast with sequential ATC, where pot N always holds tool N.

**Sequential ATC** — A tool changer where T# and pot # are fixed (T1 always in pot 1). Older / simpler design.

**Pot** — Physical slot in the tool magazine/carousel that holds a tool holder. The Viper has 23 + 1 (probe) = 24 pots.

**T-number (T#)** — Logical tool identifier referenced in G-code (e.g., `T25 M6` = "load tool number 25"). On random-access ATC, T# is independent of pot location.

**H-register / H-code** — Length offset register. `H125` in G-code (e.g., `G43 H125 Z...`) tells the control to apply length offset stored in register 125 to compensate for the tool's length.

**D-register / D-code** — Diameter / cutter compensation offset register. `D225` applies the diameter offset stored in register 225 for cutter compensation moves.

**Geometry offset** — The nominal offset value from tool measurement (length or diameter). Set during initial setup or after tool change.

**Wear offset** — A small adjustment added to geometry offset to compensate for tool wear. Operator typically adjusts wear, not geometry.

**Length geometry** — Z-axis offset between tool tip and a reference point (gauge line, spindle face).

**Length wear** — Small adjustment to length geometry to compensate for tool wear over time.

**Diameter geometry** — Tool radius/diameter offset for cutter compensation.

**Diameter wear** — Adjustment to diameter geometry for wear.

**Offset register** — A numbered slot in FANUC's offset memory. The Viper has 400 such slots, each holding the four values above.

**Tool offset table** — The collection of all offset registers. Editable on the control via the `OFFSET` screen.

**Tool life management** — Built-in FANUC feature tracking how long each tool has been used (count, time, or distance). Tools can be auto-skipped when exceeding life threshold, with backup tools defined in groups.

**MDI** — Manual Data Input. Operator types G-code directly into a single-shot buffer for execution.

**AUTO** — Automatic mode. Machine runs a stored program.

**EDIT** — Program editing mode.

**JOG** — Manual axis movement.

**REF** — Reference point return mode.

**Macro / Custom Macro** — User-written G-code subroutine using variables (e.g., `#100 = 5.0`). Used for probing, custom cycles, parametric programming.

**G10** — G-code command to write to data tables, including offset registers (e.g., `G10 L10 P125 R63.5042` writes 63.5042 to length geometry register 125).

**G43** — Length offset enable. Combined with H code: `G43 H125 Z2.0`.

**G73** — Peck drilling cycle with chip break (used for plastic boring per Sleeve Suite rules).

**M6** — Tool change command.

**M100** — Probing macro on Lance machines (custom; specific to tools and process).

**FOCAS** — Fanuc Open CNC API Specification. Ethernet-based protocol for reading/writing FANUC control state. Default port 8193. Library: `Fwlib32.dll` on Windows.

**FOCAS2** — Second-generation FOCAS spec, supporting more functions and 30i-series controls.

**DPRNT** — A custom-macro statement that outputs formatted text out of the control to a configured port (serial or Ethernet). Useful for sending probe results or status to external systems.

**DNC** — Direct Numerical Control. Mode where machine runs a program streamed from an external source (file server, PC).

**SYS-CONF** — System configuration file output by the FANUC control listing hardware, software modules, and edition numbers.

**0i-MF** — Series 0i Model F, mill variant. The control on both Lance Mighty Vipers. Part of the FS30i processing family from the FOCAS SDK perspective — meaning the 0i-MF is serviced by `fwlib30i64.dll` (the same processing DLL that handles 30i / 31i / 32i / 0i-F controls). Supports embedded Ethernet, FOCAS2, custom macros. Confirmed live on Viper LG-1000AP at 10.1.10.58:8193.

**FS30i-family processing DLL** — `fwlib30i64.dll` from the FwLib64 SDK. The "processing" DLL implements the per-control-family logic that decodes responses; the front-end `Fwlib64.dll` and transport `fwlibe64.dll` are family-agnostic. 0i-MF and 0i-F both fall under this DLL.

**30i-B** — Series 30i-B FANUC control. Mid-modern controller, FOCAS2, large memory. **Not the Lance control** — the Lance Vipers are 0i-MF, which shares the FS30i processing DLL with 30i-B but is a distinct series. Earlier docs referred to 30i-B in error; the working assumption now is 0i-MF.

**Embedded Ethernet** — Built-in Ethernet port on the FANUC control (vs. add-on cards). Required for FOCAS over LAN.

---

## Machinist terms

**EM** — Endmill. A rotary cutter typically used for milling slots, profiles, contours.

**Square endmill** — Endmill with a flat tip (90° corner).

**Ball endmill** — Endmill with a hemispherical tip.

**Bull-nose / corner-radius endmill** — Endmill with a small radius at the corner (e.g., .020" rad).

**4FL** — Four-flute. Four cutting edges. More flutes = better surface finish, less chip clearance.

**CRB** — Carbide. Tool substrate material — hard, brittle, holds an edge well.

**HSS** — High Speed Steel. Tougher than carbide but doesn't hold edge as long; cheaper.

**Cobalt** — Cobalt-alloyed HSS. Mid-tier between HSS and carbide.

**TiAlN, AlTiN** — Coatings (titanium aluminum nitride variants). Heat and wear resistance.

**TiN** — Titanium nitride coating. Older, gold colored.

**DLC** — Diamond-like carbon coating. Very hard, used for non-ferrous.

**Stickout** — How far the tool protrudes from the holder. More stickout = more deflection, less stability.

**Flute length** — Length of the cutting portion of the tool.

**OAL** — Overall length of the tool.

**Shank** — The non-cutting portion of the tool that goes into the holder.

**TSC** — Through-Spindle Coolant. Coolant delivered through the spindle and out the tool tip (vs. flood coolant from external nozzles). Required for some deep drills, beneficial for chip evacuation.

**DOC** — Depth of Cut. How deep into the part the tool engages per pass.

**WOC** — Width of Cut (or radial engagement). How much of the tool's diameter is engaged.

**Climb milling** — Cutting direction where the tool spindle rotation matches the feed direction at the cut. Lower forces, better finish, generally preferred.

**Conventional milling** — Opposite of climb. Older convention, used for backlash-prone setups or rough castings.

**Toolsetter** — On-machine probe used to measure tool length (and sometimes diameter). The Lance machines have toolsetters; the M100 macro invokes the measurement cycle.

**Offline presetter** — Standalone device (Zoller, Speroni, Parlec, Haimer) used to measure tools off the machine, freeing up spindle time. Lance does not currently have one; architecture supports adding one.

**Probe** — A spindle-mounted touch probe used to measure parts and fixtures. Fixed to a specific T-number / pot in the carousel and never reassigned.

**GD&T** — Geometric Dimensioning and Tolerancing. The specification language used on engineering drawings to define part geometry tolerances.

**Sagitta** — The height of an arc from its chord to the highest point. Used in radius/taper geometry math (relevant to Sleeve Suite v10).

---

## Project-specific terms

**Tool identity** — The persistent record of a physical tool in the library, regardless of which machine it's on or what registers it occupies.

**Assignment** — A relational record binding a tool to a machine, T-number, and offset registers.

**Pending review** — State of an assignment after detected offset change but before operator confirmation.

**Confirmed** — State of an assignment whose offset values have been verified by an operator after the most recent change.

**Pot observation** — A FOCAS-derived snapshot of which T-number is currently in which physical pot. Treated as observed state, not commanded state.

**Write request** — Operator-initiated intent to write a value to a FANUC offset register. Goes through validation, confirmation, execution, verification stages.

**Read-after-write verification** — After a FOCAS write, immediately re-read the same register to confirm the value took effect. Mandatory for every write.

**Mode lockout** — Refusing to write to FANUC while machine is in AUTO running mode. Safety mechanism.

**Drift abort** — Aborting a confirmed write because the register's current value no longer matches what the operator was shown when they confirmed. Indicates someone else (or a probe macro) changed the register in between.

**Capability flag** — A boolean on a tool or machine indicating presence/absence of a feature (e.g., `requires_tsc`, `has_tsc`). Used to validate assignments.

**Consumable class** — A tool record that represents a class of identical replaceable tools rather than a specific physical cutter. Multiple physical tools share offsets; UI suppresses the multi-assignment warning.

**Random-access ATC** — See FANUC terms above; central to the Viper's pot model.

**Probe pot** — Reserved pot containing the touch probe. Configured per-machine, never assignable to a regular tool.

---

## Stack terms (brief)

**FastAPI** — Python web framework, used for the API layer.

**SQLAlchemy** — Python ORM.

**Alembic** — Migration tool for SQLAlchemy.

**Pydantic** — Data validation library, used by FastAPI for request/response models.

**Vite** — Frontend build tool.

**Tailwind** — Utility-first CSS framework.

**JWT** — JSON Web Token, used for stateless auth.

**WebSocket** — Bidirectional persistent connection, optional v1.1 for live UI updates.

**`pyfocas`** — Community Python wrapper around Fanuc's FOCAS DLL.

**Lance CNC Tracker** — Existing app on the same host. Tracks job/operator/operation state from JobBoss2.
