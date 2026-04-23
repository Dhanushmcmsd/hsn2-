"use client";

import { motion, useReducedMotion } from "framer-motion";
import { LogoAnimation } from "@/components/LogoAnimation";

export function SupraPacificText() {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      className="group relative inline-flex overflow-hidden"
      initial={reducedMotion ? false : { opacity: 0, y: 10 }}
      animate={reducedMotion ? undefined : { opacity: 1, y: 0 }}
      transition={reducedMotion ? undefined : { duration: 0.56, delay: 0.3, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="relative z-10 flex items-center gap-3">
        <LogoAnimation className="h-10 w-10 shrink-0" />
        <div className="min-w-0">
          <div className="flex items-baseline gap-2 whitespace-nowrap font-display text-[2rem] font-bold leading-none tracking-[-0.04em]">
            <span className="text-[#ff4d3b] drop-shadow-[0_0_16px_rgba(255,77,59,0.12)]">Supra</span>
            <span className="text-[#3b82f6] drop-shadow-[0_0_18px_rgba(59,130,246,0.14)]">Pacific</span>
          </div>
          <div className="mt-1 font-mono-alt text-[10px] uppercase tracking-[0.34em] text-slate-400">
            Product intelligence
          </div>
        </div>
      </div>

      {!reducedMotion ? (
        <motion.span
          aria-hidden="true"
          className="absolute inset-y-0 left-[-18%] w-[22%] bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.4),transparent)] blur-md"
          animate={{ x: ["0%", "390%"] }}
          transition={{ duration: 1.15, delay: 1, ease: "easeInOut" }}
        />
      ) : null}
    </motion.div>
  );
}
