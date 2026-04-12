import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen bg-white">
      <nav className="flex items-center justify-between px-8 py-5 border-b border-gray-100 max-w-6xl mx-auto">
        <span className="text-xl font-semibold">HSN Classifier</span>
        <div className="flex gap-3">
          <Link href="/login" className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 transition">Log in</Link>
          <Link href="/signup" className="px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition">Get started</Link>
        </div>
      </nav>
      <section className="max-w-4xl mx-auto px-8 pt-24 pb-20 text-center">
        <span className="inline-block mb-6 px-3 py-1 text-xs font-medium bg-blue-50 text-blue-700 rounded-full border border-blue-100">
          AI-Powered GST Compliance
        </span>
        <h1 className="text-5xl font-bold tracking-tight text-gray-900 leading-tight mb-6">
          Classify any product to its{" "}
          <span className="text-blue-600">HSN code</span> instantly
        </h1>
        <p className="text-xl text-gray-500 mb-10 max-w-2xl mx-auto">
          Semantic AI + exact matching. 87%+ confidence. Built for Indian GST compliance at scale.
        </p>
        <div className="flex gap-4 justify-center flex-wrap">
          <Link href="/signup" className="px-8 py-3 bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition font-medium">
            Start for free →
          </Link>
          <Link href="/login" className="px-8 py-3 border border-gray-200 text-gray-700 rounded-lg hover:bg-gray-50 transition font-medium">
            Sign in
          </Link>
        </div>
      </section>
      <section className="max-w-5xl mx-auto px-8 pb-20 grid grid-cols-1 md:grid-cols-3 gap-6">
        {[
          { title: "Semantic Search", desc: "FAISS + sentence-transformers for fuzzy product name matching across 100s of HSN codes." },
          { title: "Bulk CSV Upload", desc: "Process 6,000+ products at once and download results as CSV — built for real GST workflows." },
          { title: "Human Review Queue", desc: "Low-confidence predictions are flagged so your team can verify and correct with one click." },
        ].map((f) => (
          <div key={f.title} className="p-6 rounded-2xl border border-gray-100 bg-gray-50">
            <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
            <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
