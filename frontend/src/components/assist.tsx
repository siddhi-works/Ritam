"use client";

import { Contrast, Mic, Square, Type, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/* Reading aids for people who find small text or typing hard. Everything runs in the browser's
   own speech engine: nothing is sent to Ritam's server or any AI. */

const BTN =
  "print:hidden inline-flex min-h-11 items-center gap-2 rounded-md border border-ink/45 px-3 text-sm font-medium text-ink hover:border-neon aria-pressed:border-neon aria-pressed:text-neon";

/** Reads the text of the element with `targetId` aloud. Hidden when the browser cannot speak. */
export function ListenButton({ targetId, label = "Listen" }: { targetId: string; label?: string }) {
  const [supported, setSupported] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  useEffect(() => {
    setSupported("speechSynthesis" in window);
    return () => {
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    };
  }, []);
  if (!supported) return null;

  function toggle() {
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    const text = document.getElementById(targetId)?.innerText.split(label).join(" ").replace(/\s+/g, " ").trim();
    if (!text) return;
    const u = new SpeechSynthesisUtterance(text.replace(/₹/g, "rupees "));
    u.lang = "en-IN";
    u.rate = 0.92;
    u.voice = synth.getVoices().find((v) => v.lang === "en-IN") ?? null;
    u.onend = u.onerror = () => setSpeaking(false);
    synth.cancel();
    synth.speak(u);
    setSpeaking(true);
  }

  return (
    <button type="button" onClick={toggle} aria-pressed={speaking} className={BTN}>
      {speaking ? <Square aria-hidden className="size-4" /> : <Volume2 aria-hidden className="size-4" />}
      {speaking ? "Stop" : label}
    </button>
  );
}

interface Recognition {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Speak instead of typing. `languages` lets the person pick Hindi for a question. */
export function VoiceButton({
  onText,
  what,
  languages = ["en-IN"],
}: {
  onText: (text: string) => void;
  what: string;
  languages?: ("en-IN" | "hi-IN")[];
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const rec = useRef<Recognition | null>(null);
  useEffect(() => {
    setSupported(recognitionCtor() !== null);
    return () => rec.current?.stop();
  }, []);
  if (!supported) return null;

  function start(lang: string) {
    if (listening) {
      rec.current?.stop();
      return;
    }
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    const r = new Ctor();
    r.lang = lang;
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onresult = (e) => {
      const text = e.results[0]?.[0]?.transcript?.trim();
      if (text) {
        onText(text);
        setNote(`Heard: “${text}”`);
      }
    };
    r.onerror = (e) =>
      setNote(e.error === "not-allowed" ? "Allow the microphone in your browser to speak." : "Didn't catch that. Try again.");
    r.onend = () => setListening(null);
    rec.current = r;
    setNote("");
    setListening(lang);
    r.start();
  }

  return (
    <div className="flex flex-wrap items-center gap-2 print:hidden">
      {languages.map((lang) => (
        <button
          key={lang}
          type="button"
          onClick={() => start(lang)}
          aria-pressed={listening === lang}
          className={BTN}
        >
          <Mic aria-hidden className="size-4" />
          {listening === lang ? (
            "Listening… tap to stop"
          ) : lang === "hi-IN" ? (
            <span lang="hi">हिंदी में बोलें</span>
          ) : (
            `Say ${what}`
          )}
        </button>
      ))}
      <span role="status" className="text-sm text-mute">
        {note}
      </span>
    </div>
  );
}

type Pref = "contrast" | "large";

function read(p: Pref): boolean {
  try {
    return localStorage.getItem(`ritam.${p}`) === "1";
  } catch {
    return false;
  }
}

/** Header toggles for larger text and high contrast; remembered on this device. */
export function ReadingControls({ labelled = false }: { labelled?: boolean }) {
  const [on, setOn] = useState<Record<Pref, boolean>>({ contrast: false, large: false });
  useEffect(() => setOn({ contrast: read("contrast"), large: read("large") }), []);

  function flip(p: Pref) {
    const next = !on[p];
    setOn((o) => ({ ...o, [p]: next }));
    document.documentElement.dataset[p] = next ? "1" : "";
    try {
      localStorage.setItem(`ritam.${p}`, next ? "1" : "0");
    } catch {
      /* private mode: the setting lasts until the tab closes */
    }
  }

  const cls =
    "inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2 text-sm text-ink hover:text-neon aria-pressed:text-neon";
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Reading options">
      <button type="button" aria-pressed={on.large} onClick={() => flip("large")} className={cls} title="Larger text">
        <Type aria-hidden className="size-4" />
        <span className={labelled ? "" : "sr-only lg:not-sr-only"}>Larger text</span>
      </button>
      <button type="button" aria-pressed={on.contrast} onClick={() => flip("contrast")} className={cls} title="High contrast">
        <Contrast aria-hidden className="size-4" />
        <span className={labelled ? "" : "sr-only lg:not-sr-only"}>High contrast</span>
      </button>
    </div>
  );
}
