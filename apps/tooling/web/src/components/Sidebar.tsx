import { ClipboardList, Gauge, Settings, Wrench } from "lucide-react";
import type { ComponentType } from "react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/lib/auth";
import { ROLE_RANK } from "@/types/api";
import type { Role } from "@/types/api";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  minRole?: Role;
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/machines", label: "Machines", icon: Gauge },
  { to: "/audit", label: "Audit", icon: ClipboardList, minRole: "admin" },
  { to: "/settings", label: "Settings", icon: Settings, minRole: "admin" },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth();
  const rank = user ? ROLE_RANK[user.role] : -1;
  const items = NAV.filter((i) => !i.minRole || rank >= ROLE_RANK[i.minRole]);

  return (
    <nav className="flex h-full flex-col gap-1 p-3" aria-label="Primary">
      <div className="px-2 py-3 text-lg font-semibold text-neutral-100">Lance Tooling</div>
      {items.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex min-h-[44px] items-center gap-3 rounded-md px-3 text-sm text-neutral-300 hover:bg-neutral-800",
              isActive && "bg-neutral-800 text-neutral-100",
            )
          }
        >
          <Icon className="h-5 w-5 shrink-0" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
