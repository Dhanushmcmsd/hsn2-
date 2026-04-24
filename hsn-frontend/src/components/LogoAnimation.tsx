"use client";

import { motion, useReducedMotion } from "framer-motion";

type LogoAnimationProps = {
  className?: string;
};

const easeOut = [0.22, 1, 0.36, 1] as const;

const bracketPaths = [
  { key: "tl", path: "M0 0H32V10H10V32H0Z", originX: 16, originY: 16 },
  { key: "tr", path: "M68 0H100V32H90V10H68Z", originX: 84, originY: 16 },
  { key: "bl", path: "M0 68H10V90H32V100H0Z", originX: 16, originY: 84 },
  { key: "br", path: "M68 90H90V68H100V100H68Z", originX: 84, originY: 84 },
];

const squareSize = 12;
const squareRadius = 1.5;
const centerSquare = { x: 44, y: 44 };
const armSquares = [
  { key: "top-left", x: 28, y: 28, delay: 0.35 },
  { key: "top-right", x: 60, y: 28, delay: 0.39 },
  { key: "bottom-left", x: 28, y: 60, delay: 0.43 },
  { key: "bottom-right", x: 60, y: 60, delay: 0.47 },
];

export function LogoAnimation({ className = "" }: LogoAnimationProps) {
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      className={className}
      initial={
        reducedMotion
          ? false
          : { filter: "drop-shadow(0 0 6px rgba(232,25,44,0.15))" }
      }
      animate={
        reducedMotion
          ? undefined
          : {
              filter: [
                "drop-shadow(0 0 6px rgba(232,25,44,0.15))",
                "drop-shadow(0 0 12px rgba(232,25,44,0.28))",
                "drop-shadow(0 0 6px rgba(232,25,44,0.15))",
              ],
            }
      }
      transition={
        reducedMotion
          ? undefined
          : { duration: 3.5, delay: 0.8, ease: "easeInOut", repeat: Infinity }
      }
    >
      <svg
        viewBox="0 0 100 100"
        className="h-full w-full"
        preserveAspectRatio="xMidYMid meet"
        style={{ overflow: "visible" }}
      >
        {bracketPaths.map((corner) => (
          <motion.g
            key={corner.key}
            style={{ originX: corner.originX, originY: corner.originY }}
            initial={reducedMotion ? false : { opacity: 0, scale: 0.7 }}
            animate={reducedMotion ? { opacity: 1, scale: 1 } : { opacity: 1, scale: 1 }}
            transition={
              reducedMotion
                ? undefined
                : {
                    duration: 0.38,
                    ease: easeOut,
                  }
            }
          >
            <path d={corner.path} fill="#173f8a" />
          </motion.g>
        ))}

        <motion.rect
          x={centerSquare.x}
          y={centerSquare.y}
          width={squareSize}
          height={squareSize}
          rx={squareRadius}
          fill="#e8192c"
          style={{ originX: centerSquare.x + squareSize / 2, originY: centerSquare.y + squareSize / 2 }}
          initial={reducedMotion ? false : { scale: 0, opacity: 0 }}
          animate={
            reducedMotion
              ? { scale: 1, opacity: 1 }
              : { scale: [0, 1.15, 1], opacity: [0, 1, 1] }
          }
          transition={
            reducedMotion
              ? undefined
              : { duration: 0.28, delay: 0.2, ease: easeOut, times: [0, 0.72, 1] }
          }
        />

        {armSquares.map((square) => (
          <motion.rect
            key={square.key}
            x={centerSquare.x}
            y={centerSquare.y}
            width={squareSize}
            height={squareSize}
            rx={squareRadius}
            fill="#e8192c"
            initial={reducedMotion ? false : { x: 0, y: 0, opacity: 0 }}
            animate={
              reducedMotion
                ? { x: square.x - centerSquare.x, y: square.y - centerSquare.y, opacity: 1 }
                : { x: square.x - centerSquare.x, y: square.y - centerSquare.y, opacity: 1 }
            }
            transition={
              reducedMotion
                ? undefined
                : {
                    duration: 0.32,
                    delay: square.delay,
                    ease: easeOut,
                  }
            }
          />
        ))}
      </svg>
    </motion.div>
  );
}
