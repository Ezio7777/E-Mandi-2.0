"use client";
import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeQueryClient } from "@/lib/query/query-client";
import { setUnauthorizedHandler } from "@/lib/api/client";
import { useEffect } from "react";
import { useAppDispatch } from "@/store/hooks";
import { sessionExpired } from "@/store/slices/auth.slice";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeQueryClient);
  const dispatch = useAppDispatch();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      dispatch(sessionExpired());
      client.clear();
      if (!window.location.pathname.startsWith("/login")) window.location.assign("/login?expired=1");
    });
    return () => setUnauthorizedHandler(null);
  }, [client, dispatch]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
