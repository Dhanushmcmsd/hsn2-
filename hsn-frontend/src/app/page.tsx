import Link from "next/link";
import { BarChart3, Zap, Shield, ArrowRight, FileSpreadsheet, CheckCircle2, ChevronRight } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen" style={{
      background: "linear-gradient(135deg, #060b18 0%, #0a1224 50%, #060d1f 100%)",
      color: "#c8d4e8",
      fontFamily: "'DM Sans', sans-serif",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Syne:wght@600;700;800&family=DM+Mono:wght@400;500&display=swap');
        .gold-text { color: #c8a96e; }
        .accent-text { color: #5b8fe8; }
        .nav-link { color: #7a90b0; transition: color 0.2s; text-decoration: none; font-size: 0.875rem; font-weight: 500; }
        .nav-link:hover { color: #c8d4e8; }
        .btn-primary {
          background: linear-gradient(135deg, #1e3a6e 0%, #2d5aa0 100%);
          color: #a8c4f0;
          border: 1px solid #2d4a7a;
          padding: 0.75rem 1.75rem;
          border-radius: 6px;
          font-size: 0.875rem;
          font-weight: 600;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          text-decoration: none;
          transition: all 0.2s;
          letter-spacing: 0.02em;
        }
        .btn-primary:hover {
          background: linear-gradient(135deg, #243f77 0%, #3463ae 100%);
          color: #c8d8f8;
          box-shadow: 0 0 20px rgba(45, 90, 160, 0.3);
        }
        .btn-ghost {
          background: transparent;
          color: #7a90b0;
          border: 1px solid #1c2e4a;
          padding: 0.75rem 1.75rem;
          border-radius: 6px;
          font-size: 0.875rem;
          font-weight: 500;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          text-decoration: none;
          transition: all 0.2s;
        }
        .btn-ghost:hover { border-color: #2d4a7a; color: #c8d4e8; }
        .feature-card {
          background: rgba(14, 21, 36, 0.8);
          border: 1px solid #1a2840;
          border-radius: 10px;
          padding: 1.75rem;
          transition: all 0.3s;
          position: relative;
          overflow: hidden;
        }
        .feature-card::before {
          content: '';
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 1px;
          background: linear-gradient(90deg, transparent, rgba(90, 140, 230, 0.3), transparent);
        }
        .feature-card:hover { border-color: #2d4a7a; transform: translateY(-2px); }
        .feature-card.highlight {
          border-color: #2d4a7a;
          background: rgba(20, 30, 55, 0.9);
        }
        .feature-card.highlight::before {
          background: linear-gradient(90deg, transparent, rgba(90, 140, 230, 0.6), transparent);
        }
        .stat-number { font-family: 'DM Mono', monospace; }
        .divider { border: none; border-top: 1px solid #1a2840; }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 0.375rem;
          background: rgba(45, 74, 122, 0.3);
          border: 1px solid rgba(45, 74, 122, 0.6);
          color: #7aabdf;
          padding: 0.3rem 0.75rem;
          border-radius: 100px;
          font-size: 0.75rem;
          font-weight: 600;
          letter-spacing: 0.05em;
          text-transform: uppercase;
        }
        .glow-icon {
          width: 42px; height: 42px;
          background: rgba(45, 90, 160, 0.15);
          border: 1px solid rgba(45, 90, 160, 0.3);
          border-radius: 8px;
          display: flex; align-items: center; justify-content: center;
          color: #5b8fe8;
        }
        .grid-overlay {
          position: absolute; inset: 0;
          background-image: linear-gradient(rgba(45,74,122,0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(45,74,122,0.05) 1px, transparent 1px);
          background-size: 48px 48px;
          pointer-events: none;
        }
      `}</style>

      {/* Nav */}
      <nav style={{
        borderBottom: "1px solid #111c30",
        background: "rgba(6, 11, 24, 0.95)",
        backdropFilter: "blur(12px)",
        position: "sticky", top: 0, zIndex: 50,
      }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 2rem", height: 64, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.625rem" }}>
            <div style={{ width: 28, height: 28, background: "linear-gradient(135deg, #1e3a6e, #3d6db5)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <BarChart3 size={15} color="#8ab4e8" />
            </div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "1rem", color: "#c8d4e8", letterSpacing: "0.01em" }}>
              HSN Classifier
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "2rem" }}>
            <a href="#features" className="nav-link">Features</a>
            <Link href="/login" className="nav-link">Sign in</Link>
            <Link href="/signup" className="btn-primary" style={{ padding: "0.5rem 1.25rem", fontSize: "0.8rem" }}>
              Get started <ChevronRight size={13} />
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section style={{ position: "relative", overflow: "hidden", padding: "6rem 2rem 5rem" }}>
        <div className="grid-overlay" />
        <div style={{
          position: "absolute", top: "10%", left: "50%", transform: "translateX(-50%)",
          width: 600, height: 400,
          background: "radial-gradient(ellipse, rgba(45,90,160,0.08) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />
        <div style={{ maxWidth: 820, margin: "0 auto", textAlign: "center", position: "relative" }}>
          <div style={{ marginBottom: "1.5rem" }}>
            <span className="badge"><Zap size={10} /> AI-Powered · GST Compliance</span>
          </div>
          <h1 style={{
            fontFamily: "'Syne', sans-serif",
            fontSize: "clamp(2.4rem, 5vw, 3.8rem)",
            fontWeight: 800,
            lineHeight: 1.08,
            letterSpacing: "-0.02em",
            color: "#dce8f8",
            marginBottom: "1.5rem",
          }}>
            Classify products to<br />
            <span style={{ color: "#5b8fe8" }}>HSN codes</span>{" "}
            <span className="gold-text">instantly</span>
          </h1>
          <p style={{ color: "#6b84a6", fontSize: "1.05rem", maxWidth: 540, margin: "0 auto 2.5rem", lineHeight: 1.7 }}>
            Built for Indian GST compliance at scale. Semantic AI matching with 87%+ confidence across thousands of product classifications.
          </p>
          <div style={{ display: "flex", gap: "0.875rem", justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/signup" className="btn-primary">
              Start classifying <ArrowRight size={14} />
            </Link>
            <Link href="/login" className="btn-ghost">
              Sign in
            </Link>
          </div>

          {/* Stats strip */}
          <div style={{ marginTop: "4rem", display: "flex", justifyContent: "center", gap: "3.5rem", flexWrap: "wrap" }}>
            {[
              { val: "6,000+", label: "Products per batch" },
              { val: "87%+", label: "Confidence accuracy" },
              { val: "8-digit", label: "HSN precision" },
            ].map((s) => (
              <div key={s.val} style={{ textAlign: "center" }}>
                <div className="stat-number" style={{ fontSize: "1.6rem", fontWeight: 500, color: "#c8d4e8", letterSpacing: "-0.01em" }}>{s.val}</div>
                <div style={{ fontSize: "0.75rem", color: "#4e6480", letterSpacing: "0.04em", textTransform: "uppercase", marginTop: 4 }}>{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <hr className="divider" style={{ margin: "0 2rem" }} />

      {/* Features */}
      <section id="features" style={{ padding: "5rem 2rem", maxWidth: 1100, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: "3.5rem" }}>
          <p style={{ fontSize: "0.72rem", letterSpacing: "0.12em", textTransform: "uppercase", color: "#4e6480", marginBottom: "0.75rem" }}>Capabilities</p>
          <h2 style={{ fontFamily: "'Syne', sans-serif", fontSize: "2rem", fontWeight: 700, color: "#c8d4e8", letterSpacing: "-0.01em" }}>
            Enterprise-grade classification
          </h2>
        </div>

        {/* Bulk — Hero feature */}
        <div className="feature-card highlight" style={{ marginBottom: "1.25rem", padding: "2.5rem" }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: "1.5rem", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 280 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
                <div className="glow-icon"><FileSpreadsheet size={18} /></div>
                <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "1.2rem", color: "#c8d4e8" }}>
                  Bulk Excel Classification
                </span>
                <span style={{ background: "rgba(200,169,110,0.15)", border: "1px solid rgba(200,169,110,0.35)", color: "#c8a96e", fontSize: "0.68rem", padding: "0.2rem 0.6rem", borderRadius: 100, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>Core Feature</span>
              </div>
              <p style={{ color: "#6b84a6", lineHeight: 1.7, fontSize: "0.9rem", marginBottom: "1.25rem" }}>
                Upload any .xlsx or .csv file and classify thousands of product descriptions simultaneously. Live progress tracking, downloadable results, and full GST rate mapping — built for real Indian GST workflows.
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
                {["Max 500 rows per batch", ".xlsx & .csv support", "Live progress bar", "Downloadable results", "GST rate mapping"].map((f) => (
                  <span key={f} style={{ display: "inline-flex", alignItems: "center", gap: "0.375rem", fontSize: "0.78rem", color: "#5a7a9a" }}>
                    <CheckCircle2 size={11} color="#2d7a60" /> {f}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ background: "rgba(10, 16, 30, 0.7)", border: "1px solid #1a2840", borderRadius: 8, padding: "1.25rem", minWidth: 240, fontFamily: "'DM Mono', monospace", fontSize: "0.75rem" }}>
              <div style={{ color: "#3a5070", marginBottom: "0.5rem", fontSize: "0.68rem", letterSpacing: "0.08em", textTransform: "uppercase" }}>Batch result preview</div>
              {[
                { desc: "AMUL BUTTER 500G", hsn: "04051000", conf: "97%", label: "high" },
                { desc: "VKC HAWAI SLIPPER", hsn: "64019900", conf: "94%", label: "high" },
                { desc: "HARPIC 500ML", hsn: "34029090", conf: "88%", label: "high" },
              ].map((r, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0.4rem 0", borderBottom: i < 2 ? "1px solid #0e1828" : "none", gap: "0.75rem" }}>
                  <span style={{ color: "#5a7a9a", fontSize: "0.7rem", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.desc}</span>
                  <span style={{ color: "#5b8fe8" }}>{r.hsn}</span>
                  <span style={{ color: "#2d9975", fontSize: "0.68rem" }}>{r.conf}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Other features */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.25rem" }}>
          {[
            {
              icon: <Zap size={17} />,
              title: "Single Lookup",
              desc: "Instant classification for individual product descriptions. Returns top match with alternatives, confidence score, and match methodology.",
            },
            {
              icon: <Shield size={17} />,
              title: "Human Review Queue",
              desc: "Low-confidence predictions are automatically flagged. Your team can verify and correct with a single action — maintaining audit trails.",
            },
            {
              icon: <BarChart3 size={17} />,
              title: "Semantic + Exact Matching",
              desc: "Hybrid FAISS vector search combined with exact and fuzzy text matching across verified product databases and HSN master data.",
            },
          ].map((f) => (
            <div key={f.title} className="feature-card">
              <div className="glow-icon" style={{ marginBottom: "1rem" }}>{f.icon}</div>
              <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 600, fontSize: "0.95rem", color: "#b8cce0", marginBottom: "0.625rem" }}>{f.title}</div>
              <p style={{ color: "#4e6480", fontSize: "0.82rem", lineHeight: 1.7 }}>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <hr className="divider" />

      {/* CTA */}
      <section style={{ padding: "5rem 2rem", textAlign: "center", position: "relative", overflow: "hidden" }}>
        <div style={{
          position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)",
          width: 500, height: 300,
          background: "radial-gradient(ellipse, rgba(45,90,160,0.06) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />
        <p style={{ fontSize: "0.72rem", letterSpacing: "0.12em", textTransform: "uppercase", color: "#4e6480", marginBottom: "1rem" }}>Get started today</p>
        <h2 style={{ fontFamily: "'Syne', sans-serif", fontSize: "2.2rem", fontWeight: 700, color: "#c8d4e8", marginBottom: "1.5rem", letterSpacing: "-0.01em" }}>
          Ready to automate your<br />GST compliance?
        </h2>
        <Link href="/signup" className="btn-primary">
          Start for free <ArrowRight size={14} />
        </Link>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid #111c30", padding: "1.75rem 2rem" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <div style={{ width: 20, height: 20, background: "linear-gradient(135deg, #1e3a6e, #3d6db5)", borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <BarChart3 size={10} color="#8ab4e8" />
            </div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "0.8rem", color: "#4e6480" }}>HSN Classifier</span>
          </div>
          <div style={{ display: "flex", gap: "2rem", alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: "0.75rem", color: "#3a5070" }}>
              Developer: <span style={{ color: "#c8a96e", fontWeight: 600 }}>DhanushRaghav</span>
            </span>
            <span style={{ fontSize: "0.72rem", color: "#2e3d52" }}>Built for Indian GST compliance</span>
          </div>
        </div>
      </footer>
    </main>
  );
}
