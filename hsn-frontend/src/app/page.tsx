import Link from "next/link";
import { BarChart3, ChevronRight } from "lucide-react";

export default function Home() {
  return (
    <main style={{
      background: "#001F54",
      color: "#F5F8F3",
      fontFamily: "'DM Sans', sans-serif",
      minHeight: "100vh",
      overflow: "hidden",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Syne:wght@600;700;800&family=DM+Mono:wght@400;500&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }

        /* ── Noise grain overlay ── */
        body::before {
          content: '';
          position: fixed;
          inset: 0;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
          pointer-events: none;
          z-index: 0;
          opacity: 0.5;
        }

        /* ── Ambient glow blobs ── */
        .blob-1 {
          position: fixed;
          width: 700px; height: 700px;
          top: -200px; left: -200px;
          background: radial-gradient(ellipse, rgba(1,128,235,0.08) 0%, transparent 65%);
          pointer-events: none;
          animation: driftA 18s ease-in-out infinite alternate;
        }
        .blob-2 {
          position: fixed;
          width: 500px; height: 500px;
          bottom: -100px; right: -100px;
          background: radial-gradient(ellipse, rgba(1,128,235,0.06) 0%, transparent 65%);
          pointer-events: none;
          animation: driftB 22s ease-in-out infinite alternate;
        }
        @keyframes driftA {
          from { transform: translate(0, 0) scale(1); }
          to   { transform: translate(60px, 40px) scale(1.08); }
        }
        @keyframes driftB {
          from { transform: translate(0, 0) scale(1); }
          to   { transform: translate(-40px, -30px) scale(1.06); }
        }

        /* ── Nav ── */
        .nav {
          position: fixed; top: 0; left: 0; right: 0; z-index: 100;
          height: 60px;
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 2.5rem;
          border-bottom: 1px solid rgba(206,221,250,0.08);
          background: rgba(0,15,40,0.7);
          backdrop-filter: blur(20px);
          animation: fadeDown 0.8s ease both;
        }
        @keyframes fadeDown {
          from { opacity: 0; transform: translateY(-10px); }
          to   { opacity: 1; transform: translateY(0); }
        }

        .nav-logo {
          display: flex; align-items: center; gap: 0.5rem;
          text-decoration: none;
        }
        .nav-logo-icon {
          width: 26px; height: 26px;
          background: linear-gradient(135deg, #0180EB, #0050aa);
          border-radius: 6px;
          display: flex; align-items: center; justify-content: center;
          box-shadow: 0 0 12px rgba(1,128,235,0.5);
        }
        .nav-wordmark {
          font-family: 'Syne', sans-serif;
          font-weight: 700; font-size: 0.9rem;
          color: #F5F8F3; letter-spacing: 0.01em;
        }
        .nav-actions {
          display: flex; align-items: center; gap: 1rem;
        }
        .nav-link {
          font-size: 0.8rem; font-weight: 500;
          color: rgba(206,221,250,0.6);
          text-decoration: none;
          transition: color 0.2s;
        }
        .nav-link:hover { color: #F5F8F3; }

        .btn-nav {
          font-family: 'DM Sans', sans-serif;
          font-size: 0.78rem; font-weight: 600;
          color: #F5F8F3;
          background: linear-gradient(135deg, #0180EB, #0050aa);
          border: none;
          padding: 0.45rem 1.1rem;
          border-radius: 5px;
          cursor: pointer;
          text-decoration: none;
          display: inline-flex; align-items: center; gap: 0.3rem;
          letter-spacing: 0.02em;
          box-shadow: 0 0 16px rgba(1,128,235,0.4);
          transition: box-shadow 0.25s, transform 0.2s;
        }
        .btn-nav:hover {
          box-shadow: 0 0 28px rgba(1,128,235,0.65);
          transform: translateY(-1px);
        }

        /* ── Hero ── */
        .hero {
          position: relative; z-index: 1;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          min-height: 100vh;
          text-align: center;
          padding: 8rem 2rem 6rem;
        }

        /* Thin horizontal rule that pulses */
        .rule {
          width: 1px; height: 80px;
          background: linear-gradient(to bottom, transparent, rgba(1,128,235,0.7), transparent);
          margin-bottom: 2.5rem;
          animation: fadeUp 1.2s 0.2s ease both, pulseLine 3s 1.4s ease-in-out infinite;
        }
        @keyframes pulseLine {
          0%, 100% { opacity: 0.5; }
          50%       { opacity: 1; }
        }

        /* Eyebrow tag */
        .eyebrow {
          font-family: 'DM Mono', monospace;
          font-size: 0.68rem; letter-spacing: 0.18em;
          text-transform: uppercase;
          color: rgba(1,128,235,0.85);
          margin-bottom: 1.75rem;
          animation: fadeUp 1s 0.4s ease both;
        }

        /* Main headline — word-by-word stagger */
        .headline {
          font-family: 'Syne', sans-serif;
          font-size: clamp(3rem, 7vw, 5.5rem);
          font-weight: 800;
          line-height: 1.02;
          letter-spacing: -0.025em;
          color: #F5F8F3;
          max-width: 800px;
          margin-bottom: 1.75rem;
        }
        .hl-w1 { display: block; animation: fadeUp 0.9s 0.5s ease both; }
        .hl-w2 { display: block; animation: fadeUp 0.9s 0.65s ease both; }
        .hl-w3 { display: block; animation: fadeUp 0.9s 0.80s ease both; color: #0180EB; text-shadow: 0 0 40px rgba(1,128,235,0.45); }

        /* Sub */
        .sub {
          font-size: 0.9rem;
          color: rgba(206,221,250,0.55);
          max-width: 360px;
          line-height: 1.75;
          margin-bottom: 3rem;
          animation: fadeUp 0.9s 0.95s ease both;
        }

        /* CTA row */
        .cta-row {
          display: flex; align-items: center; gap: 1.25rem;
          animation: fadeUp 0.9s 1.1s ease both;
        }
        .btn-primary {
          font-family: 'DM Sans', sans-serif;
          font-size: 0.85rem; font-weight: 600;
          color: #F5F8F3;
          background: linear-gradient(135deg, #0180EB, #0050aa);
          border: none;
          padding: 0.8rem 2rem;
          border-radius: 6px;
          cursor: pointer;
          text-decoration: none;
          display: inline-flex; align-items: center; gap: 0.4rem;
          letter-spacing: 0.02em;
          box-shadow: 0 0 22px rgba(1,128,235,0.45), inset 0 1px 0 rgba(255,255,255,0.12);
          transition: box-shadow 0.25s, transform 0.2s;
        }
        .btn-primary:hover {
          box-shadow: 0 0 36px rgba(1,128,235,0.7), inset 0 1px 0 rgba(255,255,255,0.15);
          transform: translateY(-2px);
        }
        .btn-ghost {
          font-family: 'DM Sans', sans-serif;
          font-size: 0.82rem; font-weight: 500;
          color: rgba(206,221,250,0.6);
          background: transparent;
          border: 1px solid rgba(206,221,250,0.18);
          padding: 0.78rem 1.75rem;
          border-radius: 6px;
          cursor: pointer;
          text-decoration: none;
          transition: border-color 0.2s, color 0.2s;
        }
        .btn-ghost:hover {
          border-color: rgba(1,128,235,0.55);
          color: #F5F8F3;
        }

        /* Stats strip */
        .stats {
          display: flex; gap: 4rem;
          margin-top: 5rem;
          animation: fadeUp 0.9s 1.3s ease both;
        }
        .stat-val {
          font-family: 'DM Mono', monospace;
          font-size: 1.5rem; font-weight: 500;
          color: #F5F8F3;
          display: block;
          letter-spacing: -0.01em;
        }
        .stat-lbl {
          font-size: 0.67rem; letter-spacing: 0.1em;
          text-transform: uppercase;
          color: rgba(206,221,250,0.35);
          display: block;
          margin-top: 4px;
        }

        /* Divider dot */
        .stat-sep {
          width: 1px;
          background: linear-gradient(to bottom, transparent, rgba(206,221,250,0.15), transparent);
          align-self: stretch;
        }

        /* Bottom scroll hint */
        .scroll-hint {
          position: absolute;
          bottom: 2.5rem;
          left: 50%;
          transform: translateX(-50%);
          display: flex; flex-direction: column; align-items: center;
          gap: 0.4rem;
          animation: fadeUp 1s 1.6s ease both;
        }
        .scroll-dot {
          width: 4px; height: 4px;
          border-radius: 50%;
          background: rgba(1,128,235,0.6);
          animation: scrollBounce 1.8s ease-in-out infinite;
        }
        .scroll-dot:nth-child(2) { animation-delay: 0.2s; }
        .scroll-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes scrollBounce {
          0%, 100% { opacity: 0.3; transform: translateY(0); }
          50%       { opacity: 1;   transform: translateY(4px); }
        }

        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* Ambient blobs */}
      <div className="blob-1" />
      <div className="blob-2" />

      {/* Nav */}
      <nav className="nav">
        <Link href="/" className="nav-logo">
          <div className="nav-logo-icon">
            <BarChart3 size={13} color="#F5F8F3" />
          </div>
          <span className="nav-wordmark">HSN Classifier</span>
        </Link>
        <div className="nav-actions">
          <Link href="/login" className="nav-link">Sign in</Link>
          <Link href="/signup" className="btn-nav">
            Get started <ChevronRight size={11} />
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="hero">
        <div className="rule" />

        <p className="eyebrow">Bulk Classification · GST Compliance · India</p>

        <h1 className="headline">
          <span className="hl-w1">Classify thousands</span>
          <span className="hl-w2">of products to</span>
          <span className="hl-w3">HSN codes.</span>
        </h1>

        <p className="sub">
          Upload any spreadsheet. Get 8-digit HSN codes with GST rates — instantly, at scale.
        </p>

        <div className="cta-row">
          <Link href="/signup" className="btn-primary">
            Start classifying <ChevronRight size={13} />
          </Link>
          <Link href="/login" className="btn-ghost">
            Sign in
          </Link>
        </div>

        <div className="stats">
          <div style={{ textAlign: "center" }}>
            <span className="stat-val">6,000+</span>
            <span className="stat-lbl">rows per batch</span>
          </div>
          <div className="stat-sep" />
          <div style={{ textAlign: "center" }}>
            <span className="stat-val">87%+</span>
            <span className="stat-lbl">confidence</span>
          </div>
          <div className="stat-sep" />
          <div style={{ textAlign: "center" }}>
            <span className="stat-val">8-digit</span>
            <span className="stat-lbl">precision</span>
          </div>
        </div>

        {/* Scroll hint */}
        <div className="scroll-hint">
          <div className="scroll-dot" />
          <div className="scroll-dot" />
          <div className="scroll-dot" />
        </div>
      </section>
    </main>
  );
}
