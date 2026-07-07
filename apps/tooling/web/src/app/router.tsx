import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuditPage } from "@/features/audit/AuditPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { MachinesListPage } from "@/features/machines/MachinesListPage";
import { ToolDetailPage } from "@/features/tools/ToolDetailPage";
import { ToolsListPage } from "@/features/tools/ToolsListPage";

// React Router v7, library mode. The protected shell owns the authenticated
// routes; feature pages render into its <Outlet/>.
export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "tools", element: <ToolsListPage /> },
      { path: "tools/:id", element: <ToolDetailPage /> },
      { path: "machines", element: <MachinesListPage /> },
      { path: "audit", element: <AuditPage /> },
    ],
  },
]);
