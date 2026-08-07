import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportMenu } from "@/features/machines/ExportMenu";
import { ApiError } from "@/lib/api";

const { apiDownload, saveBlob } = vi.hoisted(() => ({
  apiDownload: vi.fn(),
  saveBlob: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiDownload,
  saveBlob,
}));

describe("ExportMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("downloads the sparse G10 with the server filename", async () => {
    const blob = new Blob(["%\n"]);
    apiDownload.mockResolvedValueOnce({ blob, filename: "VT-offsets-sparse.nc" });
    render(<ExportMenu machineId="m-1" />);
    fireEvent.click(screen.getByText("Offsets — G10 (sparse)"));
    await waitFor(() =>
      expect(apiDownload).toHaveBeenCalledWith("/machines/m-1/exports/offsets.g10?mode=sparse"),
    );
    expect(saveBlob).toHaveBeenCalledWith(blob, "VT-offsets-sparse.nc");
  });

  it("surfaces a live-read failure without crashing", async () => {
    apiDownload.mockRejectedValueOnce(new ApiError(503, "FOCAS connect failed"));
    render(<ExportMenu machineId="m-1" />);
    fireEvent.click(screen.getByText("Running program (live read)"));
    expect(await screen.findByRole("alert")).toHaveTextContent("FOCAS connect failed");
    expect(saveBlob).not.toHaveBeenCalled();
  });
});
