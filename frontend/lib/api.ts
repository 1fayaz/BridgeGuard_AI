const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const TOKEN = process.env.NEXT_PUBLIC_DEMO_TOKEN;

const headers = () => ({
  "Content-Type": "application/json",
  "Authorization": `Bearer ${TOKEN}`,
});

export async function getBridges() {
  const res = await fetch(`${BASE_URL}/v1/bridges`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch bridges");
  return res.json();
}

export async function getBridgeDetail(id: string) {
  const res = await fetch(`${BASE_URL}/v1/bridges/${id}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch bridge");
  return res.json();
}

export async function getBridgeRisk(id: string) {
  const res = await fetch(`${BASE_URL}/v1/bridges/${id}/risk`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch risk");
  return res.json();
}

export async function getBridgeAlerts(id: string) {
  const res = await fetch(`${BASE_URL}/v1/bridges/${id}/alerts`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return res.json();
}

export async function generateReport(id: string) {
  const res = await fetch(`${BASE_URL}/v1/bridges/${id}/reports`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to generate report");
  return res.json();
}