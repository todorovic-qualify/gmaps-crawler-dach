"""
HTML-Parsing-Hilfsfunktionen.

Konvention in Docstrings:
  [FAKT]      = direkt aus HTML extrahiert
  [SIGNAL]    = durch Muster-Matching erkannt
  [HEURISTIK] = aus indirekten Indikatoren geschlossen
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

# ── Regex-Muster ──────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Telefon: deutsch + international, flexibel formatiert
TELEFON_RE = re.compile(
    r"(?:Tel(?:efon)?\.?|Fon|Phone|☎|📞)[\s:]*"
    r"((?:\+49|0049|0)[\s.\-/]?\(?\d{2,5}\)?[\s.\-/]?\d{3,}[\s.\-/]?\d{0,6})",
    re.I,
)
TELEFON_PLAIN_RE = re.compile(
    r"(?<!\d)(?:\+49|0049|\(0\))?[\s.\-]?\(?\d{2,5}\)?[\s.\-/]\d{3,}(?:[\s.\-/]\d{2,5}){0,3}(?!\d)"
)

# Matcht vollständige Social-Media-URLs direkt im HTML-Quellcode.
# Gruppe 0 = volle URL (wird zurückgegeben).
SOCIAL_DOMAIN_RE: dict[str, re.Pattern] = {
    "instagram": re.compile(
        r'https?://(?:www\.)?instagram\.com/'
        r'(?!p/|explore/|reel/|stories/|_u/)([^/?#"\'>\s]{2,})',
        re.I,
    ),
    "facebook": re.compile(
        r'https?://(?:www\.)?facebook\.com/'
        r'(?!sharer|share|dialog|plugins|tr\?)([^/?#"\'>\s]{2,})',
        re.I,
    ),
    "linkedin": re.compile(
        r'https?://(?:www\.)?linkedin\.com/(?:in|company)/([^/?#"\'>\s]{2,})',
        re.I,
    ),
    "tiktok": re.compile(
        r'https?://(?:www\.)?tiktok\.com/@([^/?#"\'>\s]{2,})',
        re.I,
    ),
    "youtube": re.compile(
        r'https?://(?:www\.)?youtube\.com/(?:channel|user|@c?)([^/?#"\'>\s]{2,})',
        re.I,
    ),
}

# [HEURISTIK] Veraltete Website-Indikatoren
VERALTET_PATTERNS = [
    re.compile(r"©\s*20(?:0\d|1[0-5])\b"),                           # Copyright 2000-2015
    re.compile(r"copyright\s+20(?:0\d|1[0-5])\b", re.I),
    re.compile(r"flash|macromedia|ms\s?frontpage|dreamweaver", re.I),
    re.compile(r"<!--\[if\s+(?:lt\s+)?IE\s*\d", re.I),               # IE-Conditionals
    re.compile(r'<meta\s+http-equiv=["\']X-UA-Compatible["\']', re.I),
    re.compile(r"table\s+width=[\"\']\d+%?[\"\']\s+cellpadding", re.I),  # Table-Layout
    re.compile(r"font\s+face=[\"\']\w+[\"\']\s+color=", re.I),        # Font-Tags
]

# [SIGNAL] CTA-Schlüsselwörter
CTA_KEYWORDS = [
    # Deutsch
    "jetzt anfragen", "jetzt buchen", "termin buchen", "termin vereinbaren",
    "termin anfragen", "kostenlos testen", "jetzt kontaktieren",
    "angebot anfordern", "jetzt anrufen", "rückruf anfordern",
    "rückruf anfragen", "kontakt aufnehmen", "jetzt bestellen",
    "kostenlose beratung", "beratung anfragen", "probetraining",
    "erstgespräch", "unverbindlich anfragen", "jetzt starten",
    # Englisch
    "book now", "get a quote", "contact us", "schedule", "appointment",
    "free consultation", "get started", "request a call",
]

# [SIGNAL] Buchungs-Schlüsselwörter und Widget-Fingerprints
BUCHUNGS_PATTERNS = [
    # Keywords
    re.compile(r"online\s*buch", re.I),
    re.compile(r"termin\s*online", re.I),
    re.compile(r"reservier", re.I),
    re.compile(r"book\s+(?:an?\s+)?appointment", re.I),
    re.compile(r"online\s+booking", re.I),
    # Widget-Fingerprints
    re.compile(r"calendly\.com", re.I),
    re.compile(r"bookingkit", re.I),
    re.compile(r"treatwell", re.I),
    re.compile(r"timify", re.I),
    re.compile(r"shore\.com|shore-booking", re.I),
    re.compile(r"appointy|setmore|acuityscheduling", re.I),
    re.compile(r"doctolib", re.I),
    re.compile(r"jameda\.de", re.I),
    re.compile(r"zocdoc", re.I),
    re.compile(r"widget.*reserv|reserv.*widget", re.I),
]

# [SIGNAL] WhatsApp-Fingerprints
WHATSAPP_PATTERNS = [
    re.compile(r"wa\.me/", re.I),
    re.compile(r"api\.whatsapp\.com/send", re.I),
    re.compile(r'href=["\'][^"\']*whatsapp', re.I),
    re.compile(r"whatsapp\s*(?:chat|button|kontakt|schreiben|uns)", re.I),
]

# [SIGNAL] Chat/KI-Widget-Fingerprints
CHAT_WIDGET_PATTERNS = [
    re.compile(r"tawk\.to|tawkto", re.I),
    re.compile(r"crisp\.chat|crispcdn", re.I),
    re.compile(r"intercom(?:\.io)?", re.I),
    re.compile(r"drift\.com|driftt\.com", re.I),
    re.compile(r"livechat(?:inc)?\.com", re.I),
    re.compile(r"zendesk(?:\.com)?.*chat|zopim", re.I),
    re.compile(r"tidio(?:\.com|cdn)", re.I),
    re.compile(r"hubspot.*chat|hs-analytics", re.I),
    re.compile(r"freshchat|freshdesk", re.I),
    re.compile(r"smartsupp", re.I),
    re.compile(r"userlike", re.I),
    re.compile(r"chatbot|chat-bot|chatwidget", re.I),
]

# [SIGNAL] Kontaktformular-Fingerprints
KONTAKTFORMULAR_PATTERNS = [
    re.compile(r'<form[^>]+(?:contact|kontakt|anfrage|message|nachricht)', re.I),
    re.compile(r'class=["\'][^"\']*(?:contact|kontakt|wpcf7|gform|ninja-form|cf7)[^"\']*["\']', re.I),
    re.compile(r'id=["\'][^"\']*(?:contact|kontakt|contactform)[^"\']*["\']', re.I),
    re.compile(r'action=["\'][^"\']*(?:contact|anfrage|formspree|formcarry)[^"\']*["\']', re.I),
]

# Geschäftsführer / Inhaber aus Impressum
ENTSCHEIDUNGSTRAEGER_RE = [
    re.compile(
        r"(?:geschäftsführer(?:in)?|inhaber(?:in)?|vorstand|ceo|"
        r"managing\s+director|vertreten\s+durch|verantwortlich|"
        r"gründer(?:in)?|founder)\s*:?\s*"
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.I | re.MULTILINE,
    ),
    # "Inh.: Max Mustermann" oder "Inh. Max Mustermann"
    re.compile(
        r"\bInh\.?\s*:?\s*([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.MULTILINE,
    ),
]

# Speziell: Geschäftsführer-Name (höhere Präzision)
GESCHAEFTSFUEHRER_RE = [
    # "Geschäftsführer: Max Mustermann" / "Geschäftsführerin: ..."
    re.compile(
        r"Gesch[äa]ftsf[üu]hrer(?:in)?\s*[:\-]\s*"
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ]?[a-zäöüß\-]+)*\s+[A-ZÄÖÜ][a-zäöüß\-]+)",
        re.MULTILINE,
    ),
    # "GF: Max Mustermann"
    re.compile(
        r"\bGF\s*[:\-]\s*([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.MULTILINE,
    ),
    # "vertreten durch: Max Mustermann" / "Vertreten durch Geschäftsführer Max Mustermann"
    re.compile(
        r"[Vv]ertreten\s+durch\s+(?:(?:den\s+)?Gesch[äa]ftsf[üu]hrer\s+)?"
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.MULTILINE,
    ),
    # "Inhaber: Max Mustermann"
    re.compile(
        r"Inhaber(?:in)?\s*[:\-]\s*"
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.MULTILINE,
    ),
    # "Inh.: Max Mustermann"
    re.compile(
        r"\bInh\.?\s*[:\-]\s*([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.MULTILINE,
    ),
    # CEO / Managing Director
    re.compile(
        r"\b(?:CEO|Managing\s+Director)\s*[:\-]\s*"
        r"([A-ZÄÖÜ][a-zäöüß\-]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-]+){1,3})",
        re.I | re.MULTILINE,
    ),
]

# Rechtlicher Firmenname
RECHTLICHER_NAME_RE = [
    re.compile(
        r"([A-ZÄÖÜ][A-Za-zäöüÄÖÜß\s&\.\-]+(?:GmbH|UG|AG|OHG|KG|GbR|e\.K\.|e\.V\.|mbH)(?:\s*&\s*Co\.?\s*KG)?)",
        re.MULTILINE,
    ),
    re.compile(
        r"Firmenname\s*:?\s*(.+?)(?:\n|<br)", re.I | re.MULTILINE
    ),
]

# Technologie-Stack-Fingerprints (HEURISTIK / FAKT hybrid)
TECHNOLOGIE_MAP = [
    ("WordPress",   [r"wp-content", r"wp-includes", r"/wp-json/"]),
    ("Shopify",     [r"shopify\.com", r"cdn\.shopify", r'"Shopify"']),
    ("Wix",         [r"wix\.com", r"wixsite\.com", r"wix-code"]),
    ("Squarespace", [r"squarespace\.com", r"sqsp\.net"]),
    ("Jimdo",       [r"jimdo\.com", r"jimdocontent"]),
    ("Weebly",      [r"weebly\.com", r"editmysite\.com"]),
    ("TYPO3",       [r"typo3", r"EXT:form"]),
    ("Joomla",      [r"/joomla", r'content="Joomla']),
    ("Drupal",      [r"drupal\.js", r'content="Drupal']),
    ("Bootstrap",   [r"bootstrap\.min\.css", r"bootstrap\.bundle"]),
    ("React",       [r"__NEXT_DATA__", r"react\.production", r'id="__next"']),
    ("Vue",         [r"vue\.min\.js", r"__VUE__"]),
    ("Webflow",     [r"webflow\.com", r"data-wf-page"]),
]


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# [FAKT] E-Mail-Extraktion
def extrahiere_emails(html_oder_text: str) -> list[str]:
    gefunden = EMAIL_RE.findall(html_oder_text)
    ignoriere_endungen = {".png", ".jpg", ".gif", ".svg", ".webp", ".ico", ".woff"}
    ignoriere_domains = {"example", "domain", "yourdomain", "mustermann", "ihre-domain"}
    bereinigt = []
    for e in gefunden:
        e_lower = e.lower()
        if any(e_lower.endswith(ext) for ext in ignoriere_endungen):
            continue
        domain = e_lower.split("@")[-1].split(".")[0]
        if domain in ignoriere_domains:
            continue
        bereinigt.append(e_lower)
    return list(dict.fromkeys(bereinigt))


# [FAKT] Telefon-Extraktion
def extrahiere_telefon(text: str) -> Optional[str]:
    # Erst mit Kontext-Label (Tel.: 0621 ...)
    m = TELEFON_RE.search(text)
    if m:
        nummer = m.group(1).strip()
        ziffern = re.sub(r"\D", "", nummer)
        if len(ziffern) >= 7:
            return nummer

    # Dann einfaches Muster
    treffer = TELEFON_PLAIN_RE.findall(text)
    for t in treffer:
        t = t.strip()
        ziffern = re.sub(r"\D", "", t)
        if 7 <= len(ziffern) <= 15:
            return t
    return None


# [FAKT] Social Links – matcht volle URLs direkt im Quellcode
def extrahiere_social_links(html: str) -> dict[str, str]:
    """
    Gibt {plattform: volle_url} zurück.
    Sucht direkt nach vollständigen https://…-URLs im HTML-Quelltext.
    """
    links: dict[str, str] = {}
    for plattform, pattern in SOCIAL_DOMAIN_RE.items():
        m = pattern.search(html)
        if m:
            # m.group(0) ist die vollständige URL (kein href= drum herum)
            links[plattform] = m.group(0)
    return links


# [FAKT] Meta-Informationen
def extrahiere_meta(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    desc = None
    meta = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    if meta and isinstance(meta, Tag):
        desc = meta.get("content", "")
        desc = desc.strip() if desc else None

    return title or None, desc or None


# [FAKT] Technologie-Stack
def extrahiere_technologie_stack(html: str) -> Optional[str]:
    gefunden = []
    for name, muster_liste in TECHNOLOGIE_MAP:
        if any(re.search(m, html) for m in muster_liste):
            gefunden.append(name)
    return ", ".join(gefunden) if gefunden else None


# [SIGNAL] Kontaktformular
# Muster-Match auf bekannte Form-Fingerprints; Fallback: <form> mit einem
# <input type="text"> und einem <textarea> gilt als Kontaktformular.
def hat_kontaktformular(html: str) -> bool:
    html_lower = html.lower()
    if "<form" not in html_lower:
        return False
    # Explizite Fingerprints
    if any(p.search(html) for p in KONTAKTFORMULAR_PATTERNS):
        return True
    # Fallback: form + textarea + text-input = sehr wahrscheinlich Kontaktformular
    hat_textarea = "<textarea" in html_lower
    hat_input = bool(re.search(r'<input[^>]+type=["\'](?:text|email)["\']', html_lower))
    return hat_textarea and hat_input


# [SIGNAL] CTA
def hat_cta(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    return any(k in text for k in CTA_KEYWORDS)


# [SIGNAL] Buchungssystem
def hat_buchungssignal(html: str, soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True)
    return any(p.search(html) or p.search(text) for p in BUCHUNGS_PATTERNS)


# [SIGNAL] WhatsApp
def hat_whatsapp(html: str) -> bool:
    return any(p.search(html) for p in WHATSAPP_PATTERNS)


# [SIGNAL] Chat-/KI-Widget
def hat_chat_widget(html: str) -> bool:
    return any(p.search(html) for p in CHAT_WIDGET_PATTERNS)


# [SIGNAL] Newsletter
def hat_newsletter(html: str, soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    keywords = ["newsletter", "e-mail abonnieren", "email abonnieren", "anmelden", "subscribe"]
    return any(k in text for k in keywords) and "<form" in html.lower()


# [HEURISTIK] Veraltete Website
def sieht_veraltet_aus(html: str) -> bool:
    return any(p.search(html) for p in VERALTET_PATTERNS)


# [HEURISTIK] Fehlender Mobile-Viewport
def fehlt_mobile_viewport(html: str) -> bool:
    return not bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I))


# [HEURISTIK] Baukastenseite
def ist_baukastenseite(stack: Optional[str]) -> bool:
    if not stack:
        return False
    return any(b in stack for b in ["Wix", "Jimdo", "Squarespace", "Weebly"])


# [HEURISTIK] Schwache Seitenstruktur
def hat_schwache_struktur(soup: BeautifulSoup, anzahl_seiten: int) -> bool:
    nav = soup.find("nav")
    menu_links = soup.find_all("a", href=True)
    zu_wenig_seiten = anzahl_seiten <= 2
    kein_nav = nav is None
    wenig_links = len(menu_links) < 5
    return zu_wenig_seiten and (kein_nav or wenig_links)


# [FAKT] Interne Links für Unterseiten-Crawling
# Substring-Suche im Pfad – flexibler als exakter Teilstring-Match
_INTERESSANTE_PFAD_FRAGMENTE = [
    "impressum", "kontakt", "contact", "about",
    "ueber-uns", "ueber_uns", "ueber",
    "team", "leistungen", "services", "angebot",
    "leistung", "service",
]

def extrahiere_interne_links(soup: BeautifulSoup, basis_url: str) -> list[str]:
    """
    [FAKT] Gibt interne URLs zurück, deren Pfad auf eine für
    die Anreicherung relevante Unterseite hindeutet.
    """
    basis_host = urlparse(basis_url).netloc
    gefunden = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolut = urljoin(basis_url, href)
        parsed = urlparse(absolut)
        if parsed.netloc != basis_host:
            continue
        pfad = parsed.path.lower()
        if any(frag in pfad for frag in _INTERESSANTE_PFAD_FRAGMENTE):
            gefunden.append(absolut)
    return list(dict.fromkeys(gefunden))


# [FAKT] Entscheidungsträger aus Impressum
def extrahiere_entscheidungstraeger(text: str) -> Optional[str]:
    for pattern in ENTSCHEIDUNGSTRAEGER_RE:
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            # Plausibilitätsprüfung: min. 2 Wörter, keine Zahlen
            if " " in name and not re.search(r"\d", name):
                return name
    return None


# [FAKT] Geschäftsführer speziell aus Impressum
def extrahiere_geschaeftsfuehrer(text: str) -> Optional[str]:
    """Sucht gezielt nach Geschäftsführer/Inhaber-Name im Impressumstext."""
    for pattern in GESCHAEFTSFUEHRER_RE:
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            # Plausibilitätsprüfung: 2-4 Wörter, keine Zahlen, nicht zu kurz
            woerter = name.split()
            if 2 <= len(woerter) <= 4 and not re.search(r"\d", name) and len(name) >= 5:
                return name
    return None


# [FAKT] Rechtlicher Firmenname aus Impressum
def extrahiere_rechtlicher_name(text: str) -> Optional[str]:
    for pattern in RECHTLICHER_NAME_RE:
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            if 3 < len(name) < 100:
                return name
    return None


# [FAKT] Sauberer Text mit trafilatura (wenn verfügbar) oder Fallback
def extrahiere_haupttext(html: str, max_zeichen: int = 800) -> Optional[str]:
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text:
            return bereinige_text(text, max_zeichen)
    except ImportError:
        pass

    # Fallback: BeautifulSoup
    soup = parse_html(html)
    # Störende Elemente entfernen
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return bereinige_text(text, max_zeichen) if text else None


# [FAKT] Leistungen aus strukturiertem HTML extrahieren
def extrahiere_leistungen_liste(soup: BeautifulSoup) -> list[str]:
    """Versucht eine strukturierte Leistungsliste zu extrahieren."""
    leistungen = []

    # Aus <ul> / <li> in Leistungs-Abschnitten
    for section in soup.find_all(["section", "div", "article"]):
        text = section.get_text().lower()
        if any(k in text for k in ["leistung", "service", "angebot", "was wir"]):
            for li in section.find_all("li"):
                item = li.get_text(strip=True)
                if 3 < len(item) < 80 and not re.search(r"(cookie|datenschutz|impressum)", item, re.I):
                    leistungen.append(item)

    # Aus <h2>/<h3> Headlines als Leistungsübersicht
    if not leistungen:
        for h in soup.find_all(["h2", "h3"]):
            text = h.get_text(strip=True)
            if 3 < len(text) < 60:
                leistungen.append(text)

    # Max. 10 Einträge, dedupliziert
    gesehen = set()
    eindeutig = []
    for item in leistungen:
        key = item.lower()
        if key not in gesehen:
            gesehen.add(key)
            eindeutig.append(item)
    return eindeutig[:10]


def bereinige_text(text: str, max_zeichen: int = 500) -> str:
    bereinigt = " ".join(text.split())
    return bereinigt[:max_zeichen].rstrip() if len(bereinigt) > max_zeichen else bereinigt


# ── Brancheneinordnung ────────────────────────────────────────────────────────

# [HEURISTIK] Kategorie → Branchenbegriffe
_KATEGORIE_BRANCHEN: dict[str, list[str]] = {
    "restaurant":          ["Gastronomie", "Foodservice"],
    "cafe":                ["Gastronomie", "Café & Bäckerei"],
    "bar":                 ["Gastronomie", "Nachtgastronomie"],
    "friseur":             ["Beauty & Wellness", "Friseur"],
    "schoenheitssalon":    ["Beauty & Wellness", "Kosmetik"],
    "nagelstudio":         ["Beauty & Wellness", "Nageldesign"],
    "barber":              ["Beauty & Wellness", "Barbershop"],
    "zahnarzt":            ["Gesundheit", "Zahnmedizin"],
    "arzt":                ["Gesundheit", "Medizin"],
    "physiotherapeut":     ["Gesundheit", "Physiotherapie"],
    "fitnessstudio":       ["Sport & Fitness"],
    "hotel":               ["Hotellerie & Tourismus"],
    "immobilien":          ["Immobilien"],
    "handwerker":          ["Handwerk & Bau"],
    "elektriker":          ["Handwerk & Bau", "Elektrotechnik"],
    "klempner":            ["Handwerk & Bau", "Sanitär"],
    "dachdecker":          ["Handwerk & Bau", "Dachdeckerei"],
    "solar":               ["Energie & Umwelt", "Photovoltaik"],
    "heizung":             ["Handwerk & Bau", "Heizungstechnik"],
    "autowerkstatt":       ["KFZ & Mobilität"],
    "anwalt":              ["Recht & Beratung", "Kanzlei"],
    "steuerberater":       ["Recht & Beratung", "Steuern & Finanzen"],
    "unternehmensberater": ["Beratung & Consulting"],
    "einzelhandel":        ["Einzelhandel & Verkauf"],
}

# Branchen-Keywords die im Seitentext auf Spezialgebiete hinweisen
_BRANCHEN_KEYWORD_MAP: list[tuple[str, str]] = [
    ("hochzeit|heirat|braut",          "Hochzeitsbranche"),
    ("kind|kinder|baby|pediatr",       "Kinder & Familie"),
    ("tier|hund|katze|veterinär",      "Tiermedizin"),
    ("sport|fitness|yoga|pilates",     "Sport & Wellness"),
    ("digital|online|software|app",    "Digitale Dienste"),
    ("pflege|senio|alten",             "Pflege & Soziales"),
    ("bau|bauprojekt|architekt",       "Bau & Architektur"),
    ("ausbildung|kurs|schulung|coach", "Bildung & Coaching"),
    ("transport|logistik|lieferung",   "Logistik & Transport"),
    ("bio|nachhaltig|öko|vegan",       "Nachhaltigkeit"),
]


def leite_branchen_ab(kategorie: Optional[str], text: str) -> list[str]:
    """
    [HEURISTIK] Leitet Branchenbegriffe aus Kategorie + Seiteninhalt ab.
    Gibt eine deduplizierte, sortierte Liste zurück.
    """
    branchen: list[str] = []

    # 1. Direkt aus Kategorie
    if kategorie:
        branchen.extend(_KATEGORIE_BRANCHEN.get(kategorie, []))

    # 2. Keyword-Scan im Text (Leistungen / Über-uns)
    text_lower = text.lower() if text else ""
    for muster, branche in _BRANCHEN_KEYWORD_MAP:
        if branche not in branchen and re.search(muster, text_lower):
            branchen.append(branche)

    return list(dict.fromkeys(branchen))  # dedupliziert, Reihenfolge behalten


# ── Sichtbare Schwächen ───────────────────────────────────────────────────────

def identifiziere_sichtbare_schwaechen(
    hat_webseite: bool,
    # Signale
    cta_gefunden: bool,
    kontaktformular_gefunden: bool,
    buchungs_signal_gefunden: bool,
    whatsapp_gefunden: bool,
    chat_widget_gefunden: bool,
    # Heuristiken
    sieht_veraltet_aus: bool,
    fehlt_mobile_viewport: bool,
    fehlt_ssl: bool,
    baukastenseite: bool,
    schwache_struktur: bool,
    technologie_stack: Optional[str] = None,
) -> list[str]:
    """
    [HEURISTIK] Gibt eine Liste sichtbarer Schwächen zurück.
    Jede Schwäche ist direkt aus Website-Beobachtungen ableitbar –
    keine Scoring-Annahmen, keine Kategorisierungslogik.
    """
    schwaechen: list[str] = []

    if not hat_webseite:
        schwaechen.append("Kein Online-Auftritt vorhanden")
        return schwaechen  # weitere Prüfungen sinnlos

    if sieht_veraltet_aus:
        schwaechen.append("Website wirkt veraltet (altes Copyright, veraltete Technologien)")

    if fehlt_mobile_viewport:
        schwaechen.append("Kein Mobile-Viewport – wahrscheinlich nicht mobiloptimiert")

    if fehlt_ssl:
        schwaechen.append("Kein HTTPS – unsichere Verbindung, schlechtes Google-Ranking-Signal")

    if baukastenseite:
        stack = f" ({technologie_stack})" if technologie_stack else ""
        schwaechen.append(f"Baukastenseite{stack} – begrenzte Anpassbarkeit und Professionalität")

    if schwache_struktur:
        schwaechen.append("Schwache Seitenstruktur – wenige Unterseiten oder keine Navigation erkennbar")

    if not cta_gefunden:
        schwaechen.append("Kein Call-to-Action – Besucher werden nicht zur Handlung aufgefordert")

    if not kontaktformular_gefunden:
        schwaechen.append("Kein Kontaktformular – Kontaktaufnahme ist umständlich")

    if not buchungs_signal_gefunden:
        schwaechen.append("Keine Online-Buchungsmöglichkeit erkannt")

    if not whatsapp_gefunden:
        schwaechen.append("Kein WhatsApp-Kontakt angeboten")

    if not chat_widget_gefunden:
        schwaechen.append("Kein Live-Chat oder Chat-Widget vorhanden")

    return schwaechen


# ── Konversionsqualität ───────────────────────────────────────────────────────

def bewerte_konversions_qualitaet(
    hat_webseite: bool,
    cta_gefunden: bool,
    kontaktformular_gefunden: bool,
    buchungs_signal_gefunden: bool,
    sieht_veraltet_aus: bool,
    fehlt_mobile_viewport: bool,
) -> str:
    """
    [HEURISTIK] Gibt eine von vier Qualitätsstufen zurück:
    'stark' | 'mittel' | 'schwach' | 'fehlt'

    Basiert ausschließlich auf beobachteten Signalen – kein Lead-Score.
    """
    if not hat_webseite:
        return "fehlt"

    punkte = 0
    if cta_gefunden:
        punkte += 2
    if kontaktformular_gefunden:
        punkte += 2
    if buchungs_signal_gefunden:
        punkte += 2
    if not sieht_veraltet_aus:
        punkte += 1
    if not fehlt_mobile_viewport:
        punkte += 1

    if punkte >= 6:
        return "stark"
    if punkte >= 3:
        return "mittel"
    return "schwach"


# ── Zusammenfassung ───────────────────────────────────────────────────────────

def generiere_zusammenfassung(
    name: str,
    kategorie: Optional[str],
    meta_beschreibung: Optional[str],
    ueber_uns_text: Optional[str],
    leistungen_text: Optional[str],
    stadt: Optional[str] = None,
) -> str:
    """
    [GENERIERT] Erstellt eine kurze Firmenbeschreibung (max. 2 Sätze).
    Priorität: Über-uns-Seite > Meta-Description > konstruiert aus Stammdaten.
    Klar als generiert markiert – keine erfundenen Fakten.
    """
    # Priorität 1: Über-uns-Text (ersten Satz extrahieren)
    if ueber_uns_text and len(ueber_uns_text.strip()) > 40:
        saetze = re.split(r"(?<=[.!?])\s+", ueber_uns_text.strip())
        # Ersten zwei sinnvollen Sätze nehmen
        kandidaten = [s for s in saetze if len(s) > 25][:2]
        if kandidaten:
            return " ".join(kandidaten)

    # Priorität 2: Meta-Description
    if meta_beschreibung and len(meta_beschreibung.strip()) > 30:
        return bereinige_text(meta_beschreibung, 250)

    # Priorität 3: Konstruiert aus Stammdaten (klar als Fallback)
    ort_teil = f" in {stadt}" if stadt else ""
    kat_label = _kategorie_zu_label(kategorie)
    leistungs_teil = ""
    if leistungen_text:
        kurz = bereinige_text(leistungen_text, 80)
        leistungs_teil = f" Angeboten werden unter anderem: {kurz}."

    return f"{name} ist {kat_label}{ort_teil}.{leistungs_teil}"


def _kategorie_zu_label(kategorie: Optional[str]) -> str:
    """Wandelt internes Kategorie-Kürzel in lesbaren deutschen Text um."""
    mapping = {
        "restaurant": "ein Restaurant",
        "cafe": "ein Café",
        "bar": "eine Bar",
        "friseur": "ein Friseursalon",
        "schoenheitssalon": "ein Schönheitssalon",
        "nagelstudio": "ein Nagelstudio",
        "barber": "ein Barbershop",
        "zahnarzt": "eine Zahnarztpraxis",
        "arzt": "eine Arztpraxis",
        "physiotherapeut": "eine Physiotherapie-Praxis",
        "fitnessstudio": "ein Fitnessstudio",
        "hotel": "ein Hotel",
        "immobilien": "ein Immobilienbüro",
        "handwerker": "ein Handwerksbetrieb",
        "elektriker": "ein Elektrobetrieb",
        "klempner": "ein Sanitärbetrieb",
        "dachdecker": "ein Dachdeckerbetrieb",
        "solar": "ein Solartechnik-Unternehmen",
        "heizung": "ein Heizungsbauunternehmen",
        "autowerkstatt": "eine Autowerkstatt",
        "anwalt": "eine Anwaltskanzlei",
        "steuerberater": "eine Steuerberatungskanzlei",
        "unternehmensberater": "ein Beratungsunternehmen",
        "einzelhandel": "ein Einzelhandelsgeschäft",
    }
    return mapping.get(kategorie or "", "ein lokales Unternehmen")
