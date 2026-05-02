import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

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
    const data = await res.json();

    await prisma.dachJob.updateMany({
      where: { id: jobId },
      data: {
        status: data.status ?? "laeuft",
        gefiltert: data.gefiltert ?? 0,
        verarbeitet: data.verarbeitet ?? 0,
        fehler: data.fehler ?? null,
      },
    });

    return NextResponse.json(data);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 503 });
  }
}
