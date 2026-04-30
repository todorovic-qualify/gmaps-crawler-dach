"""
FastAPI-Service: Stellt HTTP-Endpunkte für die Next.js-Frontend-Integration bereit.
Läuft als separater Prozess auf Port 8000.

Pipeline (3 Phasen):
  1. Rohdaten sammeln (Overpass)
  2. Duplikat-Matching gegen DB → nur neue Leads anreichern
  3. Scoring + Speichern (bestehende Leads immer "wiederverwendet")
"""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from typing import Optional, Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

load_dotenv()

API_KEY = os.environ.get("CRAWLER_API_KEY", "")


# ── DB-Schema-Migration (idempotent, läuft bei jedem Start) ───────────────────

def _migriere_db() -> None:
    """
    Fügt fehlende Spalten/Tabellen hinzu, befüllt norm_name, bereinigt Duplikate.
    Idempotent – sicher mehrfach ausführbar.
    """
    try:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            logger.warning("DATABASE_URL nicht gesetzt – Migration übersprungen")
            return

        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            # ── Neue Spalten in unternehmen ────────────────────────────────────
            cur.execute("""
                ALTER TABLE unternehmen
                  ADD COLUMN IF NOT EXISTS externe_id       TEXT,
                  ADD COLUMN IF NOT EXISTS norm_name        TEXT,
                  ADD COLUMN IF NOT EXISTS norm_domain      TEXT,
                  ADD COLUMN IF NOT EXISTS last_crawled_at  TIMESTAMPTZ,
                  ADD COLUMN IF NOT EXISTS crawl_status     TEXT DEFAULT 'neu',
                  ADD COLUMN IF NOT EXISTS quelle           TEXT DEFAULT 'overpass'
            """)

            # ── Neue Spalten in suchauftrag ────────────────────────────────────
            cur.execute("""
                ALTER TABLE suchauftrag
                  ADD COLUMN IF NOT EXISTS anzahl_neu              INTEGER DEFAULT 0,
                  ADD COLUMN IF NOT EXISTS anzahl_wiederverwendet  INTEGER DEFAULT 0,
                  ADD COLUMN IF NOT EXISTS anzahl_aktualisiert     INTEGER DEFAULT 0
            """)

            # ── Junction-Tabelle suchauftrag_unternehmen ───────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS suchauftrag_unternehmen (
                  id              TEXT PRIMARY KEY,
                  suchauftrag_id  TEXT NOT NULL REFERENCES suchauftrag(id) ON DELETE CASCADE,
                  unternehmen_id  TEXT NOT NULL REFERENCES unternehmen(id) ON DELETE CASCADE,
                  herkunft        TEXT NOT NULL DEFAULT 'neu',
                  erstellt_am     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  UNIQUE(suchauftrag_id, unternehmen_id)
                )
            """)

            # ── Indexes für Performance ────────────────────────────────────────
            cur.execute("CREATE INDEX IF NOT EXISTS idx_unt_externe_id   ON unternehmen(externe_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_unt_norm         ON unternehmen(norm_name, norm_domain)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_unt_stadt        ON unternehmen(stadt)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_unt_lead_score   ON unternehmen(lead_score)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_unt_crawl_status ON unternehmen(crawl_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sau_suchauftrag  ON suchauftrag_unternehmen(suchauftrag_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sau_unternehmen  ON suchauftrag_unternehmen(unternehmen_id)")

            # ── norm_name für Legacy-Einträge befüllen ─────────────────────────
            cur.execute("""
                UPDATE unternehmen
                SET norm_name = LOWER(TRIM(name))
                WHERE norm_name IS NULL AND name IS NOT NULL
            """)

            # ── Duplikate entfernen (gleicher Name + Stadt, bestes behalten) ──
            # Kriterium: hat externe_id > höherer Score > älterer Eintrag
            cur.execute("""
                DELETE FROM unternehmen
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY
                                       LOWER(TRIM(name)),
                                       LOWER(TRIM(COALESCE(stadt, '')))
                                   ORDER BY
                                       (CASE WHEN externe_id IS NOT NULL THEN 1 ELSE 0 END) DESC,
                                       lead_score DESC,
                                       erstellt_am ASC
                               ) AS rn
                        FROM unternehmen
                    ) t
                    WHERE rn > 1
                )
            """)

        conn.commit()
        conn.close()
        logger.info("DB-Migration erfolgreich abgeschlossen")
    except Exception as e:
        logger.warning(f"DB-Migration fehlgeschlagen (nicht kritisch): {e}")


@asynccontextmanager
async def lifespan(app_instance):
    _migriere_db()
    yield

app = FastAPI(
    title="LeadScout Crawler API",
    description="Interner Crawler-Service für die LeadScout-Plattform",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", os.environ.get("NEXTAUTH_URL", ""), "https://crawler-firmen.vercel.app"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Laufende Jobs tracken (in-memory, für MVP ausreichend)
_laufende_jobs: dict[str, dict] = {}


# ── Request-Modelle ────────────────────────────────────────────────────────────

class CrawlerStartRequest(BaseModel):
    ort: str
    radius_km: int = 10
    kategorien: list[str] = []
    max_ergebnisse: int = 100
    enrichment: bool = True
    auftrag_id: Optional[str] = None
    crawler_config: Optional[dict[str, Any]] = None
    scoring_config: Optional[dict[str, Any]] = None


class JobStatus(BaseModel):
    auftrag_id: str
    status: str
    gefunden: int = 0
    verarbeitet: int = 0
    fehler: Optional[str] = None
    anzahl_neu: int = 0
    anzahl_wiederverwendet: int = 0
    anzahl_aktualisiert: int = 0
    uebersprungen: int = 0


# ── Auth-Helper ────────────────────────────────────────────────────────────────

def prüfe_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Ungültiger API-Key")


# ── Hintergrund-Crawler (3-Phasen-Pipeline) ────────────────────────────────────

def _starte_crawler_job(request: CrawlerStartRequest, auftrag_id: str) -> None:
    """
    Läuft in einem separaten Thread.

    Phase 1: Rohdaten sammeln (Overpass)
    Phase 2: Duplikat-Matching – bestehende Leads IMMER wiederverwenden (kein Re-Crawl)
    Phase 3: Scoring + Speichern
    """
    from crawler.sources.overpass import suche_unternehmen, KATEGORIE_OSM_MAP
    from crawler.enricher import reichere_an
    from crawler.scorer import bewerte
    from crawler.db_writer import (
        verbinde, aktualisiere_suchauftrag,
        suche_duplikat, speichere_oder_aktualisiere_unternehmen,
    )
    from crawler.utils.http_utils import rate_limiter_setzen

    _laufende_jobs[auftrag_id] = {
        "status": "laeuft",
        "gefunden": 0,
        "verarbeitet": 0,
        "anzahl_neu": 0,
        "anzahl_wiederverwendet": 0,
        "anzahl_aktualisiert": 0,
        "uebersprungen": 0,
    }

    if request.crawler_config:
        delay = request.crawler_config.get("delay_seconds")
        if isinstance(delay, (int, float)) and delay > 0:
            rate_limiter_setzen(float(delay))

    kategorien = request.kategorien or list(KATEGORIE_OSM_MAP.keys())

    try:
        # ── Phase 1: Rohdaten sammeln ─────────────────────────────────────────
        logger.info(f"[Job {auftrag_id}] Phase 1: Suche in '{request.ort}'")
        roh_liste = suche_unternehmen(
            ort=request.ort,
            radius_km=request.radius_km,
            kategorien=kategorien,
            max_ergebnisse=request.max_ergebnisse,
        )
        _laufende_jobs[auftrag_id]["gefunden"] = len(roh_liste)
        logger.info(f"[Job {auftrag_id}] Roh-Treffer: {len(roh_liste)}")

        if not roh_liste:
            logger.warning(f"[Job {auftrag_id}] Keine Treffer – Geocodierung prüfen!")
            conn = verbinde()
            aktualisiere_suchauftrag(conn, auftrag_id, "abgeschlossen", 0, 0)
            conn.close()
            _laufende_jobs[auftrag_id]["status"] = "abgeschlossen"
            return

        # ── Phase 2: Duplikat-Matching ────────────────────────────────────────
        logger.info(f"[Job {auftrag_id}] Phase 2: Duplikat-Matching")
        conn = verbinde()

        neu_liste = []        # Keine DB-Einträge → vollständig anreichern
        bekannt_liste = []    # Bereits in DB → immer wiederverwenden, nie überschreiben

        for u in roh_liste:
            existierend = suche_duplikat(conn, u)
            if existierend is None:
                neu_liste.append(u)
            else:
                bekannt_liste.append(u)

        conn.close()

        logger.info(
            f"[Job {auftrag_id}] Matching: "
            f"{len(neu_liste)} neu | {len(bekannt_liste)} bereits bekannt (wiederverwendet)"
        )
        _laufende_jobs[auftrag_id]["uebersprungen"] = len(bekannt_liste)

        # ── Phase 3: Enrichment nur für neue Leads ────────────────────────────
        logger.info(f"[Job {auftrag_id}] Phase 3: Enrichment ({len(neu_liste)} neue Leads)")
        if request.enrichment:
            for i, u in enumerate(neu_liste):
                if u.hat_webseite:
                    try:
                        reichere_an(u)
                        logger.debug(f"[Job {auftrag_id}] Enrichment {i+1}/{len(neu_liste)}: {u.name}")
                    except Exception as e:
                        logger.warning(f"[Job {auftrag_id}] Enrichment fehlgeschlagen {u.name}: {e}")

        # ── Phase 4: Scoring + Speichern ──────────────────────────────────────
        logger.info(f"[Job {auftrag_id}] Phase 4: Scoring + Speichern")
        conn = verbinde()

        anzahl_neu = 0
        anzahl_wiederverwendet = 0
        gespeichert = 0

        # Neue Leads: bewerten + speichern
        for u in neu_liste:
            try:
                bewerte(u, konfig=request.scoring_config)
                u_id, herkunft = speichere_oder_aktualisiere_unternehmen(conn, u, auftrag_id)
                gespeichert += 1
                if herkunft == "neu":
                    anzahl_neu += 1
                else:
                    anzahl_wiederverwendet += 1
                _laufende_jobs[auftrag_id]["verarbeitet"] = gespeichert
                _laufende_jobs[auftrag_id]["anzahl_neu"] = anzahl_neu
                _laufende_jobs[auftrag_id]["anzahl_wiederverwendet"] = anzahl_wiederverwendet
            except Exception as e:
                logger.error(f"[Job {auftrag_id}] DB-Fehler für {u.name}: {e}")

        # Bekannte Leads: nur verknüpfen, KEINE Daten überschreiben
        for u in bekannt_liste:
            try:
                u_id, herkunft = speichere_oder_aktualisiere_unternehmen(conn, u, auftrag_id)
                gespeichert += 1
                anzahl_wiederverwendet += 1
                _laufende_jobs[auftrag_id]["verarbeitet"] = gespeichert
                _laufende_jobs[auftrag_id]["anzahl_wiederverwendet"] = anzahl_wiederverwendet
            except Exception as e:
                logger.error(f"[Job {auftrag_id}] DB-Fehler für {u.name}: {e}")

        aktualisiere_suchauftrag(
            conn, auftrag_id, "abgeschlossen",
            len(roh_liste), gespeichert,
            anzahl_neu=anzahl_neu,
            anzahl_wiederverwendet=anzahl_wiederverwendet,
            anzahl_aktualisiert=0,
        )
        conn.close()

        _laufende_jobs[auftrag_id]["status"] = "abgeschlossen"

        logger.info(
            f"[Job {auftrag_id}] Abgeschlossen: "
            f"{anzahl_neu} neu | {anzahl_wiederverwendet} wiederverwendet"
        )

    except Exception as e:
        logger.error(f"[Job {auftrag_id}] Fehler: {e}", exc_info=True)
        _laufende_jobs[auftrag_id]["status"] = "fehler"
        _laufende_jobs[auftrag_id]["fehler"] = str(e)
        try:
            from crawler.db_writer import verbinde, aktualisiere_suchauftrag
            conn = verbinde()
            aktualisiere_suchauftrag(conn, auftrag_id, "fehler", 0, 0, str(e))
            conn.close()
        except Exception:
            pass


# ── Force-Recrawl für einzelnen Lead ──────────────────────────────────────────

def _recrawl_lead_job(lead_id: str) -> dict:
    """Vollständiger Re-Crawl + Re-Scoring für einen einzelnen Lead."""
    from crawler.models import Unternehmen
    from crawler.enricher import reichere_an
    from crawler.scorer import bewerte
    from crawler.db_writer import verbinde, aktualisiere_unternehmen

    conn = verbinde()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM unternehmen WHERE id = %s", (lead_id,))
        row = cur.fetchone()
    conn.close()

    if not row:
        return {"fehler": f"Lead {lead_id} nicht gefunden"}

    u = Unternehmen(
        name=row["name"],
        kategorie=row["kategorie"],
        beschreibung=row["beschreibung"],
        adresse=row["adresse"],
        stadt=row["stadt"],
        postleitzahl=row["postleitzahl"],
        telefon=row["telefon"],
        email=row["email"],
        webseite=row["webseite"],
        quelle_url=row["quelle_url"],
        bewertung=row["bewertung"],
        bewertungsanzahl=row.get("bewertungs_anzahl"),
        oeffnungszeiten=row["oeffnungszeiten"],
        instagram=row["instagram"],
        facebook=row["facebook"],
        linkedin=row["linkedin"],
        whatsapp=row["whatsapp"],
        hat_webseite=row["hat_webseite"],
        hat_email=row["hat_email"],
        hat_telefon=row["hat_telefon"],
        externe_id=row.get("externe_id"),
        crawl_status="aktualisiert",
        quelle=row.get("quelle") or "overpass",
    )

    if u.hat_webseite and u.webseite:
        try:
            reichere_an(u)
            logger.info(f"Recrawl Enrichment abgeschlossen: {u.name}")
        except Exception as e:
            logger.warning(f"Recrawl Enrichment fehlgeschlagen für {u.name}: {e}")

    bewerte(u)

    conn = verbinde()
    aktualisiere_unternehmen(conn, lead_id, u)
    conn.close()

    logger.info(f"Recrawl abgeschlossen: {u.name} ({lead_id}) → Score {u.lead_score}")
    return {"status": "abgeschlossen", "lead_id": lead_id, "lead_score": u.lead_score}


# ── Endpunkte ─────────────────────────────────────────────────────────────────

@app.get("/gesundheit")
@app.get("/health")
def gesundheitscheck():
    return {"status": "ok", "service": "LeadScout Crawler v2.1"}


@app.post("/starten", response_model=JobStatus)
def crawler_starten(
    request: CrawlerStartRequest,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
):
    """Startet einen Crawler-Job im Hintergrund."""
    prüfe_api_key(x_api_key)

    from crawler.db_writer import verbinde, erstelle_suchauftrag
    from crawler.sources.overpass import KATEGORIE_OSM_MAP

    kategorien = request.kategorien or list(KATEGORIE_OSM_MAP.keys())

    auftrag_id = request.auftrag_id
    if not auftrag_id:
        try:
            conn = verbinde()
            auftrag_id = erstelle_suchauftrag(
                conn, request.ort, request.radius_km,
                kategorien, request.max_ergebnisse,
            )
            conn.close()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DB-Fehler: {e}")

    thread = threading.Thread(
        target=_starte_crawler_job,
        args=(request, auftrag_id),
        daemon=True,
    )
    thread.start()

    return JobStatus(auftrag_id=auftrag_id, status="laeuft")


@app.get("/status/{auftrag_id}", response_model=JobStatus)
def job_status(
    auftrag_id: str,
    x_api_key: Optional[str] = Header(None),
):
    """Gibt den Status eines laufenden Jobs zurück."""
    prüfe_api_key(x_api_key)

    if auftrag_id in _laufende_jobs:
        j = _laufende_jobs[auftrag_id]
        return JobStatus(
            auftrag_id=auftrag_id,
            status=j["status"],
            gefunden=j.get("gefunden", 0),
            verarbeitet=j.get("verarbeitet", 0),
            fehler=j.get("fehler"),
            anzahl_neu=j.get("anzahl_neu", 0),
            anzahl_wiederverwendet=j.get("anzahl_wiederverwendet", 0),
            anzahl_aktualisiert=j.get("anzahl_aktualisiert", 0),
            uebersprungen=j.get("uebersprungen", 0),
        )

    try:
        from crawler.db_writer import verbinde
        conn = verbinde()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT status, gesamt_gefunden, gesamt_verarbeitet, fehler_meldung,
                          anzahl_neu, anzahl_wiederverwendet, anzahl_aktualisiert
                   FROM suchauftrag WHERE id=%s""",
                (auftrag_id,),
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
        return JobStatus(
            auftrag_id=auftrag_id,
            status=row["status"],
            gefunden=row["gesamt_gefunden"],
            verarbeitet=row["gesamt_verarbeitet"],
            fehler=row["fehler_meldung"],
            anzahl_neu=row.get("anzahl_neu", 0) or 0,
            anzahl_wiederverwendet=row.get("anzahl_wiederverwendet", 0) or 0,
            anzahl_aktualisiert=row.get("anzahl_aktualisiert", 0) or 0,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/recrawl/{lead_id}")
def recrawl_lead(
    lead_id: str,
    x_api_key: Optional[str] = Header(None),
):
    """
    Forciert einen vollständigen erneuten Crawl für einen einzelnen Lead.
    Blockierend – wartet bis Enrichment + Scoring abgeschlossen sind.
    """
    prüfe_api_key(x_api_key)
    ergebnis = _recrawl_lead_job(lead_id)
    if "fehler" in ergebnis:
        raise HTTPException(status_code=404, detail=ergebnis["fehler"])
    return ergebnis


@app.get("/kategorien")
def kategorien_liste():
    """Gibt alle verfügbaren Kategorien zurück."""
    from crawler.sources.overpass import KATEGORIE_OSM_MAP
    return {"kategorien": list(KATEGORIE_OSM_MAP.keys())}


# ── Dach-Scanner Endpunkte ────────────────────────────────────────────────────

# In-Memory-Speicher für Dach-Jobs (letzte 50 Jobs)
_dach_jobs: dict[str, dict] = {}
_dach_ergebnisse: dict[str, list[dict]] = {}


class DachStartRequest(BaseModel):
    ort: str
    radius_km: int = 10
    min_flaeche_qm: float = 500.0
    max_ergebnisse: int = 200
    enrichment: bool = True
    nur_mit_kontakt: bool = False
    lat: Optional[float] = None
    lon: Optional[float] = None


class DachJobStatus(BaseModel):
    job_id: str
    status: str
    gescannt: int = 0
    gefiltert: int = 0
    verarbeitet: int = 0
    fehler: Optional[str] = None


def _starte_dach_job(request: DachStartRequest, job_id: str) -> None:
    """Läuft im Hintergrund-Thread."""
    from crawler.sources.dach_scanner import scanne_dachflaechen
    from crawler.dach_enricher import reichere_dachlead_an

    _dach_jobs[job_id] = {
        "status": "laeuft",
        "gescannt": 0,
        "gefiltert": 0,
        "verarbeitet": 0,
    }

    try:
        leads = scanne_dachflaechen(
            ort=request.ort,
            radius_km=request.radius_km,
            min_flaeche_qm=request.min_flaeche_qm,
            max_ergebnisse=request.max_ergebnisse,
            nur_mit_kontakt=False,
            lat=request.lat,
            lon=request.lon,
        )
        _dach_jobs[job_id]["gefiltert"] = len(leads)

        if request.enrichment:
            for i, lead in enumerate(leads):
                if lead.webseite:
                    try:
                        reichere_dachlead_an(lead)
                    except Exception as e:
                        logger.warning(f"[Dach {job_id}] Enrichment {lead.anzeigename()}: {e}")
                _dach_jobs[job_id]["verarbeitet"] = i + 1

        if request.nur_mit_kontakt:
            leads = [l for l in leads if l.kontakt_vorhanden()]

        _dach_ergebnisse[job_id] = [l.to_csv_row() | {"lat": l.lat, "lon": l.lon} for l in leads]

        # Speicher begrenzen: nur letzte 50 Jobs behalten
        if len(_dach_ergebnisse) > 50:
            oldest = next(iter(_dach_ergebnisse))
            _dach_ergebnisse.pop(oldest, None)
            _dach_jobs.pop(oldest, None)

        _dach_jobs[job_id]["status"] = "abgeschlossen"
        _dach_jobs[job_id]["verarbeitet"] = len(_dach_ergebnisse[job_id])
        logger.info(f"[Dach {job_id}] Abgeschlossen: {len(_dach_ergebnisse[job_id])} Leads")

    except Exception as e:
        logger.error(f"[Dach {job_id}] Fehler: {e}", exc_info=True)
        _dach_jobs[job_id]["status"] = "fehler"
        _dach_jobs[job_id]["fehler"] = str(e)


@app.post("/dach/starten", response_model=DachJobStatus)
def dach_starten(
    request: DachStartRequest,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
):
    """Startet einen Dachflächen-Scan im Hintergrund."""
    prüfe_api_key(x_api_key)

    import uuid
    job_id = str(uuid.uuid4())[:8]

    thread = threading.Thread(
        target=_starte_dach_job,
        args=(request, job_id),
        daemon=True,
    )
    thread.start()

    return DachJobStatus(job_id=job_id, status="laeuft")


@app.get("/dach/status/{job_id}", response_model=DachJobStatus)
def dach_job_status(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
):
    """Gibt den Status eines laufenden Dach-Jobs zurück."""
    prüfe_api_key(x_api_key)
    j = _dach_jobs.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return DachJobStatus(
        job_id=job_id,
        status=j["status"],
        gescannt=j.get("gescannt", 0),
        gefiltert=j.get("gefiltert", 0),
        verarbeitet=j.get("verarbeitet", 0),
        fehler=j.get("fehler"),
    )


@app.get("/dach/ergebnisse/{job_id}")
def dach_ergebnisse(
    job_id: str,
    x_api_key: Optional[str] = Header(None),
):
    """Gibt die Ergebnisse eines abgeschlossenen Dach-Jobs zurück."""
    prüfe_api_key(x_api_key)
    if job_id not in _dach_jobs:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    leads = _dach_ergebnisse.get(job_id, [])
    return {"job_id": job_id, "anzahl": len(leads), "leads": leads}


@app.get("/dach/jobs")
def dach_alle_jobs(x_api_key: Optional[str] = Header(None)):
    """Listet alle bekannten Dach-Jobs (neueste zuerst)."""
    prüfe_api_key(x_api_key)
    jobs = [
        {"job_id": jid, **jdata}
        for jid, jdata in reversed(list(_dach_jobs.items()))
    ]
    return {"jobs": jobs}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
