/** Per-machine accent colors so machines are visually unmistakable in the UI
 * (dbc00per 2026-07-29: "visually they need to differ more" — outline each
 * machine in its own color).
 *
 * The two current machines get EXPLICIT, stable colors (operators learn
 * "AG = blue, LG = amber"); future machines fall back to a deterministic
 * hash of the machine id over the palette. Tailwind needs literal class
 * strings, hence the fixed palette objects.
 */

export interface MachineAccent {
  /** border color for card/page outlines */
  border: string;
  /** accent text color (machine name) */
  text: string;
}

const PALETTE: MachineAccent[] = [
  { border: "border-sky-500", text: "text-sky-400" },
  { border: "border-amber-500", text: "text-amber-400" },
  { border: "border-emerald-500", text: "text-emerald-400" },
  { border: "border-fuchsia-500", text: "text-fuchsia-400" },
  { border: "border-rose-500", text: "text-rose-400" },
  { border: "border-teal-500", text: "text-teal-400" },
  { border: "border-violet-500", text: "text-violet-400" },
  { border: "border-cyan-500", text: "text-cyan-400" },
  { border: "border-lime-500", text: "text-lime-400" },
  { border: "border-orange-500", text: "text-orange-400" },
];

/** Stable machine-name → palette index for the known fleet. */
const EXPLICIT: Record<string, number> = {
  "VIPER AG_1000": 0, // sky
  "VIPER LG_1000": 1, // amber
  "VIPER VT-23B": 2, // emerald — CNC Lathe 3 (renamed from VT_23, 2026-08-06)
  "PANTHER JAKE_2100LY": 3, // fuchsia — CNC Lathe 6
  "PANTHER JAKE_2100LYS": 4, // rose — CNC Lathe 7
  "PANTHER PROD_2100LYS-2": 5, // teal — CNC Lathe 8
  "VIPER VT-21": 6, // violet — CNC Lathe 1
  "VIPER VT-23A": 7, // cyan — CNC Lathe 2
  "VIPER VT-25BL": 8, // lime — CNC Lathe 4
  "VIPER VT-15L": 9, // orange — CNC Lathe 5
};

function hashIndex(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % PALETTE.length;
}

export function machineAccent(m: { id: string; name: string }): MachineAccent {
  const explicit = EXPLICIT[m.name];
  return PALETTE[explicit ?? hashIndex(m.id)];
}
