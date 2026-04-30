import { NextResponse } from "next/server";

const CRAWLER_URL = (process.env.CRAWLER_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const CRAWLER_KEY = process.env.CRAWLER_API_KEY ?? "";

export async function GET() {
  try {
    const res = await fetch(`${CRAWLER_URL}/dach/jobs`, {
      headers: CRAWLER_KEY ? { "x-api-key": CRAWLER_KEY } : {},
    });
    if (!res.ok) return NextResponse.json({ jobs: [] });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ jobs: [] });
  }
}
