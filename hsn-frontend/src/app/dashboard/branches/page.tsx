"use client";

import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const fetcher = async (url: string) => {
  const token = localStorage.getItem("access_token") || sessionStorage.getItem("access_token");
  const res = await fetch(`${API_URL}${url}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

export default function BranchesDashboardPage() {
  const { data, error, isLoading } = useSWR("/analytics/branches/compare", fetcher);
  if (isLoading) return <div className="p-6 animate-pulse">Loading branches...</div>;
  if (error) return <div className="p-6 text-red-500">You do not have permission to view this page</div>;
  const rows = [...(data || [])].sort((a, b) => b.predictions_30d - a.predictions_30d);
  return (
    <main className="p-6">
      <h1 className="text-2xl font-bold mb-4">Branch Comparison</h1>
      <table className="w-full border border-slate-200 text-sm">
        <thead className="bg-slate-100">
          <tr>
            <th className="p-2 text-left">Name</th>
            <th className="p-2 text-left">City</th>
            <th className="p-2 text-right">Predictions This Month</th>
            <th className="p-2 text-right">Avg Confidence</th>
            <th className="p-2 text-right">Pending Reviews</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any, i: number) => (
            <tr key={i} className="border-t border-slate-200">
              <td className="p-2">{r.branch_name}</td>
              <td className="p-2">{r.city || "-"}</td>
              <td className="p-2 text-right">{r.predictions_30d}</td>
              <td className="p-2 text-right">{Number(r.avg_confidence || 0).toFixed(2)}</td>
              <td className="p-2 text-right">{r.pending_reviews}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
