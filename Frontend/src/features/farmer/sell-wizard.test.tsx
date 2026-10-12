import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { makeStore } from "@/store";

const m = vi.hoisted(() => ({
  ready: true,
  startMutate: vi.fn(),
  createMutate: vi.fn(),
}));

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("@/features/upload/image-dropzone", () => ({ ImageDropzone: () => <div>dropzone</div> }));
vi.mock("@/features/upload/use-image-upload", () => ({
  useImageUpload: () => ({ items: [{ id: "1" }], errors: [], ready: m.ready, keys: ["k1"] }),
}));
vi.mock("@/features/pricing/price-card", () => ({ PriceCard: () => <div>price-card</div> }));
vi.mock("@/services/grading", () => ({
  useStartGrading: () => ({ mutate: m.startMutate, isError: false }),
  useGradingJob: () => ({
    isError: false,
    refetch: vi.fn(),
    data: {
      jobId: "j1", status: "ready",
      result: { jobId: "j1", grade: "A", confidence: 0.94, defectPercent: 2.5, explanation: "Minor bruising", issues: [], gradedAt: "2026-09-30T10:00:00Z", manualReviewRecommended: false },
    },
  }),
  usePriceSuggestion: () => ({ data: { suggested: 32 } }),
}));
vi.mock("@/services/listings", () => ({
  useCreateListing: () => ({ mutate: m.createMutate, isPending: false, isError: false, isSuccess: false, reset: vi.fn() }),
}));

import { SellWizard } from "./sell-wizard";

const setup = () => render(<Provider store={makeStore()}><SellWizard /></Provider>);
const next = () => userEvent.click(screen.getByRole("button", { name: /^continue$/i }));

beforeEach(() => {
  m.ready = true;
  m.startMutate.mockReset().mockImplementation((_v, opts) => opts?.onSuccess?.({ jobId: "j1" }));
  m.createMutate.mockReset();
});

describe("SellWizard", () => {
  it("blocks the first step until every photo has uploaded", () => {
    m.ready = false;
    setup();
    expect(screen.getByRole("button", { name: /^continue$/i })).toBeDisabled();
  });

  it("validates the crop name before moving on", async () => {
    setup();
    await next();
    await userEvent.type(screen.getByLabelText(/which crop/i), "T");
    await next();
    expect(await screen.findByText(/enter the crop name/i)).toBeInTheDocument();
  });

  it("walks the guided flow, grades, and publishes the collected data", async () => {
    setup();
    await next();                                                     // photos → crop
    await userEvent.type(screen.getByLabelText(/which crop/i), "Tomato");
    await next();                                                     // crop → quantity
    await userEvent.type(screen.getByLabelText(/how many kilograms/i), "500");
    await next();                                                     // quantity → location
    await userEvent.type(screen.getByLabelText(/where is the crop/i), "Hosur");
    await next();                                                     // location → grading

    expect(m.startMutate).toHaveBeenCalledWith({ imageKeys: ["k1"], cropName: "Tomato" }, expect.anything());
    expect(await screen.findByLabelText("Grade A")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /see price suggestion/i }));
    expect(screen.getByText("price-card")).toBeInTheDocument();
    await next();                                                     // price (defaults to AI suggestion ₹32)

    expect(screen.getByText("Tomato")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /looks good/i }));
    await userEvent.click(screen.getByRole("button", { name: /publish listing/i }));

    expect(m.createMutate).toHaveBeenCalledWith(
      { crop: "Tomato", quantityKg: 500, location: "Hosur", pricePerKg: 32, imageKeys: ["k1"], gradingJobId: "j1" },
      expect.anything(),
    );
  });
});
