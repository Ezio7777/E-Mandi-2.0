"use client";
import { useEffect, useRef } from "react";
import { Provider } from "react-redux";
import { makeStore, rehydrateFromStorage, type AppStore, type RootState } from "@/store";

interface Instance { store: AppStore; initial: RootState }

export function ReduxProvider({ children }: { children: React.ReactNode }) {
  const ref = useRef<Instance | null>(null);
  if (!ref.current) {
    const store = makeStore();
    ref.current = { store, initial: store.getState() }; // captured before anything can dispatch
  }
  const { store, initial } = ref.current;
  useEffect(() => rehydrateFromStorage(store), [store]);
  // serverState makes every component read the pure initial state while it hydrates (including
  // Suspense boundaries that hydrate after rehydrateFromStorage ran), so saved prefs never cause a mismatch.
  return <Provider store={store} serverState={initial}>{children}</Provider>;
}
