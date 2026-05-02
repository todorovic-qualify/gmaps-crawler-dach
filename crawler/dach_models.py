"""
Datenmodell für Solar-Dach-Leads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DachLead:
    osm_id: str
    dachflaeche_qm: float

    # Gebäude-Info
    gebaeude_typ: Optional[str] = None       # building=* Tag
    gebaeude_nutzung: Optional[str] = None   # landuse/amenity/shop etc.

    # Identifikation
    name: Optional[str] = None               # name-Tag
    operator: Optional[str] = None           # operator-Tag
    brand: Optional[str] = None              # brand-Tag

    # Adresse
    adresse: Optional[str] = None
    stadt: Optional[str] = None
    postleitzahl: Optional[str] = None
    land: str = "DE"

    # Koordinaten
    lat: float = 0.0
    lon: float = 0.0

    # Kontaktdaten (aus OSM direkt)
    telefon: Optional[str] = None
    email: Optional[str] = None
    webseite: Optional[str] = None

    # PV-Anlage bereits vorhanden?
    hat_pv_anlage: Optional[bool] = None   # True=ja, False=nein, None=unbekannt

    # Angereicherte Kontaktdaten (via Website-Crawl)
    entscheidungstraeger: Optional[str] = None
    geschaeftsfuehrer: Optional[str] = None
    rechtlicher_name: Optional[str] = None
    gefundene_emails: list[str] = field(default_factory=list)
    gefundene_telefone: list[str] = field(default_factory=list)
    impressum_info: Optional[str] = None

    # Meta
    quelle_url: str = ""
    google_maps_url: str = ""

    def anzeigename(self) -> str:
        return self.name or self.operator or self.brand or f"Gebäude {self.osm_id}"

    def kontakt_vorhanden(self) -> bool:
        return bool(self.telefon or self.email or self.webseite or self.gefundene_emails or self.gefundene_telefone)

    def pv_status(self) -> str:
        if self.hat_pv_anlage is True:
            return "vorhanden"
        if self.hat_pv_anlage is False:
            return "keine"
        return "unbekannt"

    def to_csv_row(self) -> dict:
        return {
            "osm_id": self.osm_id,
            "name": self.name or "",
            "operator": self.operator or "",
            "brand": self.brand or "",
            "gebaeude_typ": self.gebaeude_typ or "",
            "gebaeude_nutzung": self.gebaeude_nutzung or "",
            "dachflaeche_qm": round(self.dachflaeche_qm, 1),
            "hat_pv_anlage": self.pv_status(),
            "adresse": self.adresse or "",
            "postleitzahl": self.postleitzahl or "",
            "stadt": self.stadt or "",
            "telefon": self.telefon or "",
            "email": self.email or (self.gefundene_emails[0] if self.gefundene_emails else ""),
            "alle_emails": "; ".join(self.gefundene_emails),
            "alle_telefone": "; ".join(self.gefundene_telefone),
            "webseite": self.webseite or "",
            "geschaeftsfuehrer": self.geschaeftsfuehrer or self.entscheidungstraeger or "",
            "rechtlicher_name": self.rechtlicher_name or "",
            "impressum_info": (self.impressum_info or "")[:300],
            "quelle_url": self.quelle_url,
            "google_maps_url": self.google_maps_url,
            "kontakt_vorhanden": self.kontakt_vorhanden(),
        }
