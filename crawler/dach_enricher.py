"""
Anreicherung von DachLeads via Website-Scraping.
Sucht Telefon, E-Mail, Impressum-Daten, Entscheidungsträger.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from loguru import logger

from crawler.dach_models import DachLead
from crawler.utils.http_utils import get, erstelle_client
from crawler.utils.parse_utils import (
    bereinige_text,
    extrahiere_emails,
    extrahiere_entscheidungstraeger,
    extrahiere_rechtlicher_name,
    extrahiere_telefon,
    parse_html,
)

PRIORITAETS_PFADE = ["/impressum", "/kontakt", "/contact", "/about", "/ueber-uns"]


def reichere_dachlead_an(lead: DachLead) -> DachLead:
    """
    Crawlt die Website des Leads und ergänzt Kontaktdaten.
    Gibt das Lead-Objekt zurück (mutiert + return).
    """
    if not lead.webseite:
        return lead

    basis_url = lead.webseite
    if not basis_url.startswith("http"):
        basis_url = "https://" + basis_url
    basis_url = basis_url.rstrip("/")

    logger.info(f"Anreicherung: {lead.anzeigename()} → {basis_url}")

    try:
        with erstelle_client() as client:
            # Startseite
            html = _lade(basis_url, client)
            if html:
                _extrahiere_kontakte(lead, html)

            # Prioritätspfade
            for pfad in PRIORITAETS_PFADE:
                url = urljoin(basis_url, pfad)
                html = _lade(url, client)
                if not html:
                    continue
                _extrahiere_kontakte(lead, html)

                # Impressum-spezifisch
                if "impressum" in pfad or "legal" in pfad:
                    soup = parse_html(html)
                    text = soup.get_text(" ", strip=True)
                    if not lead.rechtlicher_name:
                        lead.rechtlicher_name = extrahiere_rechtlicher_name(text)
                    if not lead.entscheidungstraeger:
                        lead.entscheidungstraeger = extrahiere_entscheidungstraeger(text)
                    if not lead.impressum_info:
                        lead.impressum_info = bereinige_text(text, 600)

    except Exception as e:
        logger.warning(f"Anreicherung fehlgeschlagen für {lead.anzeigename()}: {e}")

    return lead


def _lade(url: str, client) -> Optional[str]:
    try:
        resp = get(url, client=client)
        if resp and resp.status_code == 200:
            ct = resp.headers.get("content-type", "")
            if "text/html" in ct or "text/plain" in ct:
                return resp.text
    except Exception:
        pass
    return None


def _extrahiere_kontakte(lead: DachLead, html: str) -> None:
    """Ergänzt fehlende Kontaktdaten aus HTML."""
    # E-Mails
    emails = extrahiere_emails(html)
    for e in emails:
        if e not in lead.gefundene_emails:
            lead.gefundene_emails.append(e)
    if not lead.email and emails:
        lead.email = emails[0]

    # Telefon
    if not lead.telefon:
        soup = parse_html(html)
        tel = extrahiere_telefon(soup.get_text(" ", strip=True))
        if tel:
            lead.telefon = tel
            if tel not in lead.gefundene_telefone:
                lead.gefundene_telefone.append(tel)
