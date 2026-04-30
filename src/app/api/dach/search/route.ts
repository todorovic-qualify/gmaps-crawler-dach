import { NextRequest, NextResponse } from "next/server";

const CRAWLER_URL = (process.env.CRAWLER_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const CRAWLER_KEY = process.env.CRAWLER_API_KEY ?? "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const {
    ort,
    radius_km = 10,
    min_flaeche_qm = 500,
    max_ergebnisse = 200,
    enrichment = true,
    nur_mit_kontakt = false,
    lat,
    lon,
  } = body;

  if (!ort?.trim()) {
    return NextResponse.json({ error: "Ort fehlt" }, { status: 400 });
  }

  try {
    const res = await fetch(`${CRAWLER_URL}/dach/starten`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(CRAWLER_KEY ? { "x-api-key": CRAWLER_KEY } : {}),
      },
      body: JSON.stringify({
        ort,
        radius_km,
        min_flaeche_qm,
        max_ergebnisse,
        enrichment,
        nur_mit_kontakt,
        ...(lat != null ? { lat } : {}),
        ...(lon != null ? { lon } : {}),
      }),
    });

    if (!res.ok) {
      const txt = await res.text();
      return NextResponse.json({ error: `Crawler-Fehler: ${txt}` }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json({ jobId: data.job_id, status: data.status });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: `Verbindung zum Crawler fehlgeschlagen: ${msg}` }, { status: 503 });
  }
}
