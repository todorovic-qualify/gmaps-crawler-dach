"use client";

import { useState, useEffect, Fragment } from "react";

// ── Typen ──────────────────────────────────────────────────────────────────────

interface DachJob {
  job_id: string;
  ort?: string;
  status: string;
  gefiltert: number;
  verarbeitet: number;
  fehler?: string;
  erstellt_am?: string;
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

function anzeigeName(lead: DachLead): string {
  return lead.name || lead.operator || lead.brand || `Gebäude (${lead.gebaeude_typ || "?"})`;
}

async function kopiereText(text: string) {
  try { await navigator.clipboard.writeText(text); } catch {}
}

function exportCSV(leads: DachLead[], jobId: string) {
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
  a.download = `dach_leads_${jobId}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Seite ──────────────────────────────────────────────────────────────────────

export default function DachLeadsSeite() {
  const [jobs, setJobs] = useState<DachJob[]>([]);
  const [aktuellerJob, setAktuellerJob] = useState<string | null>(null);
  const [leads, setLeads] = useState<DachLead[]>([]);
  const [laden, setLaden] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Filter
  const [filterSuche, setFilterSuche] = useState("");
  const [filterKontakt, setFilterKontakt] = useState(false);
  const [filterMinFlaeche, setFilterMinFlaeche] = useState(0);
  const [sortBy, setSortBy] = useState<"dachflaeche_qm" | "name" | "stadt">("dachflaeche_qm");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Jobs laden
  useEffect(() => {
    ladeJobs();
  }, []);

  async function ladeJobs() {
    try {
      const res = await fetch("/api/dach/jobs");
      if (!res.ok) return;
      const data = await res.json();
      const jobListe: DachJob[] = data.jobs ?? [];
      setJobs(jobListe);
      // Automatisch letzten abgeschlossenen Job laden
      const letzter = jobListe.find((j) => j.status === "abgeschlossen");
      if (letzter) ladeJobErgebnisse(letzter.job_id);
    } catch {}
  }

  async function ladeJobErgebnisse(jobId: string) {
    setLaden(true);
    setFehler(null);
    setAktuellerJob(jobId);
    setExpandedId(null);
    try {
      const res = await fetch(`/api/dach/search/${jobId}/results`);
      const data = await res.json();
      if (!res.ok) {
        setFehler(data.error ?? "Fehler beim Laden");
        setLeads([]);
      } else {
        setLeads(data.leads ?? []);
      }
    } catch (e) {
      setFehler(String(e));
    } finally {
      setLaden(false);
    }
  }

  // Gefilterte + sortierte Liste
  const angezeigteLeads = leads
    .filter((l) => {
      if (filterKontakt && !l.kontakt_vorhanden) return false;
      if (filterMinFlaeche > 0 && l.dachflaeche_qm < filterMinFlaeche) return false;
      if (filterSuche) {
        const q = filterSuche.toLowerCase();
        const h = [l.name, l.operator, l.brand, l.adresse, l.stadt, l.email].join(" ").toLowerCase();
        if (!h.includes(q)) return false;
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
    if (sortBy === feld) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortBy(feld); setSortDir("desc"); }
  }

  function sortPfeil(feld: typeof sortBy) {
    if (sortBy !== feld) return <span className="text-slate-300 ml-1">↕</span>;
    return <span className="text-yellow-500 ml-1">{sortDir === "desc" ? "↓" : "↑"}</span>;
  }

  const mitKontakt = leads.filter((l) => l.kontakt_vorhanden).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dach-Leads Archiv</h1>
          <p className="text-slate-500 mt-0.5 text-sm">
            Ergebnisse aller bisherigen Dachflächen-Scans
          </p>
        </div>
        <div className="flex gap-2">
          {aktuellerJob && leads.length > 0 && (
            <button
              onClick={() => exportCSV(angezeigteLeads, aktuellerJob)}
              className="text-sm bg-slate-800 hover:bg-slate-900 text-white px-4 py-2 rounded-lg transition-colors"
            >
              ↓ CSV Export
            </button>
          )}
          <a
            href="/dach"
            className="text-sm bg-yellow-500 hover:bg-yellow-600 text-white font-medium px-4 py-2 rounded-lg transition-colors"
          >
            + Neuer Scan
          </a>
        </div>
      </div>

      {/* Job-Auswahl */}
      {jobs.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-3">Scan-Verlauf</p>
          <div className="flex flex-wrap gap-2">
            {jobs.map((job) => (
              <button
                key={job.job_id}
                onClick={() => ladeJobErgebnisse(job.job_id)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  aktuellerJob === job.job_id
                    ? "bg-yellow-50 border-yellow-400 text-yellow-800 font-medium"
                    : "border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${
                    job.status === "abgeschlossen"
                      ? "bg-green-500"
                      : job.status === "laeuft"
                        ? "bg-yellow-500 animate-pulse"
                        : "bg-red-400"
                  }`}
                />
                {job.ort || `Job ${job.job_id}`}
                {job.verarbeitet > 0 && (
                  <span className="ml-1.5 text-slate-400">({job.verarbeitet})</span>
                )}
                {job.erstellt_am && (
                  <span className="ml-1.5 text-slate-400">
                    · {new Date(job.erstellt_am).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })}
                  </span>
                )}
              </button>
            ))}
          </div>
          {jobs.length === 0 && (
            <p className="text-sm text-slate-400">Noch keine Scans gestartet.</p>
          )}
        </div>
      )}

      {/* Fehler */}
      {fehler && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          {fehler}
        </div>
      )}

      {/* Lade-Spinner */}
      {laden && (
        <div className="flex items-center justify-center py-12 text-slate-400">
          <svg className="animate-spin h-6 w-6 mr-3 text-yellow-500" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 100 16v-4l-3 3 3 3v-4a8 8 0 01-8-8z" />
          </svg>
          Leads werden geladen…
        </div>
      )}

      {/* Ergebnisse */}
      {!laden && leads.length > 0 && (
        <div className="space-y-4">
          {/* Stats */}
          <div className="flex flex-wrap items-center gap-4 text-sm text-slate-600">
            <span><strong className="text-slate-900">{leads.length}</strong> Gebäude</span>
            <span><strong className="text-green-700">{mitKontakt}</strong> mit Kontakt</span>
            {leads[0] && (
              <span>
                Größtes Dach:{" "}
                <strong className="text-slate-800">
                  {leads[0].dachflaeche_qm.toLocaleString("de-DE", { maximumFractionDigits: 0 })} m²
                </strong>
              </span>
            )}
          </div>

          {/* Filter */}
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
            <div className="min-w-[180px]">
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
                  {["Typ", "Telefon / E-Mail", "Website", "Details"].map((h) => (
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
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                        {lead.telefon || lead.alle_telefone
                          ? <span className="text-slate-700">{lead.telefon || lead.alle_telefone.split(";")[0]}</span>
                          : lead.email || lead.alle_emails
                            ? <span className="text-blue-600 truncate max-w-[130px] block">{(lead.email || lead.alle_emails.split(";")[0]).trim()}</span>
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
                            className="text-blue-600 hover:underline truncate max-w-[110px] block text-xs"
                          >
                            {lead.webseite.replace(/^https?:\/\//, "").slice(0, 26)}
                          </a>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-slate-400 text-xs whitespace-nowrap">
                        {expandedId === lead.osm_id ? "▲" : "▼"}
                      </td>
                    </tr>

                    {expandedId === lead.osm_id && (
                      <tr className="bg-amber-50/50">
                        <td colSpan={7} className="px-4 py-4">
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Identifikation</p>
                              <dl className="space-y-1">
                                {lead.name && <div><dt className="inline text-slate-400">Name: </dt><dd className="inline text-slate-700">{lead.name}</dd></div>}
                                {lead.operator && <div><dt className="inline text-slate-400">Betreiber: </dt><dd className="inline text-slate-700">{lead.operator}</dd></div>}
                                {lead.rechtlicher_name && <div><dt className="inline text-slate-400">Rechtl. Name: </dt><dd className="inline text-slate-700 font-medium">{lead.rechtlicher_name}</dd></div>}
                                {lead.entscheidungstraeger && <div><dt className="inline text-slate-400">Ansprechpartner: </dt><dd className="inline text-slate-700 font-medium">{lead.entscheidungstraeger}</dd></div>}
                                <div><dt className="inline text-slate-400">Adresse: </dt><dd className="inline text-slate-700">{[lead.adresse, lead.postleitzahl, lead.stadt].filter(Boolean).join(", ") || "—"}</dd></div>
                              </dl>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Kontakt</p>
                              <dl className="space-y-1">
                                {(lead.alle_telefone || lead.telefon) && (
                                  <div>
                                    <dt className="inline text-slate-400">Telefon: </dt>
                                    {(lead.alle_telefone || lead.telefon).split(";").map((t) => t.trim()).filter(Boolean).map((t) => (
                                      <button key={t} onClick={() => kopiereText(t)} className="text-slate-700 hover:text-blue-600 mr-2" title="Kopieren">{t}</button>
                                    ))}
                                  </div>
                                )}
                                {(lead.alle_emails || lead.email) && (
                                  <div>
                                    <dt className="inline text-slate-400">E-Mail: </dt>
                                    {(lead.alle_emails || lead.email).split(";").map((e) => e.trim()).filter(Boolean).map((e) => (
                                      <button key={e} onClick={() => kopiereText(e)} className="text-blue-600 hover:underline mr-2" title="Kopieren">{e}</button>
                                    ))}
                                  </div>
                                )}
                              </dl>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Gebäude</p>
                              <dl className="space-y-1">
                                <div><dt className="inline text-slate-400">Typ: </dt><dd className="inline text-slate-700">{lead.gebaeude_typ || "—"}</dd></div>
                                <div><dt className="inline text-slate-400">Nutzung: </dt><dd className="inline text-slate-700">{lead.gebaeude_nutzung || "—"}</dd></div>
                                <div><dt className="inline text-slate-400">Dachfläche: </dt><dd className="inline font-bold text-slate-800">{lead.dachflaeche_qm.toLocaleString("de-DE", { maximumFractionDigits: 0 })} m²</dd></div>
                              </dl>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-amber-100">
                            <a href={lead.google_maps_url} target="_blank" rel="noopener noreferrer"
                              className="text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 px-3 py-1.5 rounded-lg">
                              📍 Google Maps
                            </a>
                            <a href={lead.quelle_url} target="_blank" rel="noopener noreferrer"
                              className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 px-3 py-1.5 rounded-lg">
                              OpenStreetMap
                            </a>
                            {lead.webseite && (
                              <a href={lead.webseite} target="_blank" rel="noopener noreferrer"
                                className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 px-3 py-1.5 rounded-lg">
                                Website
                              </a>
                            )}
                            {(lead.email || lead.alle_emails) && (
                              <button onClick={() => kopiereText(lead.email || lead.alle_emails.split(";")[0])}
                                className="text-xs bg-green-50 hover:bg-green-100 text-green-700 px-3 py-1.5 rounded-lg">
                                E-Mail kopieren
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
      {!laden && leads.length === 0 && !fehler && (
        <div className="text-center py-20 text-slate-400">
          <p className="text-4xl mb-3">🏭</p>
          <p>Noch keine Scan-Ergebnisse. Starte einen neuen Scan.</p>
          <a href="/dach" className="mt-4 inline-block text-sm bg-yellow-500 hover:bg-yellow-600 text-white font-medium px-5 py-2 rounded-lg">
            Scan starten
          </a>
        </div>
      )}
    </div>
  );
}
