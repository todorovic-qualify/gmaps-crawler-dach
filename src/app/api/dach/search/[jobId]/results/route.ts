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
    const res = await fetch(`${CRAWLER_URL}/dach/ergebnisse/${jobId}`, {
      headers: CRAWLER_KEY ? { "x-api-key": CRAWLER_KEY } : {},
    });

    if (res.ok) {
      const data = await res.json();
      const leads: Record<string, unknown>[] = data.leads ?? [];

      if (leads.length > 0) {
        await Promise.all(
          leads.map((l) =>
            prisma.dachLead.upsert({
              where: { jobId_osmId: { jobId, osmId: String(l.osm_id ?? "") } },
              update: {},
              create: {
                jobId,
                osmId: String(l.osm_id ?? ""),
                name: String(l.name ?? "") || null,
                operator: String(l.operator ?? "") || null,
                brand: String(l.brand ?? "") || null,
                gebaeudeTyp: String(l.gebaeude_typ ?? "") || null,
                gebaeudeNutzung: String(l.gebaeude_nutzung ?? "") || null,
                dachflaecheQm: Number(l.dachflaeche_qm ?? 0),
                adresse: String(l.adresse ?? "") || null,
                postleitzahl: String(l.postleitzahl ?? "") || null,
                stadt: String(l.stadt ?? "") || null,
                telefon: String(l.telefon ?? "") || null,
                email: String(l.email ?? "") || null,
                alleEmails: String(l.alle_emails ?? "") || null,
                alleTelefone: String(l.alle_telefone ?? "") || null,
                webseite: String(l.webseite ?? "") || null,
                entscheidungstraeger: String(l.entscheidungstraeger ?? "") || null,
                rechtlicherName: String(l.rechtlicher_name ?? "") || null,
                impressumInfo: String(l.impressum_info ?? "") || null,
                quelleUrl: String(l.quelle_url ?? "") || null,
                googleMapsUrl: String(l.google_maps_url ?? "") || null,
                kontaktVorhanden: Boolean(l.kontakt_vorhanden),
                hatPvAnlage: String(l.hat_pv_anlage ?? "") || null,
                lat: l.lat != null ? Number(l.lat) : null,
                lon: l.lon != null ? Number(l.lon) : null,
              },
            })
          )
        );

        await prisma.dachJob.updateMany({
          where: { id: jobId },
          data: { status: "abgeschlossen", verarbeitet: leads.length },
        });
      }

      return NextResponse.json(data);
    }

    // Crawler nicht verfügbar → aus DB laden
    const dbLeads = await prisma.dachLead.findMany({
      where: { jobId },
      orderBy: { dachflaecheQm: "desc" },
    });

    if (dbLeads.length === 0) {
      return NextResponse.json({ error: "Job nicht gefunden" }, { status: 404 });
    }

    return NextResponse.json({
      job_id: jobId,
      anzahl: dbLeads.length,
      leads: dbLeads.map((l) => ({
        osm_id: l.osmId,
        name: l.name ?? "",
        operator: l.operator ?? "",
        brand: l.brand ?? "",
        gebaeude_typ: l.gebaeudeTyp ?? "",
        gebaeude_nutzung: l.gebaeudeNutzung ?? "",
        dachflaeche_qm: l.dachflaecheQm,
        adresse: l.adresse ?? "",
        postleitzahl: l.postleitzahl ?? "",
        stadt: l.stadt ?? "",
        telefon: l.telefon ?? "",
        email: l.email ?? "",
        alle_emails: l.alleEmails ?? "",
        alle_telefone: l.alleTelefone ?? "",
        webseite: l.webseite ?? "",
        entscheidungstraeger: l.entscheidungstraeger ?? "",
        rechtlicher_name: l.rechtlicherName ?? "",
        impressum_info: l.impressumInfo ?? "",
        quelle_url: l.quelleUrl ?? "",
        google_maps_url: l.googleMapsUrl ?? "",
        kontakt_vorhanden: l.kontaktVorhanden,
        hat_pv_anlage: l.hatPvAnlage ?? "",
        lat: l.lat,
        lon: l.lon,
      })),
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 503 });
  }
}
