import { Link, useParams } from "react-router-dom";

// Placeholder — full detail (spec card, assignments, tool-scoped audit) lands
// in the next step. Confirms the route + param wiring for now.
export function ToolDetailPage() {
  const { id } = useParams();
  return (
    <div className="space-y-3">
      <Link to="/tools" className="text-sm text-neutral-400 hover:underline">
        ← Tools
      </Link>
      <h1 className="text-xl font-semibold">Tool detail</h1>
      <p className="font-mono text-neutral-400">{id}</p>
      <p className="text-neutral-500">Detail view coming in the next step.</p>
    </div>
  );
}
