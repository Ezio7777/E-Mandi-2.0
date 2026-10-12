"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, animate, motion, useMotionValue, useReducedMotion } from "framer-motion";
import { ArrowRight, PartyPopper, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import { ROLE_PREFIX } from "@/config/routes";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { driveSet, stepChanged, tourAck, tourCompleted, tourReset, tourSkipped } from "@/store/slices/tour.slice";
import type { Role } from "@/types";
import { placeCard, type Box } from "./tour-layout";
import { tourSteps } from "./tour-steps";

const PAD = 8;
const EASE = [0.22, 1, 0.36, 1] as const;

const frame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const toBox = (r: DOMRect): Box => ({ top: r.top, left: r.left, width: r.width, height: r.height });

/** Two copies can exist (sidebar + bottom nav): pick the one that is actually on screen. */
function findVisible(name?: string): HTMLElement | null {
  if (!name) return null;
  return Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)).find((e) => e.offsetParent !== null) ?? null;
}

async function until(test: () => boolean, timeout: number, stop: () => boolean) {
  const t0 = performance.now();
  while (!stop() && performance.now() - t0 < timeout) {
    if (test()) return true;
    await sleep(40);
  }
  return !stop() && test();
}

/** Scrolls only when needed, and tall targets to their top, so the card is never asked to cover them. */
function ensureVisible(el: HTMLElement, instant: boolean) {
  const r = el.getBoundingClientRect();
  const vh = window.innerHeight;
  const tall = r.height > vh * 0.7;
  const fine = tall ? r.top >= 0 && r.top < vh * 0.35 : r.top >= 64 && r.bottom <= vh - 64;
  if (!fine) el.scrollIntoView({ block: tall ? "start" : "center", behavior: instant ? "auto" : "smooth" });
}

/** Resolves once the element has stopped moving (smooth scroll finished, layout settled). */
async function settle(el: HTMLElement, stop: () => boolean) {
  let prev = "";
  let same = 0;
  const t0 = performance.now();
  while (!stop() && performance.now() - t0 < 1100) {
    const r = el.getBoundingClientRect();
    const key = `${Math.round(r.top)}|${Math.round(r.left)}|${Math.round(r.width)}|${Math.round(r.height)}`;
    same = key === prev ? same + 1 : 0;
    prev = key;
    if (same >= 4) return;
    await frame();
  }
}

function TourOverlay() {
  const dispatch = useAppDispatch();
  const router = useRouter();
  const reduce = useReducedMotion() ?? false;
  const { activeTour, stepIndex } = useAppSelector((s) => s.tour);
  const role = useAppSelector((s) => s.auth.role);
  const authStatus = useAppSelector((s) => s.auth.status);

  const [mounted, setMounted] = useState(false);
  const [layerOn, setLayerOn] = useState(false);
  const [cardOn, setCardOn] = useState(false);
  const [hasTarget, setHasTarget] = useState(true);
  const [shown, setShown] = useState<{ tour: Role; index: number } | null>(null);

  const cardRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLElement | null>(null);
  const settledRef = useRef(false);
  const cardVisible = useRef(false);
  const layerShown = useRef(false);
  const lastRect = useRef<Box | null>(null);

  const top = useMotionValue(0);
  const left = useMotionValue(0);
  const width = useMotionValue(0);
  const height = useMotionValue(0);
  const ring = useMotionValue(0);
  const cardX = useMotionValue(0);
  const cardY = useMotionValue(0);

  const steps = activeTour ? tourSteps(activeTour) : [];
  const step = steps[stepIndex];
  const last = stepIndex === steps.length - 1;

  const place = useCallback((rect: Box | null) => {
    const card = cardRef.current;
    if (!card) return;
    const w = window.innerWidth;
    const p = placeCard(rect, { w: card.offsetWidth, h: card.offsetHeight }, { w, h: window.innerHeight }, { bottomInset: w < 768 ? 76 : 16 });
    cardX.set(p.x);
    cardY.set(p.y);
  }, [cardX, cardY]);

  /** Springs the spotlight hole to `rect` (or collapses it to a point when there is no target). */
  const spotlightTo = useCallback((rect: Box | null, fromPoint: boolean): Promise<void> => {
    const spring = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 320, damping: 36, mass: 0.8 };
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const r = rect
      ? { t: rect.top - PAD, l: rect.left - PAD, w: rect.width + PAD * 2, h: rect.height + PAD * 2 }
      : { t: vh / 2 - 24, l: vw / 2, w: 0, h: 0 };
    if (fromPoint) {
      top.set(r.t + r.h / 2);
      left.set(r.l + r.w / 2);
      width.set(0);
      height.set(0);
    }
    const ctrls = [
      animate(top, r.t, spring), animate(left, r.l, spring), animate(width, r.w, spring), animate(height, r.h, spring),
      animate(ring, rect ? 1 : 0, { duration: reduce ? 0 : 0.3 }),
    ];
    return Promise.all(ctrls.map((c) => new Promise<void>((res) => c.then(res)))).then(() => undefined);
  }, [reduce, top, left, width, height, ring]);

  // Mount while a tour runs; fade out and unmount shortly after it ends.
  useEffect(() => {
    if (activeTour) { setMounted(true); return; }
    setCardOn(false);
    setLayerOn(false);
    layerShown.current = false;
    const id = setTimeout(() => { setMounted(false); setShown(null); lastRect.current = null; targetRef.current = null; }, 420);
    return () => clearTimeout(id);
  }, [activeTour]);

  // A tour only makes sense for the signed-in role. Anything else ends it quietly.
  useEffect(() => {
    if (activeTour && (authStatus === "unauthenticated" || (role && role !== activeTour))) dispatch(tourReset());
  }, [activeTour, role, authStatus, dispatch]);

  /**
   * One step = one strict sequence, so nothing pops in early:
   *  1 hide card  →  2 wait for the app shell  →  3 (collapse spotlight, navigate if needed)
   *  4 find + scroll to target  →  5 move the spotlight  →  6 only then fade the card in.
   */
  useEffect(() => {
    if (!activeTour || !step) return;
    let cancelled = false;
    const stop = () => cancelled;
    const pause = (ms: number) => (reduce ? Promise.resolve() : sleep(ms));
    const cardWasVisible = cardVisible.current;
    setCardOn(false);

    void (async () => {
      // Let the outgoing card finish leaving before anything else moves.
      if (cardWasVisible) await pause(170);
      if (cancelled) return;
      const shell = await until(() => Boolean(document.querySelector("[data-shell-ready]")), 12000, stop);
      if (cancelled) return;
      if (!shell) { dispatch(tourReset()); return; }

      const wantsRoute = step.route && step.route.startsWith(ROLE_PREFIX[activeTour]) && window.location.pathname !== step.route;
      if (wantsRoute) {
        const prev = lastRect.current;
        if (layerShown.current && prev) {
          // Close the spotlight to a point while the page swaps underneath.
          const t = reduce ? { duration: 0 } : { duration: 0.22, ease: EASE };
          void animate(ring, 0, { duration: reduce ? 0 : 0.15 });
          void animate(width, 0, t); void animate(height, 0, t);
          void animate(left, prev.left + prev.width / 2, t); void animate(top, prev.top + prev.height / 2, t);
          lastRect.current = { top: prev.top + prev.height / 2, left: prev.left + prev.width / 2, width: 0, height: 0 };
          await pause(220);
        }
        router.push(step.route!);
        await until(() => window.location.pathname === step.route, 8000, stop);
        if (cancelled) return;
        await pause(80); // let the new page paint
      }

      // Tell the page underneath what this step needs (wizard position, demo form values).
      dispatch(driveSet({ wizardGoal: step.wizard ? { goal: step.wizard.goal, sample: Boolean(step.wizard.sample) } : null, fill: step.fill ?? null }));

      /** Scroll a target into view, wait for it to stop moving, and move the spotlight onto it. */
      const focusOn = async (target: HTMLElement | null) => {
        let rect: Box | null = null;
        if (target) {
          ensureVisible(target, reduce);
          await settle(target, stop);
          if (cancelled) return null;
          rect = toBox(target.getBoundingClientRect());
        }
        targetRef.current = target;
        setHasTarget(Boolean(target));
        settledRef.current = false;
        const first = !layerShown.current;
        layerShown.current = true;
        setLayerOn(true);
        lastRect.current = rect;
        const landed = spotlightTo(rect, first).then(() => { if (!cancelled) settledRef.current = true; });
        return { rect, landed };
      };

      // Find the target. Steps that depend on slow data (AI grading) spotlight a loading placeholder
      // as soon as it exists, then keep waiting for the real thing.
      let el: HTMLElement | null = null;
      let landed: Promise<void> | null = null;
      let rect: Box | null = null;
      if (step.target) {
        const t0 = performance.now();
        const patient = Boolean(step.waitMs);
        const maxWait = step.waitMs ?? 4000;
        const fallbackAfter = step.fallbackTarget ? (wantsRoute || !layerShown.current ? 2200 : 300) : Infinity;
        let interim: HTMLElement | null = null;
        while (!cancelled && performance.now() - t0 < maxWait) {
          el = findVisible(step.target);
          if (el) break;
          if (patient) {
            const fb = findVisible(step.fallbackTarget);
            if (fb && fb !== interim) {
              interim = fb;
              const f = await focusOn(fb);
              if (!f || cancelled) return;
            }
          } else if (performance.now() - t0 > fallbackAfter) {
            el = findVisible(step.fallbackTarget);
            if (el) break;
          }
          await sleep(60);
        }
        if (cancelled) return;
        if (!el) el = interim ?? findVisible(step.fallbackTarget);
      }
      if (cancelled) return;

      // Content that must finish loading first (e.g. the price card's data).
      if (step.ready) await until(() => Boolean(document.querySelector(step.ready!)), step.waitMs ?? 6000, stop);
      if (cancelled) return;

      // Swap the card's content while it is invisible, then measure it.
      setShown({ tour: activeTour, index: stepIndex });
      await frame(); await frame();
      if (cancelled) return;

      // Background first...
      const f = await focusOn(el);
      if (!f || cancelled) return;
      landed = f.landed;
      rect = f.rect;

      // ...then the card, once the background has landed (bounded so it can never stall).
      await Promise.race([landed, pause(600)]);
      await pause(40);
      if (cancelled) return;
      place(rect);
      await frame();
      if (cancelled) return;
      setCardOn(true);
    })();

    return () => { cancelled = true; };
  }, [activeTour, stepIndex, step, reduce, router, dispatch, spotlightTo, place, top, left, width, height, ring]);

  // Keep the spotlight glued to its target on scroll / resize / layout shifts (no spring, just follow).
  useEffect(() => {
    if (!mounted) return;
    let raf = 0;
    const sync = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (!settledRef.current) return;
        const el = targetRef.current;
        if (!el) { place(null); return; }
        if (!el.isConnected) return;
        const b = toBox(el.getBoundingClientRect());
        lastRect.current = b;
        top.set(b.top - PAD); left.set(b.left - PAD); width.set(b.width + PAD * 2); height.set(b.height + PAD * 2);
        place(b);
      });
    };
    window.addEventListener("resize", sync);
    window.addEventListener("scroll", sync, true);
    const ro = new ResizeObserver(sync);
    ro.observe(document.body);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", sync); window.removeEventListener("scroll", sync, true); ro.disconnect(); };
  }, [mounted, place, top, left, width, height]);

  // Keyboard: Esc skips, arrows move.
  useEffect(() => {
    if (!activeTour) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch(tourSkipped());
      if (e.key === "ArrowRight") dispatch(last ? tourCompleted() : stepChanged(stepIndex + 1));
      if (e.key === "ArrowLeft" && stepIndex > 0) dispatch(stepChanged(stepIndex - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeTour, dispatch, last, stepIndex]);

  useEffect(() => { cardVisible.current = cardOn; if (cardOn) cardRef.current?.focus({ preventScroll: true }); }, [cardOn, shown?.index]);

  if (!mounted) return null;

  const tourRole = shown?.tour ?? activeTour;
  const list = tourRole ? tourSteps(tourRole) : [];
  const index = shown?.index ?? stepIndex;
  const view = list[index];
  const isLast = index === list.length - 1;

  return (
    // Plain CSS transitions for the two fades: framer's WAAPI opacity can flash a single frame at the hand-off.
    <div
      className={cn("fixed inset-0 z-[80] transition-opacity duration-[350ms] ease-out motion-reduce:transition-none", layerOn ? "opacity-100" : "opacity-0")}
      style={{ pointerEvents: layerOn && activeTour ? "auto" : "none" }}
      // While fading out after Esc/Finish, hide it from assistive tech and keyboard focus immediately.
      aria-hidden={!activeTour}
      inert={!activeTour}
    >
      <motion.div
        aria-hidden
        data-tour-spotlight=""
        className="absolute rounded-xl"
        style={{ top, left, width, height, boxShadow: "0 0 0 9999px hsl(150 14% 4% / 0.66)" }}
      >
        <motion.span className="absolute inset-0 rounded-xl border-2 border-primary" style={{ opacity: ring }} />
      </motion.div>

      <motion.div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        data-tour-card=""
        tabIndex={-1}
        className="absolute left-0 top-0 outline-none"
        style={{ x: cardX, y: cardY, width: "min(24rem, calc(100vw - 1.5rem))", pointerEvents: cardOn ? "auto" : "none" }}
      >
        <div
          data-tour-card-inner=""
          className={cn(
            "rounded-xl border bg-popover p-4 shadow-2xl transition-[opacity,transform] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none sm:p-5",
            cardOn ? "translate-y-0 scale-100 opacity-100 duration-[320ms]" : "translate-y-2.5 scale-[0.97] opacity-0 duration-[160ms]",
          )}
        >
          {view && (
            <>
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  Step {index + 1} of {list.length}
                  {!hasTarget && view.target ? " · Highlight unavailable on this screen" : ""}
                </p>
                <button onClick={() => dispatch(tourSkipped())} className="-m-2 inline-flex min-h-touch min-w-touch items-center justify-center text-muted-foreground transition-colors hover:text-foreground" aria-label="Skip tour">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-1 flex gap-1" aria-hidden>
                {list.map((s, i) => <span key={s.id} className={`h-1 flex-1 rounded-full transition-colors duration-300 ${i <= index ? "bg-primary" : "bg-muted"}`} />)}
              </div>
              <h2 id="tour-title" className="mt-3 text-lg font-semibold">{view.title}</h2>
              <p id="tour-body" className="mt-1 text-sm text-muted-foreground">{view.body}</p>
              {view.nextAction && (
                <p className="mt-3 flex items-center gap-1.5 rounded-md bg-primary-soft px-3 py-2 text-xs font-medium text-primary">
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden /> Next recommended: {view.nextAction}
                </p>
              )}
              <div className="mt-4 flex items-center justify-between gap-2">
                <Button variant="ghost" size="sm" onClick={() => dispatch(tourSkipped())}>Skip tour</Button>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={index === 0} onClick={() => dispatch(stepChanged(index - 1))}>Back</Button>
                  <Button size="sm" onClick={() => dispatch(isLast ? tourCompleted() : stepChanged(index + 1))}>{isLast ? "Finish" : "Next"}</Button>
                </div>
              </div>
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function CompletionToast() {
  const dispatch = useAppDispatch();
  const celebrate = useAppSelector((s) => s.tour.celebrate);
  useEffect(() => {
    if (!celebrate) return;
    const id = setTimeout(() => dispatch(tourAck()), 6000);
    return () => clearTimeout(id);
  }, [celebrate, dispatch]);
  return (
    <AnimatePresence>
      {celebrate && (
        <motion.div
          role="status"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: EASE }}
          className="fixed inset-x-3 bottom-24 z-[75] mx-auto flex max-w-sm items-center gap-3 rounded-xl border bg-popover p-4 shadow-xl md:bottom-6"
        >
          <PartyPopper className="h-6 w-6 shrink-0 text-primary" aria-hidden />
          <p className="text-sm"><strong>Tour complete.</strong> Restart it any time from the help icon in the header.</p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function TourProvider({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <TourOverlay />
      <CompletionToast />
    </>
  );
}
