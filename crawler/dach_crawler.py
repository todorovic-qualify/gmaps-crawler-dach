#!/usr/bin/env python3
"""
Solar-Dach-Crawler: Findet Gebäude mit ≥ 500 m² Dachfläche als Solar-Leads.

Beispiele:
  python -m crawler.dach_crawler --ort "Worms, Deutschland" --radius 10
  python -m crawler.dach_crawler --ort "München" --radius 5 --min-flaeche 800
  python -m crawler.dach_crawler --ort "Frankfurt" --radius 15 --kein-enrichment
  python -m crawler.dach_crawler --ort "Rheinhessen" --nur-mit-kontakt
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

load_dotenv()

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
)
logger.add(
    "logs/dach_crawler_{time}.log",
    rotation="50 MB",
    retention="7 days",
    level="DEBUG",
    encoding="utf-8",
)

Path("logs").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

from crawler.sources.dach_scanner import scanne_dachflaechen
from crawler.dach_enricher import reichere_dachlead_an
from crawler.dach_models import DachLead
from crawler.utils.http_utils import rate_limiter_setzen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solar-Dach-Crawler – Leads mit großen Dachflächen finden",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Strategie:
  1. OpenStreetMap via Overpass API nach Gebäude-Polygonen abfragen
  2. Dachfläche aus Polygon-Geometrie berechnen
  3. Gebäude mit ≥ min-flaeche m² filtern
  4. Kontaktdaten aus OSM-Tags + Website-Scraping anreichern
  5. Lead-Liste als CSV/JSON ausgeben
        """,
    )
    parser.add_argument("--ort", "--place", required=True,
                        help='Ortsname, z.B. "Worms, Deutschland"')
    parser.add_argument("--lat", type=float, default=None,
                        help="Breitengrad (überspringt Geocodierung)")
    parser.add_argument("--lon", type=float, default=None,
                        help="Längengrad (überspringt Geocodierung)")
    parser.add_argument("--radius", "--radius-km", type=int, default=10,
                        help="Suchradius in km (Standard: 10)")
    parser.add_argument("--min-flaeche", type=float, default=500.0,
                        help="Mindest-Dachfläche in m² (Standard: 500)")
    parser.add_argument("--max", type=int, default=200, dest="max_ergebnisse",
                        help="Maximale Leads (Standard: 200)")
    parser.add_argument("--output", "-o", default="output/dach_leads.csv",
                        help="Ausgabedatei (Standard: output/dach_leads.csv)")
    parser.add_argument("--format", choices=["csv", "json"], default=None,
                        help="Ausgabeformat (automatisch aus Dateiendung erkannt)")
    parser.add_argument("--kein-enrichment", action="store_true",
                        help="Website-Anreicherung überspringen (schneller)")
    parser.add_argument("--nur-mit-kontakt", action="store_true",
                        help="Nur Leads mit Kontaktdaten ausgeben")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Pause zwischen Anfragen in Sekunden (Standard: 2.0)")
    return parser.parse_args()


def speichere_csv(leads: list[DachLead], pfad: str) -> None:
    if not leads:
        logger.warning("Keine Leads zum Speichern")
        return
    felder = list(leads[0].to_csv_row().keys())
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=felder)
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.to_csv_row())
    logger.info(f"CSV gespeichert: {pfad} ({len(leads)} Leads)")


def speichere_json(leads: list[DachLead], pfad: str) -> None:
    daten = []
    for lead in leads:
        row = lead.to_csv_row()
        row["lat"] = lead.lat
        row["lon"] = lead.lon
        daten.append(row)
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"JSON gespeichert: {pfad} ({len(leads)} Leads)")


def main() -> None:
    args = parse_args()
    rate_limiter_setzen(args.delay)

    logger.info("=== Solar-Dach-Crawler ===")
    logger.info(f"Ort:           {args.ort}")
    logger.info(f"Radius:        {args.radius} km")
    logger.info(f"Mindestfläche: {args.min_flaeche} m²")
    logger.info(f"Max. Leads:    {args.max_ergebnisse}")

    # Phase 1: Gebäude scannen
    logger.info("Phase 1: Dachflächen-Scan via Overpass …")
    leads = scanne_dachflaechen(
        ort=args.ort,
        radius_km=args.radius,
        min_flaeche_qm=args.min_flaeche,
        max_ergebnisse=args.max_ergebnisse,
        nur_mit_kontakt=False,  # erst nach Enrichment filtern
        lat=args.lat,
        lon=args.lon,
    )

    if not leads:
        logger.warning("Keine Gebäude gefunden. Abbruch.")
        sys.exit(0)

    logger.info(f"Gefunden: {len(leads)} Gebäude ≥ {args.min_flaeche} m²")

    # Phase 2: Website-Anreicherung
    if not args.kein_enrichment:
        mit_webseite = [l for l in leads if l.webseite]
        logger.info(f"Phase 2: Website-Anreicherung ({len(mit_webseite)} mit Website) …")
        for lead in tqdm(leads, desc="Anreicherung", unit="Lead"):
            if lead.webseite:
                reichere_dachlead_an(lead)
    else:
        logger.info("Phase 2: Website-Anreicherung übersprungen (--kein-enrichment)")

    # Phase 3: Filtern nach Kontakt (optional)
    if args.nur_mit_kontakt:
        vorher = len(leads)
        leads = [l for l in leads if l.kontakt_vorhanden()]
        logger.info(f"Filter 'nur mit Kontakt': {vorher} → {len(leads)} Leads")

    # Statistik
    mit_telefon = sum(1 for l in leads if l.telefon)
    mit_email = sum(1 for l in leads if l.email or l.gefundene_emails)
    mit_webseite = sum(1 for l in leads if l.webseite)
    ohne_kontakt = sum(1 for l in leads if not l.kontakt_vorhanden())

    logger.info(f"Kontakt-Statistik:")
    logger.info(f"  Telefon:      {mit_telefon}")
    logger.info(f"  E-Mail:       {mit_email}")
    logger.info(f"  Website:      {mit_webseite}")
    logger.info(f"  Kein Kontakt: {ohne_kontakt}")

    # Top 5 zeigen
    logger.info("Top 5 nach Dachfläche:")
    for i, lead in enumerate(leads[:5], 1):
        kontakt = lead.telefon or lead.email or lead.webseite or "kein Kontakt"
        logger.info(
            f"  {i}. {lead.anzeigename()[:40]:<40} "
            f"{lead.dachflaeche_qm:>8.0f} m²  {kontakt}"
        )

    # Phase 4: Ausgabe
    output_pfad = args.output
    fmt = args.format
    if fmt is None:
        fmt = "json" if output_pfad.endswith(".json") else "csv"

    if fmt == "json":
        speichere_json(leads, output_pfad)
    else:
        speichere_csv(leads, output_pfad)

    logger.info("=== Dach-Crawler abgeschlossen ===")


if __name__ == "__main__":
    main()
