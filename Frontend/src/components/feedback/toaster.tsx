"use client";
import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { toastDismissed, type Toast } from "@/store/slices/notifications.slice";

const icons = { success: CheckCircle2, error: XCircle, info: Info } as const;
const tone = { success: "text-success", error: "text-danger", info: "text-primary" } as const;

function ToastItem({ toast }: { toast: Toast }) {
  const dispatch = useAppDispatch();
  const Icon = icons[toast.kind];
  useEffect(() => {
    const id = setTimeout(() => dispatch(toastDismissed(toast.id)), 5000);
    return () => clearTimeout(id);
  }, [dispatch, toast.id]);
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      className="pointer-events-auto flex items-start gap-3 rounded-lg border bg-popover p-3 pr-2 shadow-lg"
    >
      <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${tone[toast.kind]}`} aria-hidden />
      <p className="flex-1 text-sm">{toast.message}</p>
      <button
        onClick={() => dispatch(toastDismissed(toast.id))}
        className="inline-flex min-h-touch min-w-touch items-center justify-center text-muted-foreground hover:text-foreground"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </motion.li>
  );
}

export function Toaster() {
  const toasts = useAppSelector((s) => s.notifications.toasts);
  return (
    <div
      role="region"
      aria-label="Notifications"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-3 bottom-20 z-[70] mx-auto max-w-sm md:inset-x-auto md:bottom-6 md:right-6"
    >
      <ol className="flex flex-col gap-2">
        <AnimatePresence>{toasts.map((t) => <ToastItem key={t.id} toast={t} />)}</AnimatePresence>
      </ol>
    </div>
  );
}
