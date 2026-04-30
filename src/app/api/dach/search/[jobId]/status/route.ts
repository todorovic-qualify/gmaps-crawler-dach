import { NextRequest, NextResponse } from "next/server";

const CRAWLER_URL = (process.env.CRAWLER_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const CRAWLER_KEY = process.env.CRAWLER_API_KEY ?? "";

export async function GET(
  _req: NextRequest,
  { params }: { params: { jobId: string } },
) {
  const { jobId } = params;
  try {
    const res = await fetch(`${CRAWLER_URL}/dach/status/${jobId}`, {
      headers: CRAWLER_KEY ? { "x-api-key": CRAWLER_KEY } : {},
    });
    if (!res.ok) {
      const txt = await res.text();
      return NextResponse.json({ error: txt }, { status: res.status });
    }
    return NextResponse.json(await res.json());
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 503 });
  }
}
