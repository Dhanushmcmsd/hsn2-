"use client";

import { motion, useReducedMotion } from "framer-motion";

type LogoAnimationProps = {
  className?: string;
};

const redSquares = [
  { key: "top", x: 0, y: -20 },
  { key: "right", x: 20, y: 0 },
  { key: "bottom", x: 0, y: 20 },
  { key: "left", x: -20, y: 0 },
];

const blueCorners = [
  { key: "tl", x: 18, y: 18, path: "M0 16V0h16" },
  { key: "tr", x: 66, y: 18, path: "M0 0h16v16" },
  { key: "br", x: 66, y: 66, path: "M16 0v16H0" },
  { key: "bl", x: 18, y: 66, path: "M16 16H0V0" },
];

export function LogoAnimation({ className = "" }: LogoAnimationProps) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      className={className}
      initial={reducedMotion ? false : { filter: "drop-shadow(0 0 0 rgba(96,165,250,0))" }}
      animate={
        reducedMotion
          ? undefined
          : {
              filter: [
                "drop-shadow(0 0 0 rgba(96,165,250,0))",
                "drop-shadow(0 0 14px rgba(96,165,250,0.2))",
                "drop-shadow(0 0 9px rgba(96,165,250,0.1))",
              ],
            }
      }
      transition={reducedMotion ? undefined : { duration: 0.34, delay: 1.16, ease: [0.22, 1, 0.36, 1] }}
    >
      <svg viewBox="0 0 100 100" className="h-full w-full overflow-visible">
        <motion.rect
          x="42"
          y="42"
          width="16"
          height="16"
          rx="1.5"
          fill="#ef2b2d"
          initial={reducedMotion ? false : { scale: 0.92, opacity: 0.96 }}
          animate={reducedMotion ? undefined : { scale: 1, opacity: 1 }}
          transition={reducedMotion ? undefined : { duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        />

        {redSquares.map((square, index) => (
          <motion.rect
            key={square.key}
            x="42"
            y="42"
            width="16"
            height="16"
            rx="1.5"
            fill="#ef2b2d"
            initial={reducedMotion ? false : { x: 0, y: 0, scale: 0.55, opacity: 0 }}
            animate={reducedMotion ? { x: square.x, y: square.y, scale: 1, opacity: 1 } : { x: square.x, y: square.y, scale: 1, opacity: 1 }}
            transition={
              reducedMotion
                ? undefined
                : {
                    duration: 0.42,
                    delay: 0.16 + index * 0.06,
                    ease: [0.22, 1, 0.36, 1],
                  }
            }
          />
        ))}

        {blueCorners.map((corner, index) => (
          <motion.path
            key={corner.key}
            d={corner.path}
            fill="none"
            stroke="#173f8a"
            strokeWidth="8"
            strokeLinecap="square"
            strokeLinejoin="miter"
            transform={`translate(${corner.x} ${corner.y})`}
            initial={reducedMotion ? false : { pathLength: 0, opacity: 0, scale: 0.92 }}
            animate={reducedMotion ? { pathLength: 1, opacity: 1, scale: 1 } : { pathLength: 1, opacity: 1, scale: 1 }}
            transition={
              reducedMotion
                ? undefined
                : {
                    duration: 0.34,
                    delay: 0.62 + index * 0.06,
                    ease: [0.22, 1, 0.36, 1],
                  }
            }
          />
        ))}
      </svg>
    </motion.div>
  );
}
