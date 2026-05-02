"use client";

import { useState, useEffect, useRef, Fragment } from "react";
import { KATEGORIEN } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

type JobStatus = "idle" | "laeuft" | "abgeschlossen" | "fehler";

interface JobInfo {
  jobId: string;
  status: JobStatus;
  gefunden: number;
  verarbeitet: number;
  fehler?: string;
  anzahlNeu?: number;
  anzahlWiederverwendet?: number;
  anzahlAktualisiert?: number;
  uebersprungen?: number;
}

interface Lead {
  id: string;
  name: string;
  kategorie?: string | null;
  stadt?: string | null;
  adresse?: string | null;
  telefon?: string | null;
  email?: string | null;
  webseite?: string | null;
  bewertung?: number | null;
  leadScore: number;
  leadTemperatur: "HEISS" | "WARM" | "KALT";
  webseiteBedarfScore: number;
  automationBedarfScore: number;
  hatWebseite: boolean;
  hatEmail: boolean;
  wahrscheinlicheSchmerzpunkte?: string | null;
  empfohleneAngebote?: string | null;
  erstesKontaktnachricht?: string | null;
  oeffnungszeiten?: string | null;
  // Neu: Herkunft aus Junction-Tabelle
  herkunft?: "neu" | "wiederverwendet" | "aktualisiert" | null;
  crawlStatus?: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function tempBadge(t: Lead["leadTemperatur"]) {
  const styles: Record<string, string> = {
    HEISS: "bg-red-100 text-red-700 font-bold",
    WARM: "bg-orange-100 text-orange-700 font-semibold",
    KALT: "bg-slate-100 text-slate-500",
  };
  const labels: Record<string, string> = { HEISS: "🔥 Heiß", WARM: "☀️ Warm", KALT: "❄️ Kalt" };
  return (
    <span className={`px-2 py-0.5 rounded text-xs ${styles[t]}`}>
      {labels[t]}
    </span>
  );
}

function herkunftBadge(h?: string | null) {
  if (!h) return null;
  const cfg: Record<string, { label: string; cls: string }> = {
    neu:            { label: "Neu",            cls: "bg-green-100 text-green-700" },
    wiederverwendet:{ label: "Wiederverwendet",cls: "bg-blue-100 text-blue-600" },
    aktualisiert:   { label: "Aktualisiert",   cls: "bg-yellow-100 text-yellow-700" },
  };
  const c = cfg[h];
  if (!c) return null;
  return <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${c.cls}`}>{c.label}</span>;
}

function exportCSV(leads: Lead[]) {
  const cols = [
    "name", "kategorie", "stadt", "telefon", "email", "webseite",
    "leadScore", "leadTemperatur", "webseiteBedarfScore", "automationBedarfScore",
    "hatWebseite", "hatEmail", "wahrscheinlicheSchmerzpunkte", "empfohleneAngebote",
    "erstesKontaktnachricht",
  ] as const;

  const header = cols.join(";");
  const rows = leads.map((l) =>
    cols.map((c) => {
      const v = l[c as keyof Lead] ?? "";
      return `"${String(v).replace(/"/g, '""')}"`;
    }).join(";")
  );

  const blob = new Blob(["\uFEFF" + [header, ...rows].join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `leads_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function StartSeite() {
  const [ort, setOrt] = useState("");
  const [radius, setRadius] = useState(10);
  const [maxErgebnisse, setMaxErgebnisse] = useState(50);
  const [gewählteKats, setGewählteKats] = useState<string[]>([]);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [fehler, setFehler] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Stop polling on unmount
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  function toggleKat(wert: string) {
    setGewählteKats((prev) =>
      prev.includes(wert) ? prev.filter((k) => k !== wert) : [...prev, wert]
    );
  }

  async function starteSuche(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    setLeads([]);
    setJob(null);

    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ort,
        radius_km: radius,
        kategorien: gewählteKats,
        max_ergebnisse: maxErgebnisse,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      setFehler(data.error ?? "Unbekannter Fehler");
      return;
    }

    const jobId: string = data.jobId;
    setJob({ jobId, status: "laeuft", gefunden: 0, verarbeitet: 0 });

    // Poll status every 3s
    pollRef.current = setInterval(async () => {
      try {
        const sr = await fetch(`/api/search/${jobId}/status`);
        const sd = await sr.json();

        if (!sr.ok) {
          // Don't stop polling on transient errors, just log
          console.warn("Status-Fehler:", sd);
          return;
        }

        setJob({
          jobId,
          status: sd.status ?? "laeuft",
          gefunden: sd.gefunden ?? 0,
          verarbeitet: sd.verarbeitet ?? 0,
          fehler: sd.fehler,
          anzahlNeu: sd.anzahl_neu ?? 0,
          anzahlWiederverwendet: sd.anzahl_wiederverwendet ?? 0,
          anzahlAktualisiert: sd.anzahl_aktualisiert ?? 0,
          uebersprungen: sd.uebersprungen ?? 0,
        });

        if (sd.status === "abgeschlossen" || sd.status === "fehler") {
          clearInterval(pollRef.current!);

          if (sd.status === "abgeschlossen") {
            const rr = await fetch(`/api/search/${jobId}/results`);
            const rd = await rr.json();
            if (!rr.ok) {
              setFehler(`Ergebnisse konnten nicht geladen werden: ${rd.error ?? rr.status}`);
            } else {
              setLeads(rd.leads ?? []);
            }
          } else {
            setFehler(sd.fehler ?? "Crawler-Fehler");
          }
        }
      } catch (err) {
        console.warn("Polling-Fehler:", err);
      }
    }, 3000);
  }

  const isRunning = job?.status === "laeuft";

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Lokale Leads finden</h1>
        <p className="text-slate-500 mt-1">Suche + Bewertung lokaler Unternehmen als Verkaufschancen</p>
      </div>

      {/* ── Form ── */}
      <form onSubmit={starteSuche} className="bg-white rounded-xl border border-slate-200 p-6 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="sm:col-span-1">
            <label className="block text-sm font-medium text-slate-700 mb-1">Ort</label>
            <input
              required
              value={ort}
              onChange={(e) => setOrt(e.target.value)}
              placeholder="z.B. München"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Radius (km)</label>
            <input
              type="number"
              min={1}
              max={100}
              value={radius}
              onChange={(e) => setRadius(Number(e.target.value))}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Max. Ergebnisse</label>
            <input
              type="number"
              min={3}
              max={500}
              step={1}
              value={maxErgebnisse}
              onChange={(e) => setMaxErgebnisse(Number(e.target.value))}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Category checkboxes */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-slate-700">
              Kategorien{" "}
              <span className="text-slate-400 font-normal">
                ({gewählteKats.length === 0 ? "alle" : `${gewählteKats.length} gewählt`})
              </span>
            </label>
            <button
              type="button"
              onClick={() => setGewählteKats([])}
              className="text-xs text-slate-400 hover:text-slate-600"
            >
              Alle deaktivieren
            </button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 max-h-48 overflow-y-auto pr-1">
            {KATEGORIEN.map((k) => (
              <label key={k.wert} className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={gewählteKats.includes(k.wert)}
                  onChange={() => toggleKat(k.wert)}
                  className="rounded"
                />
                <span className="text-slate-700">{k.label}</span>
              </label>
            ))}
          </div>
        </div>

        <button
          type="submit"
          disabled={isRunning}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium px-6 py-2.5 rounded-lg text-sm transition-colors"
        >
          {isRunning ? "Läuft…" : "Suche starten"}
        </button>
      </form>

      {/* ── Error ── */}
      {fehler && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          {fehler}
        </div>
      )}

      {/* ── Progress ── */}
      {job && job.status === "laeuft" && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4">
          <div className="flex items-center gap-3">
            <svg className="animate-spin h-5 w-5 text-blue-600" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 100 16v-4l-3 3 3 3v-4a8 8 0 01-8-8z" />
            </svg>
            <div>
              <p className="text-sm font-medium text-blue-800">Crawler läuft…</p>
              <p className="text-xs text-blue-600 mt-0.5">
                {job.gefunden > 0
                  ? `${job.gefunden} gefunden · ${job.verarbeitet} verarbeitet`
                    + (job.uebersprungen ? ` · ${job.uebersprungen} Re-Crawls übersprungen` : "")
                  : "Suche läuft…"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Results ── */}
      {leads.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                {leads.length} Leads gefunden
              </h2>
              {job && (
                <p className="text-xs text-slate-500 mt-0.5">
                  {job.anzahlNeu ? <span className="text-green-700 font-medium">{job.anzahlNeu} neu</span> : null}
                  {job.anzahlWiederverwendet ? <span className="text-blue-700 font-medium">{job.anzahlNeu ? " · " : ""}{job.anzahlWiederverwendet} wiederverwendet</span> : null}
                  {job.anzahlAktualisiert ? <span className="text-yellow-700 font-medium">{(job.anzahlNeu || job.anzahlWiederverwendet) ? " · " : ""}{job.anzahlAktualisiert} aktualisiert</span> : null}
                </p>
              )}
            </div>
            <div className="flex gap-2">
            <a
              href="/leads"
              className="text-sm bg-blue-50 hover:bg-blue-100 text-blue-700 px-4 py-2 rounded-lg transition-colors"
            >
              Alle Leads ansehen
            </a>
            <button
              onClick={() => exportCSV(leads)}
              className="text-sm bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg transition-colors"
            >
              ↓ CSV exportieren
            </button>
            </div>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  {["Unternehmen", "Stadt", "Kategorie", "Score", "Temp.", "Status", "Website", "Email", "Telefon", "Details"].map((h) => (
                    <th key={h} className="text-left px-3 py-2.5 font-medium text-slate-600 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {leads.map((lead) => (
                  <Fragment key={lead.id}>
                    <tr
                      className="hover:bg-slate-50 cursor-pointer"
                      onClick={() => setExpandedId(expandedId === lead.id ? null : lead.id)}
                    >
                      <td className="px-3 py-2.5 font-medium text-slate-900 max-w-[180px] truncate">
                        {lead.name}
                      </td>
                      <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                        {lead.stadt ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                        {lead.kategorie ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 font-bold text-slate-900 whitespace-nowrap">
                        {lead.leadScore}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {tempBadge(lead.leadTemperatur)}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {herkunftBadge(lead.herkunft ?? lead.crawlStatus)}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {lead.hatWebseite && lead.webseite ? (
                          <a
                            href={lead.webseite}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-blue-600 hover:underline truncate max-w-[120px] block"
                          >
                            {lead.webseite.replace(/^https?:\/\//, "").slice(0, 30)}
                          </a>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {lead.email ? (
                          <a
                            href={`mailto:${lead.email}`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-blue-600 hover:underline"
                          >
                            {lead.email.slice(0, 28)}
                          </a>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap">
                        {lead.telefon ?? <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-3 py-2.5 text-slate-400 text-xs whitespace-nowrap">
                        {expandedId === lead.id ? "▲ schließen" : "▼ mehr"}
                      </td>
                    </tr>

                    {expandedId === lead.id && (
                      <tr className="bg-slate-50">
                        <td colSpan={10} className="px-4 py-3">
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1">Schmerzpunkte</p>
                              <p className="text-slate-700">{lead.wahrscheinlicheSchmerzpunkte ?? "—"}</p>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1">Empfohlene Angebote</p>
                              <p className="text-slate-700">{lead.empfohleneAngebote ?? "—"}</p>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1">Erstkontakt-Nachricht</p>
                              <p className="text-slate-700 whitespace-pre-wrap">{lead.erstesKontaktnachricht ?? "—"}</p>
                            </div>
                          </div>
                          {lead.oeffnungszeiten && (
                            <div className="mt-2 pt-2 border-t border-slate-200 text-xs">
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1">Öffnungszeiten</p>
                              <p className="text-slate-700 font-mono">{lead.oeffnungszeiten}</p>
                            </div>
                          )}
                          <div className="flex gap-4 mt-2 text-xs text-slate-500">
                            <span>Website-Bedarf: <strong>{lead.webseiteBedarfScore}</strong></span>
                            <span>Automation-Bedarf: <strong>{lead.automationBedarfScore}</strong></span>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state after job done */}
      {job?.status === "abgeschlossen" && leads.length === 0 && (
        <div className="text-center py-12 text-slate-400">
          Keine Leads gefunden. Anderen Ort oder Radius versuchen.
        </div>
      )}
    </div>
  );
}
