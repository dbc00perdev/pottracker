// Export downloads for a machine (spec-offset-export.md). Offsets come from
// the DB mirror; "Running program" performs one live read-only FOCAS upload
// FROM the control — the only item that can fail with "machine unreachable".
// G10 files carry a DO-NOT-RUN header until dbc00per panel-verifies the form
// per machine class.

import { useRef, useState } from "react";

import { ApiError, apiDownload, saveBlob } from "@/lib/api";

interface Item {
  label: string;
  path: string;
}

function items(machineId: string): Item[] {
  const base = `/machines/${machineId}/exports`;
  return [
    { label: "Offsets — G10 (sparse)", path: `${base}/offsets.g10?mode=sparse` },
    { label: "Offsets — G10 (full table)", path: `${base}/offsets.g10?mode=full` },
    { label: "Offsets — CSV (sparse)", path: `${base}/offsets.csv?mode=sparse` },
    { label: "Offsets — CSV (full table)", path: `${base}/offsets.csv?mode=full` },
    { label: "Running program (live read)", path: `${base}/program` },
  ];
}

export function ExportMenu({ machineId }: { machineId: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const detailsRef = useRef<HTMLDetailsElement>(null);

  const download = async (item: Item) => {
    setBusy(item.label);
    setError(null);
    try {
      const { blob, filename } = await apiDownload(item.path);
      saveBlob(blob, filename);
      detailsRef.current?.removeAttribute("open");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "download failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="relative">
      <details ref={detailsRef} className="group">
        <summary
          className="min-h-[44px] cursor-pointer select-none list-none rounded border
                     border-neutral-700 px-3 py-2 text-sm text-neutral-200
                     hover:border-neutral-500 [&::-webkit-details-marker]:hidden"
        >
          Export ▾
        </summary>
        <ul
          className="absolute right-0 z-10 mt-1 w-64 rounded border border-neutral-700
                     bg-neutral-900 py-1 shadow-lg"
        >
          {items(machineId).map((item) => (
            <li key={item.label}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void download(item)}
                className="block w-full px-3 py-2 text-left text-sm text-neutral-200
                           hover:bg-neutral-800 disabled:opacity-50"
              >
                {busy === item.label ? `${item.label}…` : item.label}
              </button>
            </li>
          ))}
        </ul>
      </details>
      {error && (
        <p role="alert" className="absolute right-0 mt-1 w-64 text-xs text-status-alarm">
          {error}
        </p>
      )}
    </div>
  );
}
