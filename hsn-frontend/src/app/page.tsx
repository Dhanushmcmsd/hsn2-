"use client";
import Link from "next/link";

export default function Home() {
  return (
    <main style={{
      background: "#020617",
      color: "#e2e8f0",
      fontFamily: "'Instrument Sans', sans-serif",
      minHeight: "100vh",
      overflow: "hidden",
      position: "relative",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Cabinet+Grotesk:wght@400;500;700;800;900&family=Instrument+Sans:wght@400;500;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        @keyframes blobDrift {
          0%,100%{transform:translate(0,0) scale(1)}
          50%{transform:translate(50px,35px) scale(1.08)}
        }
        @keyframes blobDrift2 {
          0%,100%{transform:translate(0,0) scale(1)}
          50%{transform:translate(-35px,-25px) scale(1.06)}
        }
        @keyframes floatA {
          0%,100%{transform:translate(0,0) rotate(-2deg)}
          40%{transform:translate(10px,-14px) rotate(2deg)}
          80%{transform:translate(-6px,8px) rotate(-1deg)}
        }
        @keyframes floatB {
          0%,100%{transform:translate(0,0)}
          50%{transform:translate(-12px,-10px) rotate(3deg)}
        }
        @keyframes floatC {
          0%,100%{transform:translate(0,0) rotate(1deg)}
          33%{transform:translate(8px,12px) rotate(-2deg)}
          66%{transform:translate(-5px,-6px) rotate(1deg)}
        }
        @keyframes wave {
          0%,100%{transform:skewX(-0.5deg) scaleY(1)}
          50%{transform:skewX(0.5deg) scaleY(1.02)}
        }
        @keyframes fadeUp {
          from{opacity:0;transform:translateY(18px)}
          to{opacity:1;transform:translateY(0)}
        }
        @keyframes fadeDown {
          from{opacity:0;transform:translateY(-10px)}
          to{opacity:1;transform:translateY(0)}
        }
        @keyframes scanLine {
          0%{top:0%;opacity:0.8}
          100%{top:100%;opacity:0.2}
        }
        @keyframes glowPulse {
          0%,100%{box-shadow:0 0 20px rgba(37,99,235,0.35)}
          50%{box-shadow:0 0 40px rgba(37,99,235,0.6)}
        }
        @keyframes countUp {
          from{opacity:0;transform:scale(0.8) translateY(6px)}
          to{opacity:1;transform:scale(1) translateY(0)}
        }
        @keyframes chipFloat1 {
          0%,100%{transform:translateY(0) rotate(-1deg)}
          50%{transform:translateY(-8px) rotate(1deg)}
        }
        @keyframes chipFloat2 {
          0%,100%{transform:translateY(0)}
          50%{transform:translateY(-12px)}
        }
        @keyframes chipFloat3 {
          0%,100%{transform:translateY(0) rotate(1deg)}
          50%{transform:translateY(-6px) rotate(-1deg)}
        }
        @keyframes flagFlow {
          0%,100%{transform:perspective(400px) rotateY(0deg) scaleX(1) skewY(0deg)}
          20%{transform:perspective(400px) rotateY(2.5deg) scaleX(0.97) skewY(0.3deg)}
          50%{transform:perspective(400px) rotateY(0.5deg) scaleX(1.01) skewY(-0.2deg)}
          75%{transform:perspective(400px) rotateY(-2deg) scaleX(0.98) skewY(0.2deg)}
        }

        .nav {
          position: fixed; top: 0; left: 0; right: 0; z-index: 100;
          height: 60px;
          display: flex; align-items: center; justify-content: space-between;
          padding: 0 2.5rem;
          border-bottom: 1px solid rgba(255,255,255,0.06);
          background: rgba(2,6,23,0.8);
          backdrop-filter: blur(20px);
          animation: fadeDown 0.7s ease both;
        }
        .nav-logo {
          display: flex; align-items: center; gap: 0.55rem;
          text-decoration: none;
        }
        .nav-logo-icon {
          width: 28px; height: 28px;
          background: linear-gradient(135deg, #2563eb, #3b82f6);
          border-radius: 8px;
          display: flex; align-items: center; justify-content: center;
          box-shadow: 0 0 16px rgba(37,99,235,0.5);
        }
        .nav-wordmark {
          font-family: 'Cabinet Grotesk', sans-serif;
          font-weight: 800; font-size: 1rem;
          color: #f8fafc; letter-spacing: -0.01em;
        }
        .btn-nav {
          font-family: 'Instrument Sans', sans-serif;
          font-size: 0.78rem; font-weight: 600;
          color: #fff;
          background: linear-gradient(135deg, #2563eb, #3b82f6);
          border: none;
          padding: 0.48rem 1.15rem;
          border-radius: 8px;
          cursor: pointer;
          text-decoration: none;
          display: inline-flex; align-items: center; gap: 0.3rem;
          box-shadow: 0 0 18px rgba(37,99,235,0.4);
          transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-nav:hover {
          transform: translateY(-1px);
          box-shadow: 0 0 30px rgba(37,99,235,0.65);
        }
        .btn-nav-ghost {
          font-family: 'Instrument Sans', sans-serif;
          font-size: 0.78rem; font-weight: 500;
          color: #64748b;
          background: transparent;
          border: none;
          text-decoration: none;
          transition: color 0.2s;
        }
        .btn-nav-ghost:hover{color:#f8fafc}
        .hero {
          position: relative; z-index: 1;
          padding: 10rem 2rem 6rem;
          max-width: 1120px; margin: 0 auto;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 4rem;
          align-items: center;
        }
        @media(max-width:768px){
          .hero{grid-template-columns:1fr;padding:8rem 1.5rem 4rem}
          .hero-right{display:none}
        }
        .eyebrow {
          font-family: 'DM Mono', monospace;
          font-size: 0.68rem; letter-spacing: 0.16em;
          text-transform: uppercase;
          color: #3b82f6;
          margin-bottom: 1.5rem;
          display: flex; align-items: center; gap: 8px;
          animation: fadeUp 0.8s 0.2s ease both;
          position: relative;
        }
        .headline {
          font-family: 'Cabinet Grotesk', sans-serif;
          font-size: clamp(2.4rem,5vw,3.8rem);
          font-weight: 900;
          line-height: 1.04;
          letter-spacing: -0.03em;
          color: #f8fafc;
          margin-bottom: 1.5rem;
          animation: fadeUp 0.8s 0.35s ease both;
        }
        .headline-accent {
          color: #3b82f6;
          text-shadow: 0 0 40px rgba(59,130,246,0.4);
        }
        .subtext {
          font-size: 0.92rem;
          color: #475569;
          line-height: 1.75;
          max-width: 440px;
          margin-bottom: 2.5rem;
          animation: fadeUp 0.8s 0.5s ease both;
        }
        .cta-row {
          display: flex; align-items: center; gap: 1rem;
          animation: fadeUp 0.8s 0.65s ease both;
        }
        .btn-cta {
          font-family: 'Instrument Sans', sans-serif;
          font-size: 0.9rem; font-weight: 600;
          color: #fff;
          background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
          border: none;
          padding: 0.85rem 2.2rem;
          border-radius: 12px;
          cursor: pointer;
          text-decoration: none;
          display: inline-flex; align-items: center; gap: 0.4rem;
          box-shadow: 0 4px 28px rgba(37,99,235,0.45), inset 0 1px 0 rgba(255,255,255,0.15);
          transition: transform 0.2s, box-shadow 0.2s;
          animation: glowPulse 3s ease-in-out infinite;
        }
        .btn-cta:hover {
          transform: translateY(-3px);
          box-shadow: 0 8px 40px rgba(37,99,235,0.65), inset 0 1px 0 rgba(255,255,255,0.2);
        }
        .btn-ghost-cta {
          font-family: 'Instrument Sans', sans-serif;
          font-size: 0.85rem; font-weight: 500;
          color: #64748b;
          background: transparent;
          border: 1px solid rgba(255,255,255,0.1);
          padding: 0.82rem 1.8rem;
          border-radius: 12px;
          text-decoration: none;
          transition: all 0.2s;
        }
        .btn-ghost-cta:hover {
          border-color: rgba(96,165,250,0.4);
          color: #f8fafc;
          background: rgba(255,255,255,0.03);
        }
        .stats-row {
          display: flex; gap: 3rem; margin-top: 4rem;
          animation: fadeUp 0.8s 0.8s ease both;
        }
        .stat-val {
          font-family: 'Cabinet Grotesk', sans-serif;
          font-size: 1.6rem; font-weight: 800;
          color: #f8fafc; display: block;
          animation: countUp 0.6s 1s ease both;
        }
        .stat-lbl {
          font-size: 0.68rem; letter-spacing: 0.08em;
          text-transform: uppercase; color: #334155;
          display: block; margin-top: 3px;
          font-family: 'DM Mono', monospace;
        }
        .stat-sep { width: 1px; background: rgba(255,255,255,0.06); align-self: stretch; }
        .glass-demo {
          background: rgba(255,255,255,0.025);
          backdrop-filter: blur(20px);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          overflow: hidden;
          animation: fadeUp 0.8s 0.5s ease both;
          position: relative;
        }
        .demo-header {
          display: flex; align-items: center; gap: 6px;
          padding: 0.75rem 1rem;
          border-bottom: 1px solid rgba(255,255,255,0.05);
          background: rgba(0,0,0,0.15);
        }
        .dot { width: 8px; height: 8px; border-radius: 50%; }
        .chip {
          display: inline-flex; align-items: center; gap: 6px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 100px;
          padding: 5px 12px;
          font-size: 0.72rem; font-family: 'DM Mono', monospace;
          color: #94a3b8;
          white-space: nowrap;
        }
        .feature-grid {
          display: grid; grid-template-columns: repeat(3, 1fr);
          gap: 1rem;
          max-width: 1120px; margin: 0 auto;
          padding: 0 2rem 6rem;
          position: relative; z-index: 1;
        }
        @media(max-width:768px){.feature-grid{grid-template-columns:1fr;padding:0 1.5rem 4rem}}
        .feature-card {
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 18px;
          padding: 1.75rem;
          position: relative; overflow: hidden;
          transition: border-color 0.3s, transform 0.3s;
          animation: fadeUp 0.6s ease both;
        }
        .feature-card::before {
          content:'';
          position:absolute;top:0;left:0;right:0;height:1px;
          background:linear-gradient(90deg,transparent,rgba(96,165,250,0.3),transparent);
        }
        .feature-card:hover {
          border-color: rgba(96,165,250,0.2);
          transform: translateY(-3px);
        }
        .feature-icon {
          width: 44px; height: 44px;
          background: rgba(37,99,235,0.12);
          border: 1px solid rgba(96,165,250,0.2);
          border-radius: 12px;
          display: flex; align-items: center; justify-content: center;
          margin-bottom: 1.25rem;
          font-size: 1.1rem;
        }
        .section-title {
          font-family: 'Cabinet Grotesk', sans-serif;
          font-size: 1.5rem; font-weight: 800;
          color: #f8fafc; letter-spacing: -0.02em;
          text-align: center; margin-bottom: 0.75rem;
        }
        .section-sub {
          font-size: 0.82rem;
          text-align: center; margin-bottom: 3rem;
          color: #475569;
        }
        .section-header {
          max-width: 1120px; margin: 0 auto;
          padding: 0 2rem 2rem;
          text-align: center;
          position: relative; z-index: 1;
        }

        /* India flag watermark — smooth flowing water-like animation */
        .india-flag-watermark {
          position: absolute;
          border-radius: 4px;
          overflow: hidden;
          pointer-events: none;
          animation: flagFlow 9s ease-in-out infinite;
        }
        .flag-stripe-saffron { background: #FF9933; }
        .flag-stripe-white   { background: #FFFFFF; position: relative; display: flex; align-items: center; justify-content: center; }
        .flag-stripe-green   { background: #138808; }
        /* Ashoka wheel dot */
        .flag-wheel-dot {
          width: 12px; height: 12px;
          border-radius: 50%;
          border: 1.5px solid rgba(0,0,128,0.5);
          flex-shrink: 0;
        }
        /* Fade edges to blend seamlessly */
        .flag-edge-mask {
          position: absolute;
          inset: 0;
        }
      `}</style>

      {/* ── Background ─────────────────────────────────────────────────── */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}>
        <div style={{
          position: "absolute", inset: 0,
          background: `
            radial-gradient(ellipse at 18% 28%, rgba(30,58,138,0.45) 0%, transparent 55%),
            radial-gradient(ellipse at 78% 68%, rgba(37,99,235,0.22) 0%, transparent 52%),
            radial-gradient(ellipse at 50% 110%, rgba(15,23,42,0.9) 0%, transparent 60%),
            #020617`,
        }} />
        <div style={{
          position: "absolute", inset: 0, opacity: 0.03,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
        }} />
        <div style={{ position:"absolute",width:700,height:700,top:-200,left:-200,borderRadius:"50%",background:"radial-gradient(circle,rgba(37,99,235,0.1) 0%,transparent 70%)",animation:"blobDrift 22s ease-in-out infinite" }} />
        <div style={{ position:"absolute",width:500,height:500,bottom:-120,right:-120,borderRadius:"50%",background:"radial-gradient(circle,rgba(96,165,250,0.07) 0%,transparent 70%)",animation:"blobDrift2 28s ease-in-out infinite" }} />

        {/* Floating icons — no flag here anymore */}
        {[
          { left:"6%",  top:"18%", size:36, anim:"floatA 22s ease-in-out infinite", delay:"0s" },
          { left:"90%", top:"12%", size:26, anim:"floatB 18s ease-in-out infinite", delay:"3s" },
          { left:"4%",  top:"68%", size:42, anim:"floatC 25s ease-in-out infinite", delay:"6s" },
          { left:"85%", top:"62%", size:32, anim:"floatA 20s ease-in-out infinite", delay:"1s" },
          { left:"48%", top:"6%",  size:28, anim:"floatB 28s ease-in-out infinite", delay:"9s" },
          { left:"15%", top:"85%", size:20, anim:"floatC 16s ease-in-out infinite", delay:"4s" },
        ].map((ic, i) => (
          <div key={i} style={{
            position:"absolute",left:ic.left,top:ic.top,
            width:ic.size,height:ic.size,
            color:"rgba(96,165,250,0.07)",
            animation:ic.anim,animationDelay:ic.delay,
            pointerEvents:"none",filter:"blur(0.4px)",
          }}>
            <svg viewBox="0 0 28 28" width={ic.size} height={ic.size}>
              {i%3===0 && (
                <g>
                  <rect x="2" y="1" width="20" height="26" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                  <line x1="6" y1="8" x2="18" y2="8" stroke="currentColor" strokeWidth="1.2"/>
                  <line x1="6" y1="12" x2="18" y2="12" stroke="currentColor" strokeWidth="1.2"/>
                  <line x1="6" y1="16" x2="14" y2="16" stroke="currentColor" strokeWidth="1.2"/>
                </g>
              )}
              {i%3===1 && (
                <text x="3" y="22" fontSize="20" fill="currentColor" fontFamily="serif" fontWeight="bold">₹</text>
              )}
              {i%3===2 && (
                <g>
                  <rect x="1" y="1" width="22" height="22" rx="1" fill="none" stroke="currentColor" strokeWidth="1.2"/>
                  {[5,9,13,17].map((ry,j) => <line key={j} x1="1" y1={ry} x2="23" y2={ry} stroke="currentColor" strokeWidth="0.7"/>)}
                  {[7,14,20].map((rx,j) => <line key={j} x1={rx} y1="1" x2={rx} y2="23" stroke="currentColor" strokeWidth="0.7"/>)}
                </g>
              )}
            </svg>
          </div>
        ))}
      </div>

      {/* ── Nav ── (no flag in nav) ─────────────────────────────────────── */}
      <nav className="nav">
        <a href="/" className="nav-logo">
          <div className="nav-logo-icon">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="8" width="3" height="7" fill="white" rx="1"/>
              <rect x="6" y="5" width="3" height="10" fill="white" rx="1"/>
              <rect x="11" y="2" width="3" height="13" fill="white" rx="1"/>
            </svg>
          </div>
          <span className="nav-wordmark">HSN<span style={{color:"#3b82f6"}}>iq</span></span>
        </a>
        <div style={{display:"flex",alignItems:"center",gap:"1.5rem"}}>
          <a href="/login" className="btn-nav-ghost">Sign in</a>
          <a href="/signup" className="btn-nav">Get started →</a>
        </div>
      </nav>

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="hero">
        {/* Left */}
        <div>
          {/* Eyebrow with subtle India flag watermark behind it */}
          <div className="eyebrow">
            {/* Flowing flag behind the eyebrow text */}
            <div style={{ position: "absolute", left: -16, top: -22, zIndex: 0, pointerEvents: "none" }}>
              <div
                className="india-flag-watermark"
                style={{ width: 200, height: 120, opacity: 0.06, filter: "blur(1.5px) saturate(0.5)" }}
              >
                <div className="flag-stripe-saffron" style={{ height: "33.33%" }} />
                <div className="flag-stripe-white" style={{ height: "33.33%" }}>
                  <div className="flag-wheel-dot" />
                </div>
                <div className="flag-stripe-green" style={{ height: "33.33%" }} />
                {/* Fade from both sides + top + bottom */}
                <div className="flag-edge-mask" style={{
                  background: "linear-gradient(90deg, rgba(2,6,23,0.95) 0%, rgba(2,6,23,0.2) 18%, rgba(2,6,23,0) 35%, rgba(2,6,23,0) 65%, rgba(2,6,23,0.2) 82%, rgba(2,6,23,0.95) 100%)"
                }} />
                <div className="flag-edge-mask" style={{
                  background: "linear-gradient(180deg, rgba(2,6,23,0.85) 0%, rgba(2,6,23,0) 25%, rgba(2,6,23,0) 75%, rgba(2,6,23,0.85) 100%)"
                }} />
              </div>
            </div>
            <div style={{width:6,height:6,borderRadius:"50%",background:"#3b82f6",boxShadow:"0 0 8px rgba(59,130,246,0.8)", position: "relative", zIndex: 1}}/>
            <span style={{ position: "relative", zIndex: 1 }}>India · GST · HSN Classification</span>
          </div>

          <h1 className="headline">
            Classify thousands<br/>
            of products into<br/>
            <span className="headline-accent">accurate HSN codes.</span>
          </h1>
          <p className="subtext">
            Upload any Excel or CSV spreadsheet. Get 8-digit HSN codes with GST rates, instantly. Built for Indian traders, distributors, and accountants.
          </p>
          <div className="cta-row">
            <a href="/signup" className="btn-cta">
              Start classifying
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h10M9 4l4 4-4 4" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </a>
            <a href="/login" className="btn-ghost-cta">Sign in</a>
          </div>
          <div className="stats-row">
            <div>
              <span className="stat-val">6,000+</span>
              <span className="stat-lbl">rows per batch</span>
            </div>
            <div className="stat-sep" />
            <div>
              <span className="stat-val">87%+</span>
              <span className="stat-lbl">accuracy</span>
            </div>
            <div className="stat-sep" />
            <div>
              <span className="stat-val">8-digit</span>
              <span className="stat-lbl">HSN precision</span>
            </div>
          </div>
        </div>

        {/* Right — animated demo */}
        <div className="hero-right">
          <div className="glass-demo">
            <div className="demo-header">
              <div className="dot" style={{background:"#ef4444"}}/>
              <div className="dot" style={{background:"#f59e0b"}}/>
              <div className="dot" style={{background:"#22c55e"}}/>
              <span style={{marginLeft:6,fontSize:"0.68rem",color:"#334155",fontFamily:"'DM Mono',monospace"}}>
                hsn-classifier · batch
              </span>
            </div>

            <div style={{position:"relative",overflow:"hidden"}}>
              <div style={{
                position:"absolute",left:0,right:0,height:"1px",
                background:"linear-gradient(90deg,transparent,rgba(96,165,250,0.6),transparent)",
                animation:"scanLine 2.5s linear infinite",
                zIndex:2,
              }}/>

              <div style={{padding:"1rem"}}>
                {[
                  { prod:"Horlicks Womens 400g", hsn:"21069099", gst:"18%", delay:"0s" },
                  { prod:"VKC Slipper Size 7",   hsn:"64021000", gst:"5%",  delay:"0.3s" },
                  { prod:"Colgate TP 200g",       hsn:"33061010", gst:"12%", delay:"0.6s" },
                  { prod:"Amul Butter 500g",       hsn:"04059000", gst:"12%", delay:"0.9s" },
                  { prod:"Aashirvaad Atta 5kg",   hsn:"11010000", gst:"5%",  delay:"1.2s" },
                ].map((row, i) => (
                  <div key={i} style={{
                    display:"grid",
                    gridTemplateColumns:"1fr auto auto",
                    gap:"0.75rem",
                    padding:"0.5rem 0.25rem",
                    borderBottom: i < 4 ? "1px solid rgba(255,255,255,0.04)" : "none",
                    alignItems:"center",
                    animation:`fadeUp 0.5s ${row.delay} ease both`,
                  }}>
                    <span style={{fontSize:"0.74rem",color:"#64748b",fontFamily:"'DM Mono',monospace",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
                      {row.prod}
                    </span>
                    <span style={{fontSize:"0.74rem",color:"#60a5fa",fontFamily:"'DM Mono',monospace",fontWeight:500}}>
                      {row.hsn}
                    </span>
                    <span style={{
                      fontSize:"0.65rem",
                      background:"rgba(96,165,250,0.1)",
                      border:"1px solid rgba(96,165,250,0.2)",
                      color:"#93c5fd",
                      padding:"2px 7px",borderRadius:100,
                      fontFamily:"'DM Mono',monospace",
                    }}>
                      GST {row.gst}
                    </span>
                  </div>
                ))}
              </div>

              <div style={{padding:"0.75rem 1rem",borderTop:"1px solid rgba(255,255,255,0.04)",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                <span style={{fontSize:"0.65rem",color:"#334155",fontFamily:"'DM Mono',monospace"}}>
                  Processed 1,247 / 1,500
                </span>
                <div style={{width:80,height:3,background:"rgba(255,255,255,0.06)",borderRadius:4,overflow:"hidden"}}>
                  <div style={{height:"100%",width:"83%",background:"linear-gradient(90deg,#2563eb,#60a5fa)",borderRadius:4,boxShadow:"0 0 8px rgba(96,165,250,0.5)"}}/>
                </div>
              </div>
            </div>
          </div>

          <div style={{display:"flex",gap:"0.5rem",justifyContent:"center",flexWrap:"wrap",marginTop:"1rem"}}>
            {[
              { label:"Toothpaste → 33061010", delay:"chipFloat1 3.5s ease-in-out infinite" },
              { label:"Biscuits → 19053100", delay:"chipFloat2 4s ease-in-out infinite 0.5s" },
              { label:"₹ GST Ready", delay:"chipFloat3 3s ease-in-out infinite 1s" },
            ].map((chip, i) => (
              <div key={i} className="chip" style={{animation:chip.delay}}>
                <div style={{width:5,height:5,borderRadius:"50%",background:"#3b82f6",boxShadow:"0 0 6px rgba(59,130,246,0.8)"}}/>
                {chip.label}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── (flag behind "India-First Design" card) ──────── */}
      <section style={{position:"relative",zIndex:1,paddingBottom:"6rem"}}>
        <div className="section-header">
          <div style={{display:"inline-flex",alignItems:"center",gap:6,background:"rgba(37,99,235,0.1)",border:"1px solid rgba(59,130,246,0.25)",borderRadius:100,padding:"4px 14px",marginBottom:"1.25rem"}}>
            <span style={{width:5,height:5,borderRadius:"50%",background:"#3b82f6",display:"block"}}/>
            <span style={{fontSize:"0.68rem",color:"#60a5fa",fontFamily:"'DM Mono',monospace",letterSpacing:"0.12em",textTransform:"uppercase"}}>
              Why HSNiq
            </span>
          </div>
          <h2 className="section-title">Everything you need for GST compliance</h2>
          <p className="section-sub">Designed for India's trade ecosystem</p>
        </div>
        <div className="feature-grid">
          {[
            { icon:"📊", title:"Bulk Excel Upload", body:"Upload your entire product catalog as .xlsx or .csv. Process thousands of items in one go, with HSN codes and GST rates for every row.", delay:"0.1s", india: false },
            { icon:"🧠", title:"AI-Powered Matching", body:"Multi-layer semantic engine understands product names, abbreviations, and local trade terms. Trained on Indian FMCG, retail, and trade invoices.", delay:"0.2s", india: false },
            { icon:"⚡", title:"Instant Classification", body:"Single product lookups return results in milliseconds. Bulk batches of 500+ rows complete in under 30 seconds with live progress feedback.", delay:"0.3s", india: false },
            { icon:"🔍", title:"8-Digit Precision", body:"Returns full 8-digit HSN codes with exact GST rates (5%, 12%, 18%, 28%). No ambiguity, no guesswork — ready for GSTR filing.", delay:"0.4s", india: false },
            { icon:"🇮🇳", title:"India-First Design", body:"Built around Indian trade vocabulary — understands VKC, TR masalas, Pavithram oil, Kerala groceries, FMCG abbreviations, and more.", delay:"0.5s", india: true },
            { icon:"💾", title:"Export Ready", body:"Download classified results as Excel or CSV instantly. Includes HSN code, matched description, GST rate, and confidence score per row.", delay:"0.6s", india: false },
          ].map((f, i) => (
            <div key={i} className="feature-card" style={{animationDelay:f.delay}}>
              {/* Subtle India flag watermark inside the India-First card only */}
              {f.india && (
                <div style={{ position: "absolute", inset: 0, zIndex: 0, overflow: "hidden", borderRadius: 18, pointerEvents: "none" }}>
                  <div
                    className="india-flag-watermark"
                    style={{
                      width: "110%", height: "110%",
                      top: "-5%", left: "-5%",
                      opacity: 0.045,
                      filter: "blur(2px) saturate(0.4)",
                      animationDuration: "11s",
                    }}
                  >
                    <div className="flag-stripe-saffron" style={{ height: "33.33%" }} />
                    <div className="flag-stripe-white" style={{ height: "33.33%" }}>
                      <div className="flag-wheel-dot" />
                    </div>
                    <div className="flag-stripe-green" style={{ height: "33.33%" }} />
                    {/* Heavy edge fading so only the middle softly glows */}
                    <div className="flag-edge-mask" style={{
                      background: "linear-gradient(90deg, rgba(2,6,23,0.92) 0%, rgba(2,6,23,0.1) 25%, rgba(2,6,23,0) 50%, rgba(2,6,23,0.1) 75%, rgba(2,6,23,0.92) 100%)"
                    }} />
                    <div className="flag-edge-mask" style={{
                      background: "linear-gradient(180deg, rgba(2,6,23,0.8) 0%, rgba(2,6,23,0) 30%, rgba(2,6,23,0) 70%, rgba(2,6,23,0.8) 100%)"
                    }} />
                  </div>
                </div>
              )}
              <div style={{ position: "relative", zIndex: 1 }}>
                <div className="feature-icon">{f.icon}</div>
                <h3 style={{fontFamily:"'Cabinet Grotesk',sans-serif",fontWeight:700,fontSize:"1rem",color:"#f8fafc",marginBottom:"0.6rem",letterSpacing:"-0.01em"}}>
                  {f.title}
                </h3>
                <p style={{fontSize:"0.8rem",color:"#475569",lineHeight:1.7,margin:0}}>
                  {f.body}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA band ───────────────────────────────────────────────────── */}
      <div style={{
        position:"relative",zIndex:1,
        maxWidth:1120,margin:"0 auto",
        padding:"0 2rem 8rem",
      }}>
        <div style={{
          background:"rgba(255,255,255,0.02)",
          border:"1px solid rgba(255,255,255,0.07)",
          borderRadius:24,
          padding:"4rem 3rem",
          textAlign:"center",
          position:"relative",overflow:"hidden",
        }}>
          <div style={{
            position:"absolute",inset:0,
            background:"radial-gradient(ellipse at center, rgba(37,99,235,0.08) 0%, transparent 65%)",
            pointerEvents:"none",
          }}/>
          <div style={{
            position:"absolute",top:0,left:0,right:0,height:1,
            background:"linear-gradient(90deg,transparent,rgba(96,165,250,0.4),transparent)",
          }}/>
          <h2 style={{fontFamily:"'Cabinet Grotesk',sans-serif",fontSize:"2rem",fontWeight:900,color:"#f8fafc",letterSpacing:"-0.025em",marginBottom:"0.75rem"}}>
            Ready to classify at scale?
          </h2>
          <p style={{fontSize:"0.88rem",color:"#475569",marginBottom:"2rem",maxWidth:400,margin:"0 auto 2rem"}}>
            Join traders and distributors using HSNiq for accurate GST filing.
          </p>
          <a href="/signup" className="btn-cta" style={{fontSize:"0.92rem",padding:"0.9rem 2.5rem"}}>
            Get started free →
          </a>
        </div>
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer style={{
        borderTop:"1px solid rgba(255,255,255,0.04)",
        padding:"1.25rem 2.5rem",
        position:"relative",zIndex:1,
        display:"flex",justifyContent:"space-between",alignItems:"center",
      }}>
        <span style={{fontSize:"0.7rem",color:"#1e293b",fontFamily:"'DM Mono',monospace"}}>
          HSNiq · AI-powered GST classification for India
        </span>
        <span style={{fontSize:"0.7rem",color:"#334155"}}>
          Built by <span style={{color:"#3b82f6"}}>DhanushRaghav</span>
        </span>
      </footer>
    </main>
  );
}
