import { Nfc } from "lucide-react";

function Card({ tone, number, className }: { tone: "front" | "back"; number: string; className: string }) {
  return (
    <div className={`hero-float absolute ${className}`}>
      <div
        className={`hero-card relative flex aspect-[1.586] w-[17rem] flex-col justify-between rounded-2xl border p-5 sm:w-[21rem] sm:p-6 ${
          tone === "front"
            ? "border-ink/20 bg-[linear-gradient(135deg,#0d0f0a_0%,#171a11_55%,#3b4a10_100%)]"
            : "border-ink/10 bg-[linear-gradient(135deg,#0b0c09_0%,#121410_60%,#252d0c_100%)]"
        }`}
      >
        <div className="flex items-start justify-between">
          <span className="font-display text-xl font-extrabold tracking-tight text-ink">Ritam</span>
          <Nfc aria-hidden className="size-6 text-ink/70" />
        </div>
        <div className="h-7 w-10 rounded-md bg-[linear-gradient(135deg,#e9ffb0,#a8d42a)] opacity-90" />
        <div>
          <p className="font-display text-lg font-semibold tracking-[0.18em] text-ink sm:text-xl">{number}</p>
          <div className="mt-2 flex justify-between text-[0.6875rem] font-medium text-ink/70">
            <span>YOUR CARD, CHECKED</span>
            <span>12 / 30</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Two tilted cards floating over a neon disc. Decorative: hidden from screen readers. */
export function HeroCards() {
  return (
    <div aria-hidden className="relative h-[19rem] sm:h-[26rem]">
      <div className="absolute right-[-30%] top-1/2 size-[22rem] -translate-y-1/2 rounded-full bg-neon sm:size-[30rem]" />
      <div className="hero-stage absolute inset-0">
        <Card tone="back" number="•••• 4021 7788 2026" className="left-[8%] top-[34%] [animation-delay:250ms]" />
        <Card tone="front" number="•••• 1000 0000 2026" className="left-[2%] top-[8%]" />
      </div>
    </div>
  );
}
