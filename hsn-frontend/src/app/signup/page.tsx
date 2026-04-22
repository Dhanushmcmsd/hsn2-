"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api";
import { BarChart3, ArrowRight, Eye, EyeOff } from "lucide-react";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) { setError("Password must be at least 8 characters"); return; }
    setError(""); setLoading(true);
    try {
      await authApi.register(email, password, name);
      const { access_token, refresh_token } = await authApi.login(email, password);
      localStorage.setItem("access_token", access_token);
      localStorage.setItem("refresh_token", refresh_token);
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally { setLoading(false); }
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, #060b18 0%, #0a1224 50%, #060d1f 100%)",
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
          background: rgba(6, 11, 24, 0.8);
          border: 1px solid #1a2840;
          color: #c8d4e8;
          padding: 0.7rem 1rem;
          border-radius: 7px;
          font-size: 0.875rem;
          font-family: 'DM Sans', sans-serif;
          outline: none;
          transition: border-color 0.2s, box-shadow 0.2s;
          box-sizing: border-box;
        }
        .auth-input::placeholder { color: #2e4060; }
        .auth-input:focus { border-color: #2d4a7a; box-shadow: 0 0 0 3px rgba(45,74,122,0.15); }
        .btn-submit {
          width: 100%;
          background: linear-gradient(135deg, #1e3a6e 0%, #2d5aa0 100%);
          color: #a8c4f0;
          border: 1px solid #2d4a7a;
          padding: 0.75rem;
          border-radius: 7px;
          font-size: 0.875rem;
          font-weight: 600;
          cursor: pointer;
          font-family: 'DM Sans', sans-serif;
          display: flex; align-items: center; justify-content: center; gap: 0.5rem;
          transition: all 0.2s; letter-spacing: 0.02em;
        }
        .btn-submit:hover:not(:disabled) {
          background: linear-gradient(135deg, #243f77 0%, #3463ae 100%);
          color: #c8d8f8; box-shadow: 0 0 20px rgba(45,90,160,0.3);
        }
        .btn-submit:disabled { opacity: 0.5; cursor: not-allowed; }
        label { display: block; font-size: 0.78rem; font-weight: 500; color: #5a7a9a; margin-bottom: 0.5rem; letter-spacing: 0.03em; text-transform: uppercase; }
      `}</style>

      <div style={{ width: "100%", maxWidth: 420 }}>
        {/* Logo */}
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}>
            <div style={{ width: 30, height: 30, background: "linear-gradient(135deg, #1e3a6e, #3d6db5)", borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <BarChart3 size={15} color="#8ab4e8" />
            </div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: "1rem", color: "#c8d4e8" }}>HSN Classifier</span>
          </div>
        </div>

        {/* Card */}
        <div style={{
          background: "rgba(10, 16, 30, 0.95)",
          border: "1px solid #1a2840",
          borderRadius: 12,
          padding: "2.25rem",
          position: "relative",
          overflow: "hidden",
        }}>
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(90,140,230,0.4), transparent)" }} />

          <h1 style={{ fontFamily: "'Syne', sans-serif", fontSize: "1.5rem", fontWeight: 700, color: "#c8d4e8", marginBottom: "0.375rem" }}>
            Create your account
          </h1>
          <p style={{ fontSize: "0.8rem", color: "#3a5070", marginBottom: "1.875rem" }}>
            Start classifying products to HSN codes
          </p>

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.125rem" }}>
            <div>
              <label>Full name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="auth-input"
                placeholder="Your name"
              />
            </div>
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
                  placeholder="Min. 8 characters"
                  style={{ paddingRight: "2.5rem" }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{ position: "absolute", right: "0.75rem", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "#3a5070", padding: 0 }}
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>

            {error && (
              <div style={{ background: "rgba(184,64,64,0.1)", border: "1px solid rgba(184,64,64,0.3)", color: "#c47070", fontSize: "0.8rem", padding: "0.625rem 0.875rem", borderRadius: 6 }}>
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-submit">
              {loading ? "Creating account…" : (<>Create account <ArrowRight size={14} /></>)}
            </button>
          </form>

          <p style={{ marginTop: "1.5rem", textAlign: "center", fontSize: "0.8rem", color: "#3a5070" }}>
            Already have an account?{" "}
            <Link href="/login" style={{ color: "#5b8fe8", textDecoration: "none", fontWeight: 500 }}>
              Sign in
            </Link>
          </p>
        </div>

        <p style={{ textAlign: "center", fontSize: "0.72rem", color: "#243040", marginTop: "1.5rem" }}>
          Developer: <span style={{ color: "#5a6a50" }}>DhanushRaghav</span>
        </p>
      </div>
    </div>
  );
}
