"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

type FloatItem = {
  id: string;
  className: string;
  duration: number;
  delay: number;
  xFactor: number;
  yFactor: number;
  content: ReactNode;
};

const items: FloatItem[] = [
  {
    id: "invoice",
    className: "left-[6%] top-[18%] h-32 w-24 rotate-[-8deg]",
    duration: 15,
    delay: 0,
    xFactor: 14,
    yFactor: 10,
    content: (
      <div className="floating-surface h-full w-full rounded-2xl p-3">
        <div className="h-2 w-12 rounded-full bg-white/20" />
        <div className="mt-3 h-px w-full bg-white/10" />
        <div className="mt-3 space-y-2">
          <div className="h-1.5 w-[68%] rounded-full bg-white/12" />
          <div className="h-1.5 w-[88%] rounded-full bg-white/10" />
          <div className="h-1.5 w-[54%] rounded-full bg-white/8" />
        </div>
      </div>
    ),
  },
  {
    id: "barcode",
    className: "right-[8%] top-[16%] h-20 w-36",
    duration: 18,
    delay: 2,
    xFactor: 12,
    yFactor: 8,
    content: (
      <div className="floating-surface flex h-full w-full items-center rounded-2xl px-4">
        <div className="flex h-10 w-full items-end gap-1">
          {[10, 18, 14, 28, 8, 24, 16, 20, 11, 26, 12, 18].map((height, index) => (
            <span
              key={height + index}
              className="block w-1 rounded-full bg-white/14"
              style={{ height }}
            />
          ))}
        </div>
      </div>
    ),
  },
  {
    id: "grid",
    className: "left-[12%] bottom-[14%] h-28 w-28 rotate-[6deg]",
    duration: 17,
    delay: 1,
    xFactor: 10,
    yFactor: 12,
    content: (
      <div className="floating-surface grid h-full w-full grid-cols-4 gap-1 rounded-3xl p-3">
        {Array.from({ length: 16 }).map((_, index) => (
          <span key={index} className="rounded-md border border-white/8 bg-white/[0.02]" />
        ))}
      </div>
    ),
  },
  {
    id: "hsn",
    className: "right-[12%] bottom-[20%] h-24 w-40 rotate-[-4deg]",
    duration: 16,
    delay: 3,
    xFactor: 16,
    yFactor: 10,
    content: (
      <div className="floating-surface flex h-full w-full flex-col justify-center rounded-3xl px-5">
        <div className="font-mono-alt text-[11px] uppercase tracking-[0.24em] text-white/30">
          HSN Codes
        </div>
        <div className="mt-2 space-y-1 font-mono-alt text-sm text-white/35">
          <div>09042211</div>
          <div>33061010</div>
          <div>21069099</div>
        </div>
      </div>
    ),
  },
  {
    id: "ledger",
    className: "left-1/2 top-[11%] h-20 w-32 -translate-x-1/2",
    duration: 20,
    delay: 4,
    xFactor: 8,
    yFactor: 6,
    content: (
      <div className="floating-surface flex h-full w-full items-center justify-between rounded-2xl px-4">
        <div className="space-y-2">
          <div className="h-1 w-12 rounded-full bg-white/12" />
          <div className="h-1 w-16 rounded-full bg-white/10" />
          <div className="h-1 w-10 rounded-full bg-white/8" />
        </div>
        <div className="font-display text-2xl font-bold text-white/20">₹</div>
      </div>
    ),
  },
];

export function FloatingElements() {
  const reducedMotion = useReducedMotion();
  const [pointer, setPointer] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (reducedMotion) {
      return;
    }

    const handleMove = (event: MouseEvent) => {
      const x = event.clientX / window.innerWidth - 0.5;
      const y = event.clientY / window.innerHeight - 0.5;
      setPointer({ x, y });
    };

    window.addEventListener("mousemove", handleMove, { passive: true });
    return () => window.removeEventListener("mousemove", handleMove);
  }, [reducedMotion]);

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      {items.map((item) => (
        <div
          key={item.id}
          className={`absolute opacity-[0.075] blur-[0.35px] ${item.className}`}
          style={{
            transform: `translate3d(${pointer.x * item.xFactor}px, ${pointer.y * item.yFactor}px, 0)`,
            willChange: "transform, opacity",
          }}
        >
          <motion.div
            animate={
              reducedMotion
                ? undefined
                : {
                    y: [-8, 10, -8],
                    x: [0, 4, 0],
                  }
            }
            transition={
              reducedMotion
                ? undefined
                : {
                    duration: item.duration,
                    delay: item.delay,
                    repeat: Infinity,
                    ease: "easeInOut",
                  }
            }
          >
            {item.content}
          </motion.div>
        </div>
      ))}
    </div>
  );
}
