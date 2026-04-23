"use client";

import { motion, useReducedMotion } from "framer-motion";

export function SupraPacificText() {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      className="relative overflow-hidden rounded-full border border-white/10 bg-white/[0.035] px-4 py-2"
      initial={reducedMotion ? false : { opacity: 0, y: 10 }}
      animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
      transition={reducedMotion ? undefined : { duration: 0.56, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
    >
      <span className="supra-text relative z-10 text-sm font-semibold tracking-[0.24em]">
        Supra Pacific
      </span>
      {!reducedMotion ? (
        <motion.span
          aria-hidden="true"
          className="absolute inset-y-0 left-[-35%] w-[34%] rounded-full bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.55),transparent)] blur-md"
          animate={{ x: ["0%", "390%"] }}
          transition={{ duration: 1.15, delay: 1, ease: "easeInOut" }}
        />
      ) : null}
    </motion.div>
  );
}
