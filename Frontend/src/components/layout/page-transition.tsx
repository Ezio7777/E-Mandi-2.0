"use client";
import { motion, useReducedMotion } from "framer-motion";

/** Opacity only: no transform, so layout measurements (the tour spotlight) stay exact mid-transition. */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.26, ease: "easeOut" }}>
      {children}
    </motion.div>
  );
}
