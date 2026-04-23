"use client";

import { motion, useReducedMotion } from "framer-motion";
import { LogoAnimation } from "@/components/LogoAnimation";

export function SupraPacificText() {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      className="group relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.045] px-4 py-3 backdrop-blur-xl"
      initial={reducedMotion ? false : { opacity: 0, y: 10 }}
      animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
      transition={reducedMotion ? undefined : { duration: 0.56, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="relative z-10 flex items-center gap-3">
        <div className="rounded-xl border border-white/10 bg-slate-950/35 p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
          <LogoAnimation className="h-8 w-8" />
        </div>
        <div className="min-w-0">
          <div className="supra-text text-sm font-semibold tracking-[0.22em]">
            Supra Pacific
          </div>
          <div className="font-mono-alt text-[10px] uppercase tracking-[0.22em] text-slate-500">
            Product intelligence
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-0 rounded-2xl border border-cyan-300/0 transition duration-500 group-hover:border-cyan-300/15" />
      {!reducedMotion ? (
        <motion.span
          aria-hidden="true"
          className="absolute inset-y-0 left-[-35%] w-[34%] bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.55),transparent)] blur-md"
          animate={{ x: ["0%", "390%"] }}
          transition={{ duration: 1.15, delay: 1, ease: "easeInOut" }}
        />
      ) : null}
    </motion.div>
  );
}
