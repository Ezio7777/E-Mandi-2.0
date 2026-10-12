import { combineReducers, configureStore, type Action, type UnknownAction } from "@reduxjs/toolkit";
import auth from "./slices/auth.slice";
import theme from "./slices/theme.slice";
import demo from "./slices/demo.slice";
import tour from "./slices/tour.slice";
import ui from "./slices/ui.slice";
import notifications from "./slices/notifications.slice";

const combined = combineReducers({ auth, theme, demo, tour, ui, notifications });
export type RootState = ReturnType<typeof combined>;
type Persisted = Partial<Pick<RootState, "theme" | "tour" | "demo">>;

const REHYDRATE = "app/rehydrate";
export const rehydrate = (payload: Persisted) => ({ type: REHYDRATE, payload });
const isRehydrate = (a: Action): a is ReturnType<typeof rehydrate> => a.type === REHYDRATE;

/** Root reducer that can merge saved client preferences in after hydration. */
const rootReducer = (state: RootState | undefined, action: UnknownAction): RootState =>
  isRehydrate(action) ? { ...combined(state, action), ...action.payload } : combined(state, action);

const PERSIST_KEY = "emandi-client-state";

function load(): Persisted | undefined {
  try {
    const raw = window.localStorage.getItem(PERSIST_KEY);
    if (!raw) return undefined;
    const saved = JSON.parse(raw) as Persisted;
    // A running tour is never restored: avoids a stale overlay after reload.
    if (saved.tour) saved.tour = { ...saved.tour, activeTour: null, stepIndex: 0, celebrate: false, wizardGoal: null, fill: null };
    return saved;
  } catch {
    return undefined;
  }
}

/**
 * The store is created with pure initial state so server and first client render match
 * (a saved Hindi locale must NOT be applied before hydration: that causes React error #418).
 */
export function makeStore() {
  return configureStore({ reducer: rootReducer });
}

export type AppStore = ReturnType<typeof makeStore>;
export type AppDispatch = AppStore["dispatch"];

/**
 * Call once on the client after hydration. Restores non-sensitive UI prefs (language, tour progress,
 * demo flag), then starts persisting. Nothing is written before this runs, so saved values can't be
 * overwritten by initial state. Never persists tokens or user identity.
 * Returns an unsubscribe function.
 */
export function rehydrateFromStorage(store: AppStore): () => void {
  const saved = load();
  if (saved) store.dispatch(rehydrate(saved));
  return store.subscribe(() => {
    const { theme, tour, demo } = store.getState();
    try {
      window.localStorage.setItem(PERSIST_KEY, JSON.stringify({ theme, tour: { ...tour, activeTour: null, stepIndex: 0, celebrate: false, wizardGoal: null, fill: null }, demo }));
    } catch {
      /* storage unavailable */
    }
  });
}
