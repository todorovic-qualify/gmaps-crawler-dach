"use client";

import { useState, useEffect, useRef, Fragment } from "react";

// ── Typen ──────────────────────────────────────────────────────────────────────

type JobStatus = "idle" | "laeuft" | "abgeschlossen" | "fehler";

interface JobInfo {
  jobId: string;
  status: JobStatus;
  gefiltert: number;
  verarbeitet: number;
  fehler?: string;
}

interface DachLead {
  osm_id: string;
  name: string;
  operator: string;
  brand: string;
  gebaeude_typ: string;
  gebaeude_nutzung: string;
  dachflaeche_qm: number;
  adresse: string;
  postleitzahl: string;
  stadt: string;
  telefon: string;
  email: string;
  alle_emails: string;
  alle_telefone: string;
  webseite: string;
  entscheidungstraeger: string;
  rechtlicher_name: string;
  impressum_info: string;
  quelle_url: string;
  google_maps_url: string;
  kontakt_vorhanden: boolean;
  lat: number;
  lon: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function flaecheBadge(qm: number) {
  let cls = "bg-slate-100 text-slate-600";
  if (qm >= 2000) cls = "bg-orange-100 text-orange-700 font-bold";
  else if (qm >= 1000) cls = "bg-yellow-100 text-yellow-700 font-semibold";
  return (
    <span className={`px-2 py-0.5 rounded text-xs ${cls}`}>
      {qm.toLocaleString("de-DE", { maximumFractionDigits: 0 })} m²
    </span>
  );
}

function kontaktBadge(lead: DachLead) {
  if (lead.email || lead.alle_emails) {
    return <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-700 font-medium">E-Mail</span>;
  }
  if (lead.telefon || lead.alle_telefone) {
    return <span className="px-1.5 py-0.5 rounded text-xs bg-blue-100 text-blue-700 font-medium">Tel.</span>;
  }
  if (lead.webseite) {
    return <span className="px-1.5 py-0.5 rounded text-xs bg-purple-100 text-purple-700 font-medium">Website</span>;
  }
  return <span className="px-1.5 py-0.5 rounded text-xs bg-slate-100 text-slate-400">—</span>;
}

function anzeigeName(lead: DachLead): string {
  return lead.name || lead.operator || lead.brand || `Gebäude (${lead.gebaeude_typ || "unbekannt"})`;
}

async function kopiereText(text: string) {
  try { await navigator.clipboard.writeText(text); } catch {}
}

function exportCSV(leads: DachLead[]) {
  if (!leads.length) return;
  const cols: (keyof DachLead)[] = [
    "osm_id", "name", "operator", "brand", "gebaeude_typ", "gebaeude_nutzung",
    "dachflaeche_qm", "adresse", "postleitzahl", "stadt",
    "telefon", "email", "alle_emails", "alle_telefone", "webseite",
    "entscheidungstraeger", "rechtlicher_name", "google_maps_url", "quelle_url",
  ];
  const header = cols.join(";");
  const rows = leads.map((l) =>
    cols.map((c) => `"${String(l[c] ?? "").replace(/"/g, '""')}"`).join(";")
  );
  const blob = new Blob(["﻿" + [header, ...rows].join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `solar_dach_leads_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Hauptseite ─────────────────────────────────────────────────────────────────

export default function DachScanSeite() {
  const [ort, setOrt] = useState("");
  const [radius, setRadius] = useState(10);
  const [minFlaeche, setMinFlaeche] = useState(500);
  const [maxErgebnisse, setMaxErgebnisse] = useState(200);
  const [mitEnrichment, setMitEnrichment] = useState(true);
  const [nurMitKontakt, setNurMitKontakt] = useState(false);

  const [job, setJob] = useState<JobInfo | null>(null);
  const [leads, setLeads] = useState<DachLead[]>([]);
  const [fehler, setFehler] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filter
  const [filterKontakt, setFilterKontakt] = useState(false);
  const [filterMinFlaeche, setFilterMinFlaeche] = useState(0);
  const [filterSuche, setFilterSuche] = useState("");
  const [sortBy, setSortBy] = useState<"dachflaeche_qm" | "name" | "stadt">("dachflaeche_qm");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  async function starteScan(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);
    setLeads([]);
    setJob(null);
    setExpandedId(null);

    const res = await fetch("/api/dach/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ort,
        radius_km: radius,
        min_flaeche_qm: minFlaeche,
        max_ergebnisse: maxErgebnisse,
        enrichment: mitEnrichment,
        nur_mit_kontakt: nurMitKontakt,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      setFehler(data.error ?? "Unbekannter Fehler");
      return;
    }

    const jobId: string = data.jobId;
    setJob({ jobId, status: "laeuft", gefiltert: 0, verarbeitet: 0 });

    pollRef.current = setInterval(async () => {
      try {
        const sr = await fetch(`/api/dach/search/${jobId}/status`);
        const sd = await sr.json();

        if (!sr.ok) return;

        setJob({
          jobId,
          status: sd.status ?? "laeuft",
          gefiltert: sd.gefiltert ?? 0,
          verarbeitet: sd.verarbeitet ?? 0,
          fehler: sd.fehler,
        });

        if (sd.status === "abgeschlossen" || sd.status === "fehler") {
          clearInterval(pollRef.current!);
          if (sd.status === "abgeschlossen") {
            const rr = await fetch(`/api/dach/search/${jobId}/results`);
            const rd = await rr.json();
            if (rr.ok) setLeads(rd.leads ?? []);
            else setFehler(`Ergebnisse konnten nicht geladen werden: ${rd.error ?? rr.status}`);
          } else {
            setFehler(sd.fehler ?? "Scan-Fehler");
          }
        }
      } catch {}
    }, 3000);
  }

  // ── Gefilterte + sortierte Liste ─────────────────────────────────────────────

  const angezeigteLeads = leads
    .filter((l) => {
      if (filterKontakt && !l.kontakt_vorhanden) return false;
      if (filterMinFlaeche > 0 && l.dachflaeche_qm < filterMinFlaeche) return false;
      if (filterSuche) {
        const q = filterSuche.toLowerCase();
        const haystack = [l.name, l.operator, l.brand, l.adresse, l.stadt, l.email].join(" ").toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    })
    .sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      if (typeof av === "number" && typeof bv === "number")
        return sortDir === "desc" ? bv - av : av - bv;
      return sortDir === "desc"
        ? String(bv).localeCompare(String(av))
        : String(av).localeCompare(String(bv));
    });

  function toggleSort(feld: typeof sortBy) {
    if (sortBy === feld) setSortDir((d) => d === "desc" ? "asc" : "desc");
    else { setSortBy(feld); setSortDir("desc"); }
  }

  function sortPfeil(feld: typeof sortBy) {
    if (sortBy !== feld) return <span className="text-slate-300 ml-1">↕</span>;
    return <span className="text-yellow-500 ml-1">{sortDir === "desc" ? "↓" : "↑"}</span>;
  }

  const isRunning = job?.status === "laeuft";
  const mitKontakt = leads.filter((l) => l.kontakt_vorhanden).length;

  return (
    <div className="space-y-8">
      {/* ── Header ── */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Solar-Dachflächen Scanner</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Findet Gebäude mit ≥ 500 m² Dachfläche als Solar-Leads – via OpenStreetMap
        </p>
      </div>

      {/* ── Formular ── */}
      <form onSubmit={starteScan} className="bg-white rounded-xl border border-slate-200 p-6 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="lg:col-span-2">
            <label className="block text-sm font-medium text-slate-700 mb-1">Ort / Region</label>
            <input
              required
              value={ort}
              onChange={(e) => setOrt(e.target.value)}
              placeholder='z.B. "Worms, Deutschland" oder "Rheinhessen"'
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Radius (km)</label>
            <input
              type="number" min={1} max={50} value={radius}
              onChange={(e) => setRadius(Number(e.target.value))}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Max. Ergebnisse</label>
            <input
              type="number" min={10} max={1000} step={10} value={maxErgebnisse}
              onChange={(e) => setMaxErgebnisse(Number(e.target.value))}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Mindest-Dachfläche: <strong>{minFlaeche.toLocaleString("de-DE")} m²</strong>
            </label>
            <input
              type="range" min={200} max={5000} step={100} value={minFlaeche}
              onChange={(e) => setMinFlaeche(Number(e.target.value))}
              className="w-full accent-yellow-500"
            />
            <div className="flex justify-between text-xs text-slate-400 mt-0.5">
              <span>200 m²</span><span>5.000 m²</span>
            </div>
          </div>
          <div className="flex flex-col gap-3 justify-end pb-1">
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox" checked={mitEnrichment}
                onChange={(e) => setMitEnrichment(e.target.checked)}
                className="rounded accent-yellow-500"
              />
              <span className="text-slate-700">
                Website-Anreicherung{" "}
                <span className="text-slate-400 font-normal">(Telefon, E-Mail, Impressum)</span>
              </span>
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox" checked={nurMitKontakt}
                onChange={(e) => setNurMitKontakt(e.target.checked)}
                className="rounded accent-yellow-500"
              />
              <span className="text-slate-700">Nur Leads mit Kontaktdaten</span>
            </label>
          </div>
        </div>

        <button
          type="submit"
          disabled={isRunning}
          className="bg-yellow-500 hover:bg-yellow-600 disabled:bg-yellow-300 text-white font-semibold px-6 py-2.5 rounded-lg text-sm transition-colors"
        >
          {isRunning ? "Scan läuft…" : "🔍 Scan starten"}
        </button>
      </form>

      {/* ── Fehler ── */}
      {fehler && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          {fehler}
        </div>
      )}

      {/* ── Fortschritt ── */}
      {job?.status === "laeuft" && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-5 py-4">
          <div className="flex items-center gap-3">
            <svg className="animate-spin h-5 w-5 text-yellow-500" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 100 16v-4l-3 3 3 3v-4a8 8 0 01-8-8z" />
            </svg>
            <div>
              <p className="text-sm font-medium text-yellow-800">Scan läuft…</p>
              <p className="text-xs text-yellow-600 mt-0.5">
                {job.gefiltert > 0
                  ? `${job.gefiltert} Gebäude ≥ ${minFlaeche} m² gefunden · ${job.verarbeitet} angereichert`
                  : "Gebäude-Polygone werden abgerufen und ausgemessen…"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Ergebnisse ── */}
      {leads.length > 0 && (
        <div className="space-y-4">
          {/* Stats + Aktionen */}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                {leads.length} Gebäude gefunden
              </h2>
              <div className="flex flex-wrap gap-3 mt-1 text-xs text-slate-500">
                <span>
                  <strong className="text-green-700">{mitKontakt}</strong> mit Kontakt
                </span>
                <span>
                  Größtes Dach:{" "}
                  <strong className="text-slate-800">
                    {leads[0]?.dachflaeche_qm.toLocaleString("de-DE", { maximumFractionDigits: 0 })} m²
                  </strong>
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => exportCSV(angezeigteLeads)}
                className="text-sm bg-slate-800 hover:bg-slate-900 text-white px-4 py-2 rounded-lg transition-colors"
              >
                ↓ CSV Export
              </button>
            </div>
          </div>

          {/* Filter-Leiste */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 flex flex-wrap gap-4 items-end">
            <div className="flex-1 min-w-[160px]">
              <label className="text-xs font-medium text-slate-600 mb-1 block">Suche</label>
              <input
                value={filterSuche}
                onChange={(e) => setFilterSuche(e.target.value)}
                placeholder="Name, Adresse, E-Mail…"
                className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-500"
              />
            </div>
            <div className="min-w-[160px]">
              <label className="text-xs font-medium text-slate-600 mb-1 block">
                Min. Fläche: <strong>{filterMinFlaeche > 0 ? `${filterMinFlaeche.toLocaleString("de-DE")} m²` : "alle"}</strong>
              </label>
              <input
                type="range" min={0} max={5000} step={100} value={filterMinFlaeche}
                onChange={(e) => setFilterMinFlaeche(Number(e.target.value))}
                className="w-full accent-yellow-500"
              />
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox" checked={filterKontakt}
                onChange={(e) => setFilterKontakt(e.target.checked)}
                className="rounded accent-yellow-500"
              />
              <span className="text-slate-700">Nur mit Kontakt</span>
            </label>
            <p className="text-xs text-slate-400 ml-auto self-end">
              {angezeigteLeads.length} / {leads.length} angezeigt
            </p>
          </div>

          {/* Tabelle */}
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th
                    onClick={() => toggleSort("name")}
                    className="text-left px-3 py-2.5 font-medium text-slate-600 whitespace-nowrap cursor-pointer hover:bg-slate-100 select-none"
                  >
                    Gebäude{sortPfeil("name")}
                  </th>
                  <th
                    onClick={() => toggleSort("stadt")}
                    className="text-left px-3 py-2.5 font-medium text-slate-600 whitespace-nowrap cursor-pointer hover:bg-slate-100 select-none"
                  >
                    Ort{sortPfeil("stadt")}
                  </th>
                  <th
                    onClick={() => toggleSort("dachflaeche_qm")}
                    className="text-left px-3 py-2.5 font-medium text-slate-600 whitespace-nowrap cursor-pointer hover:bg-slate-100 select-none"
                  >
                    Dachfläche{sortPfeil("dachflaeche_qm")}
                  </th>
                  {["Typ", "Kontakt", "Telefon / E-Mail", "Website", "Details"].map((h) => (
                    <th key={h} className="text-left px-3 py-2.5 font-medium text-slate-600 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {angezeigteLeads.map((lead) => (
                  <Fragment key={lead.osm_id}>
                    <tr
                      className="hover:bg-slate-50 cursor-pointer"
                      onClick={() => setExpandedId(expandedId === lead.osm_id ? null : lead.osm_id)}
                    >
                      <td className="px-3 py-2.5 font-medium text-slate-900 max-w-[180px]">
                        <span className="truncate block">{anzeigeName(lead)}</span>
                      </td>
                      <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap">
                        {[lead.postleitzahl, lead.stadt].filter(Boolean).join(" ") || "—"}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {flaecheBadge(lead.dachflaeche_qm)}
                      </td>
                      <td className="px-3 py-2.5 text-slate-500 whitespace-nowrap text-xs">
                        {lead.gebaeude_typ || lead.gebaeude_nutzung || "—"}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {kontaktBadge(lead)}
                      </td>
                      <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap text-xs">
                        {lead.telefon || lead.alle_telefone
                          ? <span className="text-slate-700">{lead.telefon || lead.alle_telefone.split(";")[0]}</span>
                          : lead.email || lead.alle_emails
                            ? <span className="text-blue-600 truncate max-w-[140px] block">{(lead.email || lead.alle_emails.split(";")[0]).trim()}</span>
                            : <span className="text-slate-300">—</span>
                        }
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        {lead.webseite ? (
                          <a
                            href={lead.webseite}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-blue-600 hover:underline truncate max-w-[120px] block text-xs"
                          >
                            {lead.webseite.replace(/^https?:\/\//, "").slice(0, 28)}
                          </a>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-slate-400 text-xs whitespace-nowrap">
                        {expandedId === lead.osm_id ? "▲" : "▼"}
                      </td>
                    </tr>

                    {/* Detail-Zeile */}
                    {expandedId === lead.osm_id && (
                      <tr className="bg-amber-50/50">
                        <td colSpan={8} className="px-4 py-4">
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Identifikation</p>
                              <dl className="space-y-1">
                                {lead.name && <div><dt className="inline text-slate-400">Name: </dt><dd className="inline text-slate-700">{lead.name}</dd></div>}
                                {lead.operator && <div><dt className="inline text-slate-400">Betreiber: </dt><dd className="inline text-slate-700">{lead.operator}</dd></div>}
                                {lead.brand && <div><dt className="inline text-slate-400">Marke: </dt><dd className="inline text-slate-700">{lead.brand}</dd></div>}
                                {lead.rechtlicher_name && <div><dt className="inline text-slate-400">Rechtl. Name: </dt><dd className="inline text-slate-700 font-medium">{lead.rechtlicher_name}</dd></div>}
                                {lead.entscheidungstraeger && <div><dt className="inline text-slate-400">Ansprechpartner: </dt><dd className="inline text-slate-700 font-medium">{lead.entscheidungstraeger}</dd></div>}
                                <div><dt className="inline text-slate-400">Adresse: </dt><dd className="inline text-slate-700">{[lead.adresse, lead.postleitzahl, lead.stadt].filter(Boolean).join(", ") || "—"}</dd></div>
                              </dl>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Kontaktdaten</p>
                              <dl className="space-y-1">
                                {(lead.alle_telefone || lead.telefon) && (
                                  <div>
                                    <dt className="inline text-slate-400">Telefon: </dt>
                                    <dd className="inline">
                                      {(lead.alle_telefone || lead.telefon).split(";").map((t) => t.trim()).filter(Boolean).map((t) => (
                                        <button
                                          key={t}
                                          onClick={() => kopiereText(t)}
                                          className="text-slate-700 hover:text-blue-600 mr-2"
                                          title="Kopieren"
                                        >
                                          {t}
                                        </button>
                                      ))}
                                    </dd>
                                  </div>
                                )}
                                {(lead.alle_emails || lead.email) && (
                                  <div>
                                    <dt className="inline text-slate-400">E-Mail: </dt>
                                    <dd className="inline">
                                      {(lead.alle_emails || lead.email).split(";").map((e) => e.trim()).filter(Boolean).map((e) => (
                                        <button
                                          key={e}
                                          onClick={() => kopiereText(e)}
                                          className="text-blue-600 hover:underline mr-2"
                                          title="Kopieren"
                                        >
                                          {e}
                                        </button>
                                      ))}
                                    </dd>
                                  </div>
                                )}
                              </dl>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Gebäude-Info</p>
                              <dl className="space-y-1">
                                <div><dt className="inline text-slate-400">Typ: </dt><dd className="inline text-slate-700">{lead.gebaeude_typ || "—"}</dd></div>
                                <div><dt className="inline text-slate-400">Nutzung: </dt><dd className="inline text-slate-700">{lead.gebaeude_nutzung || "—"}</dd></div>
                                <div><dt className="inline text-slate-400">Dachfläche: </dt><dd className="inline text-slate-700 font-bold">{lead.dachflaeche_qm.toLocaleString("de-DE", { maximumFractionDigits: 0 })} m²</dd></div>
                                <div><dt className="inline text-slate-400">OSM-ID: </dt><dd className="inline text-slate-500 font-mono">{lead.osm_id}</dd></div>
                              </dl>
                            </div>
                          </div>

                          {lead.impressum_info && (
                            <div className="mt-3 pt-3 border-t border-amber-100">
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1 text-xs">Impressum-Auszug</p>
                              <p className="text-xs text-slate-600 leading-relaxed line-clamp-3">{lead.impressum_info}</p>
                            </div>
                          )}

                          <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-amber-100">
                            <a
                              href={lead.google_maps_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 px-3 py-1.5 rounded-lg"
                            >
                              📍 Google Maps
                            </a>
                            <a
                              href={lead.quelle_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 px-3 py-1.5 rounded-lg"
                            >
                              OpenStreetMap
                            </a>
                            {lead.webseite && (
                              <a
                                href={lead.webseite}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 px-3 py-1.5 rounded-lg"
                              >
                                Website öffnen
                              </a>
                            )}
                            {(lead.email || lead.alle_emails) && (
                              <button
                                onClick={() => kopiereText(lead.email || lead.alle_emails.split(";")[0])}
                                className="text-xs bg-green-50 hover:bg-green-100 text-green-700 px-3 py-1.5 rounded-lg"
                              >
                                E-Mail kopieren
                              </button>
                            )}
                            {(lead.telefon || lead.alle_telefone) && (
                              <button
                                onClick={() => kopiereText(lead.telefon || lead.alle_telefone.split(";")[0])}
                                className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 px-3 py-1.5 rounded-lg"
                              >
                                Telefon kopieren
                              </button>
                            )}
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

      {/* Leer-Zustand */}
      {job?.status === "abgeschlossen" && leads.length === 0 && (
        <div className="text-center py-16 text-slate-400">
          Keine Gebäude mit ≥ {minFlaeche.toLocaleString("de-DE")} m² gefunden. Anderen Ort oder kleinere Mindestfläche versuchen.
        </div>
      )}
    </div>
  );
}
