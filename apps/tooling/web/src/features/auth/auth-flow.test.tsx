import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ProtectedRoute } from "@/components/ProtectedRoute";
import { LoginPage } from "@/features/auth/LoginPage";
import { AuthProvider } from "@/lib/auth";

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: "/login", element: <LoginPage /> },
      {
        path: "/",
        element: (
          <ProtectedRoute>
            <div>secret dashboard</div>
          </ProtectedRoute>
        ),
      },
    ],
    { initialEntries: [path] },
  );
  return render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  );
}

describe("protected routing", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it("redirects an unauthenticated visitor from / to the login page", async () => {
    renderAt("/");
    // No token → bootstrap resolves logged-out → ProtectedRoute redirects.
    expect(await screen.findByRole("heading", { name: "Lance Tooling" })).toBeInTheDocument();
    expect(screen.queryByText("secret dashboard")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });
});
