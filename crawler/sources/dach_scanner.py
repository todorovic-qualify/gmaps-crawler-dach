"""
Dach-Scanner: Sucht Gebäude mit ≥ 500 m² Dachfläche via Overpass API.

Ablauf:
  1. Geocodierung (Nominatim)
  2. Overpass-Abfrage für alle Gebäude-Polygone im Radius
  3. Fläche aus Polygon-Geometrie berechnen (Shoelace-Formel)
  4. Filtern nach Mindestfläche
  5. Kontaktdaten aus OSM-Tags extrahieren
  6. PV-Anlagen erkennen (OSM-Tags + separate Overpass-Abfrage)
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

# OSM-Tags die direkt auf eine PV-Anlage am Gebäude hinweisen
PV_TAGS = {
    "generator:source": {"solar"},
    "power": {"generator"},  # nur wenn generator:source=solar auch gesetzt
    "roof:panels": {"solar", "photovoltaic", "pv"},
    "solar_panels": {"yes", "true", "1"},
    "generator:type": {"solar_photovoltaic_panel", "solar_thermal", "photovoltaic"},
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
    meter_pro_lat = 111320.0
    meter_pro_lon = 111320.0 * math.cos(math.radians(lat_mitte))
    punkte_m = [(p[0] * meter_pro_lat, p[1] * meter_pro_lon) for p in punkte]

    n = len(punkte_m)
    flaeche = 0.0
    for i in range(n):
        j = (i + 1) % n
        flaeche += punkte_m[i][0] * punkte_m[j][1]
        flaeche -= punkte_m[j][0] * punkte_m[i][1]

    return abs(flaeche) / 2.0


def _abstand_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Einfache Euklid-Näherung für kleine Abstände (< 10 km)."""
    dlat = (lat2 - lat1) * 111320.0
    dlon = (lon2 - lon1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dlat ** 2 + dlon ** 2)


def _hat_pv_in_tags(tags: dict) -> bool:
    """Prüft ob OSM-Tags des Gebäudes direkt auf eine PV-Anlage hinweisen."""
    gen_source = tags.get("generator:source", "").lower()
    if gen_source == "solar":
        return True

    roof_panels = tags.get("roof:panels", "").lower()
    if roof_panels in {"solar", "photovoltaic", "pv"}:
        return True

    solar_panels = tags.get("solar_panels", "").lower()
    if solar_panels in {"yes", "true", "1"}:
        return True

    gen_type = tags.get("generator:type", "").lower()
    if "solar" in gen_type or "photovoltaic" in gen_type:
        return True

    # "power=plant" + "plant:source=solar"
    if tags.get("power") in {"plant", "generator"} and "solar" in tags.get("plant:source", "").lower():
        return True

    return False


def _lade_pv_anlagen(lat: float, lon: float, radius_m: int) -> list[tuple[float, float]]:
    """
    Lädt alle bekannten PV-Anlagen im Radius via Overpass.
    Gibt Liste von (lat, lon) Koordinaten zurück.
    """
    abfrage = f"""
[out:json][timeout:60];
(
  node["generator:source"="solar"](around:{radius_m},{lat},{lon});
  way["generator:source"="solar"](around:{radius_m},{lat},{lon});
  node["power"="generator"]["generator:source"="solar"](around:{radius_m},{lat},{lon});
  node["solar_panels"="yes"](around:{radius_m},{lat},{lon});
  way["solar_panels"="yes"](around:{radius_m},{lat},{lon});
  node["generator:type"="solar_photovoltaic_panel"](around:{radius_m},{lat},{lon});
  way["generator:type"="solar_photovoltaic_panel"](around:{radius_m},{lat},{lon});
);
out center tags;
"""
    daten = get_json(OVERPASS_URL, params={"data": abfrage}, timeout=60.0)
    if not daten or "elements" not in daten:
        return []

    koordinaten = []
    for el in daten["elements"]:
        if el["type"] == "node":
            koordinaten.append((el["lat"], el["lon"]))
        else:
            center = el.get("center", {})
            if center:
                koordinaten.append((center["lat"], center["lon"]))

    logger.info(f"PV-Anlagen gefunden: {len(koordinaten)} in {radius_m}m Radius")
    return koordinaten


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
    if element["type"] == "way":
        geometrie = element.get("geometry", [])
        return [(p["lat"], p["lon"]) for p in geometrie if "lat" in p and "lon" in p]
    if element["type"] == "relation":
        for member in element.get("members", []):
            if member.get("role") == "outer" and "geometry" in member:
                return [(p["lat"], p["lon"]) for p in member["geometry"]]
    return []


def _ermittle_nutzung(tags: dict) -> Optional[str]:
    for schluessel in ("amenity", "shop", "office", "industrial", "landuse", "leisure", "tourism"):
        wert = tags.get(schluessel)
        if wert:
            return f"{schluessel}={wert}"
    return None


def _osm_zu_dachlead(element: dict, flaeche_qm: float) -> DachLead:
    tags = element.get("tags", {})
    osm_id = f"{element['type']}/{element['id']}"

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

    strasse = tags.get("addr:street", "")
    hausnummer = tags.get("addr:housenumber", "")
    adresse = f"{strasse} {hausnummer}".strip() or None
    stadt = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village")
    plz = tags.get("addr:postcode")

    telefon = tags.get("phone") or tags.get("contact:phone") or tags.get("telephone")
    email = tags.get("email") or tags.get("contact:email")
    webseite = tags.get("website") or tags.get("contact:website") or tags.get("url")
    if webseite and not webseite.startswith("http"):
        webseite = "https://" + webseite

    # PV direkt aus Tags erkennbar
    hat_pv: Optional[bool] = True if _hat_pv_in_tags(tags) else None

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
        hat_pv_anlage=hat_pv,
        quelle_url=f"https://www.openstreetmap.org/{osm_id}",
        google_maps_url=f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}",
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
    """Hauptfunktion: Sucht Gebäude mit ≥ min_flaeche_qm Dachfläche."""
    if lat is not None and lon is not None:
        logger.info(f"Verwende direkte Koordinaten: {lat:.4f}, {lon:.4f}")
    else:
        coords = geocodiere(ort)
        if coords is None:
            return []
        lat, lon = coords

    radius_m = radius_km * 1000
    logger.info(f"Starte Gebäude-Scan: {ort}, Radius {radius_km} km, Min. {min_flaeche_qm} m²")

    # 1. Gebäude laden
    abfrage = _baue_abfrage(lat, lon, radius_m)
    daten = get_json(OVERPASS_URL, params={"data": abfrage}, timeout=180.0)
    if not daten or "elements" not in daten:
        logger.error("Keine Daten von Overpass API erhalten")
        return []

    elemente = daten["elements"]
    logger.info(f"Overpass: {len(elemente)} Gebäude gefunden, berechne Flächen …")

    # 2. Leads filtern
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

    leads.sort(key=lambda l: l.dachflaeche_qm, reverse=True)
    logger.info(f"Scan: {len(leads)} Gebäude ≥ {min_flaeche_qm} m²")

    # 3. PV-Anlagen laden und zuordnen (nur wenn Leads vorhanden)
    if leads:
        logger.info("Lade bekannte PV-Anlagen aus OSM …")
        pv_koordinaten = _lade_pv_anlagen(lat, lon, radius_m)

        if pv_koordinaten:
            # Für jeden Lead ohne PV-Tag: prüfen ob eine PV-Anlage in ≤80m Nähe liegt
            PV_RADIUS = 80  # Meter
            zugeordnet = 0
            for lead in leads:
                if lead.hat_pv_anlage is True:
                    continue  # schon aus Tags bekannt
                nahe_pv = any(
                    _abstand_meter(lead.lat, lead.lon, pv_lat, pv_lon) <= PV_RADIUS
                    for pv_lat, pv_lon in pv_koordinaten
                )
                if nahe_pv:
                    lead.hat_pv_anlage = True
                    zugeordnet += 1
                else:
                    lead.hat_pv_anlage = False  # geprüft, keine gefunden

            logger.info(f"PV-Zuordnung: {zugeordnet} Gebäude haben bereits eine PV-Anlage")
        else:
            # Keine PV-Daten → alle als "keine" markieren (geprüft)
            for lead in leads:
                if lead.hat_pv_anlage is None:
                    lead.hat_pv_anlage = False

    logger.info(f"Scan abgeschlossen: {len(leads)} Leads")
    return leads
