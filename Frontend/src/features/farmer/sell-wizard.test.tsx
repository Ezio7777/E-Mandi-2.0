import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { makeStore } from "@/store";
import { driveSet } from "@/store/slices/tour.slice";
import { act } from "@testing-library/react";

const m = vi.hoisted(() => ({
  ready: true,
  items: [{ id: "1" }] as { id: string }[],
  startMutate: vi.fn(),
  startReset: vi.fn(),
  createMutate: vi.fn(),
  addSample: vi.fn(),
  resetUpload: vi.fn(),
  suggestion: { data: { suggested: 32 } } as { data?: { suggested: number } },
}));

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("@/features/upload/image-dropzone", () => ({ ImageDropzone: () => <div>dropzone</div> }));
vi.mock("@/features/upload/use-image-upload", () => ({
  useImageUpload: () => ({ items: m.items, errors: [], ready: m.ready, keys: ["k1"], addSample: m.addSample, reset: m.resetUpload }),
}));
vi.mock("@/features/pricing/price-card", () => ({ PriceCard: () => <div>price-card</div> }));
vi.mock("@/services/grading", () => ({
  useStartGrading: () => ({ mutate: m.startMutate, reset: m.startReset, isError: false }),
  useGradingJob: () => ({
    isError: false,
    refetch: vi.fn(),
    data: {
      jobId: "j1", status: "ready",
      result: { jobId: "j1", grade: "A", confidence: 0.94, defectPercent: 2.5, explanation: "Minor bruising", issues: [], gradedAt: "2026-09-30T10:00:00Z", manualReviewRecommended: false },
    },
  }),
  usePriceSuggestion: () => m.suggestion,
}));
vi.mock("@/services/listings", () => ({
  useCreateListing: () => ({ mutate: m.createMutate, isPending: false, isError: false, isSuccess: false, reset: vi.fn() }),
}));

import { SellWizard } from "./sell-wizard";

const setup = (store = makeStore()) => ({ store, ...render(<Provider store={store}><SellWizard /></Provider>) });
const next = () => userEvent.click(screen.getByRole("button", { name: /^continue$/i }));

beforeEach(() => {
  m.ready = true;
  m.items = [{ id: "1" }];
  m.suggestion = { data: { suggested: 32 } };
  m.addSample.mockReset(); m.resetUpload.mockReset(); m.startReset.mockReset();
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


describe("SellWizard guided-tour driver", () => {
  const goalTo = (store: ReturnType<typeof makeStore>, goal: number, sample = false) =>
    act(() => { store.dispatch(driveSet({ wizardGoal: { goal, sample }, fill: null })); });

  it("adds a sample crop when the tour needs a photo and none exists", () => {
    m.items = [];
    const { store } = setup();
    goalTo(store, 0, true);
    expect(m.addSample).toHaveBeenCalledTimes(1);
    expect(m.addSample.mock.calls[0]![0]).toMatchObject({ id: "tomato" });
  });

  it("waits for the upload to finish before moving on", () => {
    m.ready = false;
    const { store } = setup();
    goalTo(store, 4);
    expect(m.startMutate).not.toHaveBeenCalled();
    expect(screen.getByText(/step 1 of 8/i)).toBeInTheDocument();
  });

  it("fills demo details, starts real grading and shows the grading step", async () => {
    const { store } = setup();
    goalTo(store, 4);
    expect(m.startMutate).toHaveBeenCalledWith({ imageKeys: ["k1"], cropName: "Tomato" }, expect.anything());
    expect(await screen.findByText(/step 5 of 8/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Grade A")).toBeInTheDocument();
  });

  it("advances to price and then to the review summary with the demo data", async () => {
    const { store } = setup();
    goalTo(store, 4);
    goalTo(store, 5);
    expect(await screen.findByText(/step 6 of 8/i)).toBeInTheDocument();
    expect(screen.getByText("price-card")).toBeInTheDocument();
    goalTo(store, 6);
    expect(await screen.findByText(/step 7 of 8/i)).toBeInTheDocument();
    expect(screen.getByText("Tomato")).toBeInTheDocument();
    expect(screen.getByText("800 kg")).toBeInTheDocument();
    expect(screen.getByText("Hosur, Tamil Nadu")).toBeInTheDocument();
  });

  it("starts grading only once even if the goal changes while it runs", () => {
    const { store } = setup();
    goalTo(store, 4);
    goalTo(store, 5);
    goalTo(store, 4);
    expect(m.startMutate).toHaveBeenCalledTimes(1);
  });

  it("resets to a clean slate when the tour ends", async () => {
    const { store } = setup();
    goalTo(store, 4);
    expect(await screen.findByText(/step 5 of 8/i)).toBeInTheDocument();
    act(() => { store.dispatch(driveSet({ wizardGoal: null, fill: null })); });
    expect(await screen.findByText(/step 1 of 8/i)).toBeInTheDocument();
    expect(m.resetUpload).toHaveBeenCalled();
    expect(m.startReset).toHaveBeenCalled();
  });

  it("never touches the wizard when no tour is driving it", () => {
    setup();
    expect(m.addSample).not.toHaveBeenCalled();
    expect(m.startMutate).not.toHaveBeenCalled();
    expect(m.resetUpload).not.toHaveBeenCalled();
  });
});


describe("SellWizard price field", () => {
  const toPriceStep = async () => {
    const store = makeStore();
    const view = render(<Provider store={store}><SellWizard /></Provider>);
    await next();
    await userEvent.type(screen.getByLabelText(/which crop/i), "Tomato");
    await next();
    await userEvent.type(screen.getByLabelText(/how many kilograms/i), "500");
    await next();
    await userEvent.type(screen.getByLabelText(/where is the crop/i), "Hosur");
    await next();
    await userEvent.click(await screen.findByRole("button", { name: /see price suggestion/i }));
    return { store, view };
  };

  it("fills the field with the suggestion when it arrives after the step is already showing", async () => {
    m.suggestion = { data: undefined };                 // still loading when the user gets here
    const { store, view } = await toPriceStep();
    expect(screen.getByLabelText(/your price per kg/i)).toHaveValue(null);
    m.suggestion = { data: { suggested: 32 } };         // now it lands
    view.rerender(<Provider store={store}><SellWizard /></Provider>);
    expect(await screen.findByDisplayValue("32")).toBeInTheDocument();
  });

  it("does not overwrite what the farmer already typed", async () => {
    m.suggestion = { data: undefined };
    const { store, view } = await toPriceStep();
    await userEvent.type(screen.getByLabelText(/your price per kg/i), "40");
    m.suggestion = { data: { suggested: 32 } };
    view.rerender(<Provider store={store}><SellWizard /></Provider>);
    expect(screen.getByLabelText(/your price per kg/i)).toHaveValue(40);
  });
});
