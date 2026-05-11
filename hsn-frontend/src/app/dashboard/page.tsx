"use client";

import useSWR from "swr";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const fetcher = async (url: string) => {
  const token = localStorage.getItem("access_token") || sessionStorage.getItem("access_token");
  const res = await fetch(`${API_URL}${url}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

export default function DashboardPage() {
  const { data, error, isLoading } = useSWR("/analytics/overview", fetcher);
  const { data: trend } = useSWR("/analytics/trends?period=30d", fetcher);

  if (isLoading) return <div className="p-6 animate-pulse">Loading dashboard...</div>;
  if (error) return <div className="p-6 text-red-500">You do not have permission to view this page</div>;

  const dist = Object.entries(data?.gst_rate_distribution || {}).map(([rate, count]) => ({ name: `${rate}%`, value: Number(count) }));
  const top = data?.top_5_hsn_codes?.[0];

  return (
    <main className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Analytics Dashboard</h1>
      <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card title="Total Predictions" value={data?.total_predictions_30d} />
        <Card title="Avg Confidence" value={Number(data?.avg_confidence || 0).toFixed(2)} />
        <Card title="Pending Reviews" value={data?.pending_reviews} />
        <Card title="Top HSN" value={top ? `${top.hsn_code}` : "-"} />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="border rounded-lg p-4 bg-white">
          <h2 className="font-semibold mb-2">Predictions (30 days)</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={trend || []}>
                <XAxis dataKey="date" hide />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#1d4ed8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="border rounded-lg p-4 bg-white">
          <h2 className="font-semibold mb-2">GST Rate Distribution</h2>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={dist} dataKey="value" nameKey="name" innerRadius={60} outerRadius={100}>
                  {dist.map((_, i) => (
                    <Cell key={i} fill={["#22c55e", "#0ea5e9", "#f59e0b", "#ef4444", "#8b5cf6"][i % 5]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>
    </main>
  );
}

function Card({ title, value }: { title: string; value: any }) {
  return (
    <div className="rounded-lg border bg-slate-50 p-4">
      <p className="text-sm text-slate-500">{title}</p>
      <p className="text-2xl font-bold text-slate-900">{value ?? "-"}</p>
    </div>
  );
}
