import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const dbJobs = await prisma.dachJob.findMany({
      orderBy: { erstelltAm: "desc" },
      select: {
        id: true,
        ort: true,
        status: true,
        gefiltert: true,
        verarbeitet: true,
        fehler: true,
        erstelltAm: true,
      },
    });

    const jobs = dbJobs.map((j) => ({
      job_id: j.id,
      ort: j.ort,
      status: j.status,
      gefiltert: j.gefiltert,
      verarbeitet: j.verarbeitet,
      fehler: j.fehler,
      erstellt_am: j.erstelltAm,
    }));

    return NextResponse.json({ jobs });
  } catch {
    return NextResponse.json({ jobs: [] });
  }
}
