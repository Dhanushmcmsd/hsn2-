"use client";

import { motion, useReducedMotion } from "framer-motion";

type FlagBackgroundProps = {
  className?: string;
};

export function FlagBackground({ className = "" }: FlagBackgroundProps) {
  const reducedMotion = useReducedMotion();

  if (reducedMotion) {
    return (
      <div
        aria-hidden="true"
        className={`pointer-events-none absolute overflow-hidden rounded-[999px] opacity-[0.08] ${className}`}
        style={{ mixBlendMode: "soft-light" }}
      >
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(255,153,51,0.7)_0%,rgba(255,255,255,0.5)_45%,rgba(19,136,8,0.7)_100%)] blur-2xl" />
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none absolute overflow-hidden rounded-[999px] opacity-[0.08] ${className}`}
      style={{ mixBlendMode: "soft-light" }}
    >
      <motion.div
        className="absolute inset-[-12%]"
        animate={{ x: [-16, 20, -16] }}
        transition={{ duration: 24, repeat: Infinity, ease: "easeInOut" }}
      >
        <motion.div
          className="absolute inset-0"
          animate={{
            y: [-3, 4, -3],
            rotateZ: [-0.35, 0.55, -0.35],
            skewX: [-3, 2, -3],
          }}
          transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
        >
          <div className="absolute inset-0 rounded-[999px] bg-[linear-gradient(90deg,rgba(255,153,51,0.9)_0%,rgba(255,214,170,0.72)_24%,rgba(255,255,255,0.68)_44%,rgba(228,255,232,0.62)_62%,rgba(19,136,8,0.85)_100%)] blur-[22px]" />
          <div className="absolute inset-y-[30%] left-[22%] right-[36%] rounded-full bg-[radial-gradient(circle,rgba(255,196,125,0.3)_0%,transparent_72%)] blur-2xl" />
          <div className="noise-overlay absolute inset-0 opacity-40" />
        </motion.div>
      </motion.div>

      <div className="absolute inset-y-0 left-0 w-[28%] bg-gradient-to-r from-[#020617] via-[#020617]/70 to-transparent" />
      <div className="absolute inset-y-0 right-0 w-[28%] bg-gradient-to-l from-[#020617] via-[#020617]/70 to-transparent" />
      <div className="absolute inset-x-0 top-0 h-[38%] bg-gradient-to-b from-[#020617] via-[#020617]/55 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-[38%] bg-gradient-to-t from-[#020617] via-[#020617]/55 to-transparent" />
    </div>
  );
}
