"""
Dach-Scanner: Sucht Gebäude mit ≥ 500 m² Dachfläche via Overpass API.

Ablauf:
  1. Geocodierung (Nominatim)
  2. Overpass-Abfrage für alle Gebäude-Polygone im Radius
  3. Fläche aus Polygon-Geometrie berechnen (Shoelace-Formel)
  4. Filtern nach Mindestfläche
  5. Kontaktdaten aus OSM-Tags extrahieren
"""
from __future__ import annotations

import math
import time
from typing import Optional

from loguru import logger

from crawler.dach_models import DachLead
from crawler.utils.http_utils import get_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Gebäude-Typen die typischerweise große Dächer haben (Gewerblich/Industrie)
INTERESSANTE_GEBAEUDE_TYPEN = {
    "industrial", "warehouse", "commercial", "retail", "supermarket",
    "office", "school", "university", "hospital", "hotel",
    "sports_centre", "sports_hall", "stadium",
    "farm", "barn", "agricultural",
    "manufacture", "storage_tank",
    "yes",  # unspezifiziert – trotzdem mitaufnehmen, Fläche entscheidet
}


def geocodiere(ort: str) -> Optional[tuple[float, float]]:
    """Gibt (lat, lon) für einen Ortsnamen zurück."""
    time.sleep(1.0)
    daten = get_json(
        NOMINATIM_URL,
        params={"q": ort, "format": "json", "limit": 1},
        timeout=15.0,
    )
    if not daten or not isinstance(daten, list) or len(daten) == 0:
        logger.error(f"Geocodierung fehlgeschlagen für: {ort}")
        return None
    lat = float(daten[0]["lat"])
    lon = float(daten[0]["lon"])
    logger.info(f"Geocodiert: {ort} → {lat:.4f}, {lon:.4f}")
    return lat, lon


def berechne_flaeche_qm(punkte: list[tuple[float, float]]) -> float:
    """
    Berechnet die Fläche eines geografischen Polygons in m².
    Verwendet lokale Plattkarte-Projektion + Shoelace-Formel.
    Genauigkeit ±1% für Flächen < 1 km².
    """
    if len(punkte) < 3:
        return 0.0

    lat_mitte = sum(p[0] for p in punkte) / len(punkte)

    # Grad → Meter
    meter_pro_lat = 111320.0
    meter_pro_lon = 111320.0 * math.cos(math.radians(lat_mitte))

    # Projektion in Meter
    punkte_m = [(p[0] * meter_pro_lat, p[1] * meter_pro_lon) for p in punkte]

    # Shoelace-Formel (Gaußsche Trapezformel)
    n = len(punkte_m)
    flaeche = 0.0
    for i in range(n):
        j = (i + 1) % n
        flaeche += punkte_m[i][0] * punkte_m[j][1]
        flaeche -= punkte_m[j][0] * punkte_m[i][1]

    return abs(flaeche) / 2.0


def _baue_abfrage(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL: Alle Gebäude-Polygone im Radius mit voller Geometrie."""
    return f"""
[out:json][timeout:180];
(
  way[building](around:{radius_m},{lat},{lon});
  relation[building](around:{radius_m},{lat},{lon});
);
out geom tags;
"""


def _extrahiere_punkte(element: dict) -> list[tuple[float, float]]:
    """Extrahiert Polygon-Koordinaten aus einem Overpass-Element."""
    if element["type"] == "way":
        geometrie = element.get("geometry", [])
        return [(p["lat"], p["lon"]) for p in geometrie if "lat" in p and "lon" in p]

    if element["type"] == "relation":
        # Äußere Kontur des ersten outer-Members verwenden
        for member in element.get("members", []):
            if member.get("role") == "outer" and "geometry" in member:
                return [(p["lat"], p["lon"]) for p in member["geometry"]]

    return []


def _ermittle_nutzung(tags: dict) -> Optional[str]:
    """Extrahiert den primären Nutzungstyp aus OSM-Tags."""
    for schluessel in ("amenity", "shop", "office", "industrial", "landuse", "leisure", "tourism"):
        wert = tags.get(schluessel)
        if wert:
            return f"{schluessel}={wert}"
    return None


def _osm_zu_dachlead(element: dict, flaeche_qm: float) -> DachLead:
    """Konvertiert ein OSM-Element + berechnete Fläche in einen DachLead."""
    tags = element.get("tags", {})
    osm_id = f"{element['type']}/{element['id']}"

    # Koordinaten (Mittelpunkt)
    if element["type"] == "way":
        geometrie = element.get("geometry", [])
        if geometrie:
            lat = sum(p["lat"] for p in geometrie) / len(geometrie)
            lon = sum(p["lon"] for p in geometrie) / len(geometrie)
        else:
            lat = lon = 0.0
    else:
        center = element.get("center", {})
        lat = center.get("lat", 0.0)
        lon = center.get("lon", 0.0)

    # Adresse
    strasse = tags.get("addr:street", "")
    hausnummer = tags.get("addr:housenumber", "")
    adresse = f"{strasse} {hausnummer}".strip() or None
    stadt = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village")
    plz = tags.get("addr:postcode")

    # Kontakt
    telefon = tags.get("phone") or tags.get("contact:phone") or tags.get("telephone")
    email = tags.get("email") or tags.get("contact:email")
    webseite = tags.get("website") or tags.get("contact:website") or tags.get("url")
    if webseite and not webseite.startswith("http"):
        webseite = "https://" + webseite

    google_maps_url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"

    return DachLead(
        osm_id=osm_id,
        dachflaeche_qm=flaeche_qm,
        gebaeude_typ=tags.get("building"),
        gebaeude_nutzung=_ermittle_nutzung(tags),
        name=tags.get("name"),
        operator=tags.get("operator"),
        brand=tags.get("brand"),
        adresse=adresse,
        stadt=stadt,
        postleitzahl=plz,
        lat=lat,
        lon=lon,
        telefon=telefon.strip() if telefon else None,
        email=email.lower() if email else None,
        webseite=webseite,
        quelle_url=f"https://www.openstreetmap.org/{osm_id}",
        google_maps_url=google_maps_url,
    )


def scanne_dachflaechen(
    ort: str,
    radius_km: int = 5,
    min_flaeche_qm: float = 500.0,
    max_ergebnisse: int = 200,
    nur_mit_kontakt: bool = False,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> list[DachLead]:
    """
    Hauptfunktion: Sucht Gebäude mit ≥ min_flaeche_qm Dachfläche.

    Args:
        ort:              Ortsname (z.B. "Worms, Deutschland")
        radius_km:        Suchradius in km
        min_flaeche_qm:   Mindest-Dachfläche in m² (Standard: 500)
        max_ergebnisse:   Maximale Anzahl zurückgegebener Leads
        nur_mit_kontakt:  Nur Leads mit Telefon/E-Mail/Website ausgeben

    Returns:
        Liste von DachLead-Objekten, absteigend nach Dachfläche sortiert.
    """
    if lat is not None and lon is not None:
        logger.info(f"Verwende direkte Koordinaten: {lat:.4f}, {lon:.4f}")
    else:
        coords = geocodiere(ort)
        if coords is None:
            return []
        lat, lon = coords

    radius_m = radius_km * 1000

    logger.info(f"Starte Gebäude-Scan: {ort}, Radius {radius_km} km, Min. {min_flaeche_qm} m²")

    abfrage = _baue_abfrage(lat, lon, radius_m)
    daten = get_json(OVERPASS_URL, params={"data": abfrage}, timeout=180.0)

    if not daten or "elements" not in daten:
        logger.error("Keine Daten von Overpass API erhalten")
        return []

    elemente = daten["elements"]
    logger.info(f"Overpass: {len(elemente)} Gebäude gefunden, berechne Flächen …")

    leads: list[DachLead] = []

    for el in elemente:
        punkte = _extrahiere_punkte(el)
        if not punkte:
            continue

        flaeche = berechne_flaeche_qm(punkte)
        if flaeche < min_flaeche_qm:
            continue

        lead = _osm_zu_dachlead(el, flaeche)

        if nur_mit_kontakt and not lead.kontakt_vorhanden():
            continue

        leads.append(lead)

        if len(leads) >= max_ergebnisse:
            logger.info(f"Limit von {max_ergebnisse} Leads erreicht")
            break

    # Absteigend nach Fläche sortieren
    leads.sort(key=lambda l: l.dachflaeche_qm, reverse=True)

    logger.info(
        f"Scan abgeschlossen: {len(leads)} Gebäude mit ≥ {min_flaeche_qm} m² "
        f"(von {len(elemente)} geprüft)"
    )
    return leads
