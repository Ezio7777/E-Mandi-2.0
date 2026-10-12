import { beforeEach, describe, expect, it } from "vitest";
import { makeStore, rehydrateFromStorage } from "./index";
import { localeChanged } from "./slices/theme.slice";

const KEY = "emandi-client-state";
const saved = {
  theme: { preference: "dark", locale: "kn" },
  tour: { activeTour: "farmer", stepIndex: 3, completed: ["buyer"], dismissed: false },
  demo: { active: true, role: "farmer" },
};

beforeEach(() => window.localStorage.clear());

describe("store hydration safety", () => {
  it("starts with pure initial state even when a saved locale exists (prevents SSR hydration mismatch)", () => {
    window.localStorage.setItem(KEY, JSON.stringify(saved));
    expect(makeStore().getState().theme.locale).toBe("en");
  });

  it("restores saved preferences after hydration but never a running tour", () => {
    window.localStorage.setItem(KEY, JSON.stringify(saved));
    const store = makeStore();
    rehydrateFromStorage(store);
    const s = store.getState();
    expect(s.theme.locale).toBe("kn");
    expect(s.demo.active).toBe(true);
    expect(s.tour.completed).toEqual(["buyer"]);
    expect(s.tour.activeTour).toBeNull();
    expect(s.tour.stepIndex).toBe(0);
  });

  it("does not overwrite saved data with initial state before rehydrating", () => {
    window.localStorage.setItem(KEY, JSON.stringify(saved));
    const store = makeStore();
    store.dispatch(localeChanged("en")); // a change before rehydrate must not be persisted
    expect(JSON.parse(window.localStorage.getItem(KEY)!).theme.locale).toBe("kn");
  });

  it("persists later changes, and never persists auth identity", () => {
    const store = makeStore();
    rehydrateFromStorage(store);
    store.dispatch(localeChanged("hi"));
    const written = JSON.parse(window.localStorage.getItem(KEY)!);
    expect(written.theme.locale).toBe("hi");
    expect(written.auth).toBeUndefined();
  });
});

import { tourCompleted, tourStarted } from "./slices/tour.slice";
describe("tour completion toast", () => {
  it("is raised only by finishing a tour, never by rehydrated state", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ tour: { activeTour: null, stepIndex: 0, completed: ["farmer"], dismissed: false, celebrate: true } }));
    const store = makeStore();
    rehydrateFromStorage(store);
    expect(store.getState().tour.celebrate).toBe(false);
    store.dispatch(tourStarted("buyer"));
    store.dispatch(tourCompleted());
    expect(store.getState().tour.celebrate).toBe(true);
  });
});
