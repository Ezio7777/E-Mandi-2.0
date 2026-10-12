"use client";
import { useEffect, useRef, useState } from "react";
import { env } from "@/config/env";
import { useGoogleLogin } from "@/services/auth";

interface GoogleId {
  initialize: (o: { client_id: string; callback: (r: { credential: string }) => void }) => void;
  renderButton: (el: HTMLElement, o: Record<string, string | number>) => void;
}
declare global {
  interface Window { google?: { accounts: { id: GoogleId } } }
}

const SRC = "https://accounts.google.com/gsi/client";

/** Official Google Identity button. The credential (ID token) is verified by the backend. */
export function GoogleButton() {
  const ref = useRef<HTMLDivElement>(null);
  const login = useGoogleLogin();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!env.googleClientId) return;
    const init = () => {
      if (!window.google || !ref.current || !env.googleClientId) return;
      window.google.accounts.id.initialize({ client_id: env.googleClientId, callback: (r) => login.mutate(r.credential) });
      window.google.accounts.id.renderButton(ref.current, {
        type: "standard", theme: "outline", size: "large", text: "continue_with", shape: "rectangular", width: Math.min(ref.current.offsetWidth, 400),
      });
      setReady(true);
    };
    if (window.google) { init(); return; }
    const s = document.createElement("script");
    s.src = SRC; s.async = true; s.defer = true; s.onload = init;
    document.head.appendChild(s);
    return () => { s.onload = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!env.isGoogleEnabled) return null;
  return (
    <div>
      <div ref={ref} className="flex min-h-[44px] w-full justify-center" aria-busy={!ready} />
      {login.isError && <p role="alert" className="mt-2 text-sm text-danger">{login.error.message}</p>}
    </div>
  );
}
