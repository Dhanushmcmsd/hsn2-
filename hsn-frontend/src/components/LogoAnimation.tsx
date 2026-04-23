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
  { key: "tl", x: 8, y: 8, path: "M0 0H24V8H8V24H0Z" },
  { key: "tr", x: 68, y: 8, path: "M0 0H24V24H16V8H0Z" },
  { key: "br", x: 68, y: 68, path: "M16 0H24V24H0V16H16Z" },
  { key: "bl", x: 8, y: 68, path: "M0 0H8V16H24V24H0Z" },
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
      <svg viewBox="-8 -8 116 116" className="h-full w-full overflow-visible">
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
          <motion.g
            key={corner.key}
            transform={`translate(${corner.x} ${corner.y})`}
            initial={reducedMotion ? false : { opacity: 0, scale: 0.82 }}
            animate={reducedMotion ? { opacity: 1, scale: 1 } : { opacity: 1, scale: 1 }}
            transition={
              reducedMotion
                ? undefined
                : {
                    duration: 0.34,
                    delay: 0.62 + index * 0.06,
                    ease: [0.22, 1, 0.36, 1],
                  }
            }
          >
            <path d={corner.path} fill="#173f8a" />
          </motion.g>
        ))}
      </svg>
    </motion.div>
  );
}
