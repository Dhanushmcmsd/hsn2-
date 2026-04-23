"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi, authStorage } from "@/lib/api";
import { BarChart3, ArrowRight, Eye, EyeOff } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const { access_token, refresh_token } = await authApi.login(email, password);
      authStorage.setTokens(access_token, refresh_token, rememberMe);
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally { setLoading(false); }
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "#001F54",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "2rem",
      fontFamily: "'DM Sans', sans-serif",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=Syne:wght@600;700;800&family=DM+Mono:wght@400;500&display=swap');
        .auth-input {
          width: 100%;
          background: rgba(0,31,84,0.7);
          border: 1px solid #CEDDFA33;
          color: #F5F8F3;
          padding: 0.7rem 1rem;
          border-radius: 7px;
          font-size: 0.875rem;
          font-family: 'DM Sans', sans-serif;
          outline: none;
          transition: border-color 0.2s, box-shadow 0.2s;
          box-sizing: border-box;
        }
        .auth-input::placeholder { color: #CEDDFA44; }
        .auth-input:focus {
          border-color: #0180EB;
          box-shadow: 0 0 0 3px rgba(1,128,235,0.2), 0 0 14px rgba(1,128,235,0.15);
        }
        .btn-submit {
          width: 100%;
          background: linear-gradient(135deg, #0180EB 0%, #0a60c0 100%);
          color: #F5F8F3;
          border: 1px solid #0180EB;
          padding: 0.75rem;
          border-radius: 7px;
          font-size: 0.875rem;
          font-weight: 600;
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.5rem;
          transition: all 0.2s;
          letter-spacing: 0.02em;
          box-shadow: 0 0 18px rgba(1,128,235,0.4), inset 0 1px 0 rgba(245,248,243,0.15);
        }
        .btn-submit:hover:not(:disabled) {
          background: linear-gradient(135deg, #1a90ff 0%, #0070d0 100%);
          box-shadow: 0 0 26px rgba(1,128,235,0.6), inset 0 1px 0 rgba(245,248,243,0.2);
          transform: translateY(-1px);
        }
        .btn-submit:disabled { opacity: 0.5; cursor: not-allowed; box-shadow: none; }
        label { display: block; font-size: 0.78rem; font-weight: 500; color: #CEDDFA88; margin-bottom: 0.5rem; letter-spacing: 0.03em; text-transform: uppercase; }
        .remember-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          margin-top: -0.1rem;
        }
        .remember-toggle {
          display: inline-flex;
          align-items: center;
          gap: 0.6rem;
          font-size: 0.82rem;
          color: #CEDDFAAA;
          cursor: pointer;
          user-select: none;
        }
        .remember-toggle input {
          width: 15px;
          height: 15px;
          accent-color: #0180EB;
          cursor: pointer;
        }
        .remember-hint {
          font-size: 0.72rem;
          color: #CEDDFA55;
          text-align: right;
        }
      `}</style>

      <div style={{ width: "100%", maxWidth: 420 }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
            <div style={{ width: 30, height: 30, background: "linear-gradient(135deg, #0180EB, #0a60c0)", borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 14px rgba(1,128,235,0.5)" }}>
              <BarChart3 size={15} color="#F5F8F3" />
            </div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "1rem", color: "#F5F8F3" }}>HSN Classifier</span>
          </div>
        </div>

        {/* Card */}
        <div style={{
          background: "rgba(0,25,65,0.95)",
          border: "1px solid #CEDDFA22",
          borderRadius: 12,
          padding: "2.25rem",
          position: "relative",
          overflow: "hidden",
          backdropFilter: "blur(12px)",
          boxShadow: "0 4px 40px rgba(1,128,235,0.1), 0 1px 0 rgba(206,221,250,0.05) inset",
        }}>
          <div style={{
            position: "absolute", top: 0, left: 0, right: 0, height: 1,
            background: "linear-gradient(90deg, transparent, rgba(1,128,235,0.6), transparent)",
          }} />

          <h1 style={{ fontFamily: "'Syne', sans-serif", fontSize: "1.5rem", fontWeight: 700, color: "#F5F8F3", marginBottom: "0.375rem" }}>
            Welcome back
          </h1>
          <p style={{ fontSize: "0.8rem", color: "#CEDDFA55", marginBottom: "1.875rem" }}>
            Sign in to your HSN Classifier account
          </p>

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.125rem" }}>
            <div>
              <label>Email address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="auth-input"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label>Password</label>
              <div style={{ position: "relative" }}>
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="auth-input"
                  placeholder="••••••••"
                  style={{ paddingRight: "2.5rem" }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{ position: "absolute", right: "0.75rem", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "#CEDDFA55", padding: 0, transition: "color 0.2s" }}
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>

            <div className="remember-row">
              <label className="remember-toggle" style={{ marginBottom: 0, textTransform: "none", letterSpacing: 0 }}>
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                />
                Remember me
              </label>
              <span className="remember-hint">
                {rememberMe ? "Keeps you signed in on this device" : "Signs out when this tab closes"}
              </span>
            </div>

            {error && (
              <div style={{ background: "rgba(0,31,84,0.8)", border: "1px solid rgba(1,128,235,0.3)", color: "#CEDDFA", fontSize: "0.8rem", padding: "0.625rem 0.875rem", borderRadius: 6 }}>
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-submit">
              {loading ? "Signing in…" : (<>Sign in <ArrowRight size={14} /></>)}
            </button>
          </form>

          <p style={{ marginTop: "1.5rem", textAlign: "center", fontSize: "0.8rem", color: "#CEDDFA55" }}>
            No account?{" "}
            <Link href="/signup" style={{ color: "#0180EB", textDecoration: "none", fontWeight: 500, textShadow: "0 0 8px rgba(1,128,235,0.4)" }}>
              Create one
            </Link>
          </p>
        </div>

        {/* Footer credit */}
        <p style={{ textAlign: "center", fontSize: "0.72rem", color: "#CEDDFA33", marginTop: "1.5rem" }}>
          Developer: <span style={{ color: "#0180EB88" }}>DhanushRaghav</span>
        </p>
      </div>
    </div>
  );
}
