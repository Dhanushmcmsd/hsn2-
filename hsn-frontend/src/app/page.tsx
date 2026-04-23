import Link from "next/link";
import { FlagBackground } from "@/components/FlagBackground";
import { FloatingElements } from "@/components/FloatingElements";
import { LogoAnimation } from "@/components/LogoAnimation";
import { SupraPacificText } from "@/components/SupraPacificText";

const demoRows = [
  { product: "Horlicks Womens 400g", hsn: "21069099", gst: "18%" },
  { product: "VKC Slipper Size 7", hsn: "64021000", gst: "5%" },
  { product: "Colgate TP 200g", hsn: "33061010", gst: "12%" },
  { product: "Amul Butter 500g", hsn: "04059000", gst: "12%" },
  { product: "Aashirvaad Atta 5kg", hsn: "11010000", gst: "5%" },
];

const featureCards = [
  {
    icon: "01",
    title: "Bulk Excel Upload",
    body:
      "Upload entire product catalogs as .xlsx or .csv and classify thousands of rows in one pass.",
  },
  {
    icon: "02",
    title: "AI-Powered Matching",
    body:
      "Understands abbreviations, invoice-style naming, and Indian trade vocabulary with confidence-aware matching.",
  },
  {
    icon: "03",
    title: "GST Precision",
    body:
      "Returns full 8-digit HSN codes with GST context, matched descriptions, and export-ready outputs.",
  },
];

export default function Home() {
  return (
    <main
      className="relative min-h-screen overflow-hidden text-slate-100"
      style={{
        background:
          "radial-gradient(circle at 18% 18%, rgba(37,99,235,0.18), transparent 28%), radial-gradient(circle at 84% 24%, rgba(14,165,233,0.08), transparent 26%), radial-gradient(circle at 50% 120%, rgba(15,23,42,0.95), transparent 38%), #020617",
      }}
    >
      <div
        className="pointer-events-none absolute inset-0 mix-blend-soft-light"
        style={{
          opacity: 0.045,
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0_0_180_180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)' opacity='.9'/%3E%3C/svg%3E\")",
        }}
      />
      <FloatingElements />

      <header className="sticky top-0 z-40 border-b border-white/8 bg-slate-950/65 backdrop-blur-2xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 lg:px-10">
          <Link href="/" className="flex items-center gap-3">
            <LogoAnimation className="h-10 w-10 shrink-0" />
            <div>
              <div className="font-display text-base font-bold tracking-[-0.03em] text-slate-50">
                HSN<span className="text-blue-400">iq</span>
              </div>
              <div className="font-mono-alt text-[10px] uppercase tracking-[0.28em] text-slate-500">
                Classification Engine
              </div>
            </div>
          </Link>

          <div className="flex items-center gap-4 sm:gap-6">
            <Link
              href="/login"
              className="hidden text-sm text-slate-400 transition hover:text-slate-100 sm:block"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="rounded-xl border border-blue-400/20 bg-gradient-to-b from-blue-500 to-blue-600 px-4 py-2 text-sm font-medium text-white shadow-[0_10px_30px_rgba(37,99,235,0.28)] transition hover:-translate-y-0.5 hover:shadow-[0_14px_40px_rgba(37,99,235,0.36)]"
            >
              Get Started
            </Link>
          </div>
        </div>
      </header>

      <section className="relative z-10 mx-auto grid max-w-7xl gap-16 px-6 pb-20 pt-20 lg:grid-cols-[1.05fr_.95fr] lg:px-10 lg:pb-28 lg:pt-28">
        <div className="max-w-2xl">
          <div className="inline-flex items-center gap-3 rounded-full border border-blue-400/15 bg-white/[0.03] px-4 py-2 font-mono-alt text-[11px] uppercase tracking-[0.24em] text-blue-200/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
            <span className="h-2 w-2 rounded-full bg-blue-400 shadow-[0_0_12px_rgba(96,165,250,0.9)]" />
            India · GST · HSN Classification
          </div>

          <div className="mt-8">
            <h1 className="group relative inline-flex max-w-full overflow-hidden rounded-[28px] border border-white/12 bg-white/[0.05] px-6 py-5 font-display text-[clamp(1.9rem,4vw,4rem)] font-black leading-none tracking-[-0.05em] text-white shadow-[0_24px_80px_rgba(2,6,23,0.55),inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-2xl">
              <FlagBackground className="-inset-x-10 -inset-y-5 opacity-100" />
              <span className="pointer-events-none absolute inset-0 noise-overlay opacity-[0.06]" />
              <span className="pointer-events-none absolute inset-[1px] rounded-[27px] bg-gradient-to-b from-white/[0.08] to-white/[0.02]" />
              <span className="pointer-events-none absolute inset-x-[18%] top-1/2 h-12 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.22)_0%,rgba(255,153,51,0.12)_36%,rgba(19,136,8,0.08)_70%,transparent_100%)] opacity-0 blur-2xl transition duration-500 group-hover:opacity-100" />
              <span className="relative z-10 whitespace-nowrap">
                India GST Classification
              </span>
            </h1>
          </div>

          <p className="mt-8 max-w-xl text-lg leading-8 text-slate-400">
            Premium GST classification tooling for Indian traders, distributors, and finance teams.
            Upload spreadsheets, resolve HSN codes, and export clean GST-ready results in minutes.
          </p>

          <div className="mt-10 flex flex-col gap-4 sm:flex-row">
            <Link
              href="/signup"
              className="inline-flex items-center justify-center rounded-2xl border border-blue-400/20 bg-gradient-to-r from-blue-500 via-blue-600 to-sky-500 px-6 py-3.5 text-sm font-semibold text-white shadow-[0_18px_50px_rgba(37,99,235,0.28)] transition hover:-translate-y-0.5"
            >
              Start classifying
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] px-6 py-3.5 text-sm font-medium text-slate-300 transition hover:border-white/20 hover:bg-white/[0.05] hover:text-white"
            >
              Sign in
            </Link>
          </div>

          <div className="mt-12 grid max-w-lg grid-cols-3 gap-4 border-t border-white/8 pt-8">
            {[
              ["6,000+", "rows per batch"],
              ["87%+", "match accuracy"],
              ["8-digit", "HSN precision"],
            ].map(([value, label]) => (
              <div key={label}>
                <div className="font-display text-3xl font-extrabold tracking-[-0.04em] text-white">
                  {value}
                </div>
                <div className="mt-1 font-mono-alt text-[10px] uppercase tracking-[0.24em] text-slate-500">
                  {label}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center justify-center pt-20 lg:pt-14">
          <div className="absolute right-0 top-0 z-10 hidden w-full max-w-[280px] lg:block">
            <SupraPacificText />
          </div>
          <div className="absolute inset-x-[8%] top-[8%] h-40 rounded-full bg-blue-500/10 blur-3xl" />
          <div className="relative w-full max-w-xl overflow-hidden rounded-[28px] border border-white/10 bg-white/[0.04] shadow-[0_30px_90px_rgba(2,6,23,0.65)] backdrop-blur-2xl lg:mt-8">
            <div className="flex items-center justify-between border-b border-white/8 bg-slate-950/35 px-5 py-4">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full bg-red-400/80" />
                <span className="h-2.5 w-2.5 rounded-full bg-amber-300/80" />
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
              </div>
              <span className="font-mono-alt text-[11px] uppercase tracking-[0.24em] text-slate-500">
                batch-classifier.live
              </span>
            </div>

            <div className="relative p-5">
              <div className="absolute inset-y-5 left-0 w-px bg-gradient-to-b from-transparent via-blue-400/50 to-transparent animate-scan-x" />
              <div className="space-y-3">
                {demoRows.map((row) => (
                  <div
                    key={row.product}
                    className="flex items-center gap-3 rounded-2xl border border-white/6 bg-slate-950/30 px-4 py-3"
                  >
                    <div className="flex-1">
                      <div className="font-mono-alt text-[11px] uppercase tracking-[0.2em] text-slate-500">
                        Product
                      </div>
                      <div className="mt-1 truncate text-sm text-slate-200">{row.product}</div>
                    </div>
                    <div className="rounded-xl border border-blue-400/15 bg-blue-500/10 px-3 py-2 text-right">
                      <div className="font-mono-alt text-[10px] uppercase tracking-[0.2em] text-blue-200/80">
                        HSN
                      </div>
                      <div className="font-mono-alt text-sm text-blue-300">{row.hsn}</div>
                    </div>
                    <div className="rounded-xl border border-emerald-400/10 bg-emerald-400/5 px-3 py-2 text-right">
                      <div className="font-mono-alt text-[10px] uppercase tracking-[0.2em] text-emerald-200/70">
                        GST
                      </div>
                      <div className="font-mono-alt text-sm text-emerald-300">{row.gst}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-6 rounded-2xl border border-white/8 bg-white/[0.03] p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono-alt text-[11px] uppercase tracking-[0.22em] text-slate-500">
                    Processing progress
                  </span>
                  <span className="font-mono-alt text-xs text-slate-300">1,247 / 1,500</span>
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/6">
                  <div className="h-full w-[83%] rounded-full bg-gradient-to-r from-blue-500 via-sky-400 to-cyan-300 shadow-[0_0_18px_rgba(56,189,248,0.45)]" />
                </div>
              </div>
            </div>
          </div>

          <div className="absolute -bottom-5 left-4 flex flex-wrap gap-3">
            {[
              "Invoice aware",
              "GST-ready export",
              "Semantic match",
            ].map((chip, index) => (
              <div
                key={chip}
                className={`rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 font-mono-alt text-[11px] uppercase tracking-[0.2em] text-slate-300 shadow-[0_8px_30px_rgba(2,6,23,0.35)] chip-float-${index + 1}`}
              >
                {chip}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto max-w-7xl px-6 pb-20 lg:px-10">
        <div className="max-w-2xl">
          <div className="font-mono-alt text-[11px] uppercase tracking-[0.3em] text-blue-300/70">
            Premium workflow
          </div>
          <h2 className="mt-4 font-display text-4xl font-black tracking-[-0.04em] text-white md:text-5xl">
            Built for India's classification edge cases.
          </h2>
          <p className="mt-4 max-w-xl text-base leading-7 text-slate-400">
            A restrained fintech surface with invoice context, trade vocabulary, and high-signal export flows.
          </p>
        </div>

        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {featureCards.map((card) => (
            <div
              key={card.title}
              className="rounded-[24px] border border-white/8 bg-white/[0.03] p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-xl transition hover:-translate-y-1 hover:border-blue-400/15"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-blue-400/15 bg-blue-500/10 font-mono-alt text-sm tracking-[0.2em] text-blue-200">
                {card.icon}
              </div>
              <h3 className="mt-6 font-display text-2xl font-bold tracking-[-0.03em] text-white">
                {card.title}
              </h3>
              <p className="mt-3 text-sm leading-7 text-slate-400">{card.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="relative z-10 mx-auto max-w-7xl px-6 pb-24 lg:px-10">
        <div className="relative overflow-hidden rounded-[32px] border border-white/10 bg-white/[0.035] p-8 shadow-[0_30px_90px_rgba(2,6,23,0.55)] md:p-12">
          <div className="absolute inset-x-[18%] mt-8 h-28 rounded-full bg-blue-500/10 blur-3xl" />
          <div className="relative flex flex-col items-start justify-between gap-8 md:flex-row md:items-center">
            <div className="max-w-2xl">
              <div className="font-mono-alt text-[11px] uppercase tracking-[0.28em] text-slate-500">
                Ready when you are
              </div>
              <h2 className="mt-4 font-display text-4xl font-black tracking-[-0.04em] text-white">
                Premium GST classification, minus the friction.
              </h2>
              <p className="mt-4 text-base leading-7 text-slate-400">
                Join Indian finance teams using HSNiq to move from spreadsheet chaos to reviewable outputs.
              </p>
            </div>

            <Link
              href="/signup"
              className="inline-flex items-center justify-center rounded-2xl border border-blue-400/20 bg-gradient-to-r from-blue-500 to-cyan-400 px-6 py-3.5 text-sm font-semibold text-white shadow-[0_18px_50px_rgba(14,165,233,0.22)] transition hover:-translate-y-0.5"
            >
              Get started free
            </Link>
          </div>
        </div>
      </section>

      <footer className="relative z-10 border-t border-white/8 px-6 py-6 lg:px-10">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
          <div className="font-mono-alt text-[11px] uppercase tracking-[0.24em]">
            HSNiq · AI-powered GST classification for India
          </div>
          <div>
            Built for modern finance teams by <span className="text-blue-300">Supra Pacific</span>
          </div>
        </div>
      </footer>
    </main>
  );
}
