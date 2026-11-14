"use client";

import { Nfc } from "lucide-react";
import { useRef } from "react";

function Card({ tone, number, className }: { tone: "front" | "back"; number: string; className: string }) {
  return (
    <div className={`hero-float absolute ${className}`}>
      <div
        className={`hero-card relative flex aspect-[1.586] w-[19rem] flex-col justify-between rounded-2xl border p-6 sm:w-[26rem] sm:p-7 ${
          tone === "front"
            ? "hero-card-front border-ink/20 bg-[linear-gradient(135deg,#0d0f0a_0%,#171a11_55%,#3b4a10_100%)]"
            : "hero-card-back border-ink/10 bg-[linear-gradient(135deg,#0b0c09_0%,#121410_60%,#252d0c_100%)]"
        }`}
      >
        <div className="flex items-start justify-between">
          <span className="font-display text-2xl font-extrabold tracking-tight text-neon">Ritam</span>
          <Nfc aria-hidden className="size-7 text-ink/70" />
        </div>
        <div className="h-8 w-12 rounded-md bg-[linear-gradient(135deg,#e9ffb0,#a8d42a)] opacity-90" />
        <div>
          <p className="font-display text-xl font-semibold tracking-[0.18em] text-ink sm:text-2xl">{number}</p>
          <div className="mt-2 flex justify-between text-xs font-medium text-ink/70">
            <span>YOUR CARD, CHECKED</span>
            <span>12 / 30</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Two tilted cards over a neon disc. They lean towards the pointer and the one under it lifts;
 * motion only follows the person (and is off with reduced motion). Decorative: hidden from
 * screen readers. */
export function HeroCards() {
  const stage = useRef<HTMLDivElement>(null);

  function follow(e: React.PointerEvent<HTMLDivElement>) {
    const el = stage.current;
    if (!el || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5; // -0.5 .. 0.5
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--tilt-x", `${(-y * 14).toFixed(2)}deg`);
    el.style.setProperty("--tilt-y", `${(x * 18).toFixed(2)}deg`);
    el.style.setProperty("--shift-x", `${(x * 24).toFixed(1)}px`);
    el.style.setProperty("--shift-y", `${(y * 18).toFixed(1)}px`);
  }

  function rest() {
    for (const p of ["--tilt-x", "--tilt-y", "--shift-x", "--shift-y"]) stage.current?.style.removeProperty(p);
  }

  return (
    <div
      ref={stage}
      aria-hidden
      className="relative h-[22rem] sm:h-[32rem]"
      onPointerMove={follow}
      onPointerLeave={rest}
    >
      <div className="hero-disc absolute right-[-30%] top-1/2 size-[24rem] rounded-full bg-neon sm:size-[36rem]" />
      <div className="hero-stage absolute inset-0">
        <div className="hero-tilt absolute inset-0">
          <Card tone="back" number="•••• 4021 7788 2026" className="left-[6%] top-[36%] [animation-delay:250ms]" />
          <Card tone="front" number="•••• 1000 0000 2026" className="left-0 top-[6%]" />
        </div>
      </div>
    </div>
  );
}
