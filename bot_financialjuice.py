#!/usr/bin/env python3
"""Bot Telegram : renvoie les nouveaux titres du flux RSS FinancialJuice dans un groupe privé.

Usage (depuis ce dossier) :
    python3 bot_financialjuice.py --chat-id   affiche l'identifiant du groupe (après /start dans le groupe)
    python3 bot_financialjuice.py --dry       lit le flux et affiche les titres, sans rien envoyer
    python3 bot_financialjuice.py --demo      envoie des titres d'exemple (rouge, majuscules, tri US)
    python3 bot_financialjuice.py --test      envoie un message de test dans le groupe
    python3 bot_financialjuice.py             lance le bot (Ctrl+C pour arrêter)

Les clés sont lues dans config.env (jamais dans le code).
Usage strictement privé : ne republie pas ces titres sur un canal public.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.env")
SEEN_PATH = os.path.join(HERE, "seen.json")
INTERVAL = 90          # secondes entre deux lectures du flux (le site limite les lectures trop fréquentes)
MAX_WAIT = 900         # attente maximale après un refus 429 (15 min)
KEEP = 500             # nombre d'identifiants mémorisés
UA = "Mozilla/5.0 (compatible; TradixPrivateBot/1.0)"


def load_config():
    cfg = dict(os.environ)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return cfg


CFG = load_config()
# Mode "cycle" (hébergement GitHub) : le bot tourne N secondes puis s'arrête, relancé toutes les 5 minutes.
BOT_DIR = os.path.join(HERE, CFG.get("BOT_DIR", "")) if CFG.get("BOT_DIR") else HERE  # dossier des listes de ce bot
os.makedirs(BOT_DIR, exist_ok=True)
SEEN_PATH = os.path.join(BOT_DIR, "seen.json")
DEADLINE = time.time() + int(CFG["CYCLE_SECONDS"]) if CFG.get("CYCLE_SECONDS") else None
FEED_URL = CFG.get("FEED_URL", "https://www.financialjuice.com/feed.ashx?xy=rss")
TG_API = CFG.get("TG_API", "https://api.telegram.org")
TOKEN = CFG.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = CFG.get("TELEGRAM_CHAT_ID", "")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def http(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


FEED_CACHE = CFG.get("FEED_CACHE") or os.path.join(os.path.dirname(HERE), "feed_cache.xml")  # partagé entre les bots du même Mac
CACHE_TTL = 60  # secondes pendant lesquelles les bots se partagent la même lecture du flux


def read_feed():
    """Une seule lecture du flux pour tous les bots : on réutilise la copie récente si elle existe."""
    try:
        if time.time() - os.path.getmtime(FEED_CACHE) < CACHE_TTL:
            with open(FEED_CACHE, "rb") as f:
                data = f.read()
            if data:
                return data
    except OSError:
        pass
    data = http(FEED_URL)
    try:
        tmp = f"{FEED_CACHE}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, FEED_CACHE)
    except OSError:
        pass
    return data


def fetch_items():
    root = ET.fromstring(read_feed())
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        guid = (it.findtext("guid") or it.findtext("link") or title).strip()
        link = (it.findtext("link") or "").strip()
        if title and guid:
            try:  # heure de publication, dans le fuseau de ton Mac
                hhmm = parsedate_to_datetime(it.findtext("pubDate")).astimezone().strftime("%H:%M")
            except Exception:
                hhmm = ""
            desc = html.unescape(it.findtext("description") or "")  # détails (ex. MOO Imbalance : chiffres par indice)
            parts = re.split(r"<br\s*/?>|</?li[^>]*>|</?p[^>]*>|</?ul[^>]*>|</?ol[^>]*>|</?div[^>]*>|\n", desc, flags=re.I)
            details = [html.unescape(re.sub(r"<[^>]+>", "", l)).strip(" \u2022\u25AA-") for l in parts]
            title = re.sub(r"^FinancialJuice:\s*", "", title)
            # 'Trump: Said X...' (discours rapporté) -> 'Trump said X...' : traité comme une phrase, pas comme une citation
            # 'Trump: told X. Thinking about it' -> 'Trump, when told X: Thinking about it' (on lui dit X, il répond)
            title = re.sub(r"^([^:\d]{2,45}?):\s+(?:told|when told|asked about|asked if|asked whether)\s+(.+?)[.,;]\s+(.+)$",
                           lambda m: f"{m.group(1)}, when told {m.group(2)}: {m.group(3)}", title, flags=re.I)
            title = re.sub(r"^([^:\d]{2,45}?):\s+(said|says|added|adds|reiterates|reiterated|reportedly|has said)\b",
                           lambda m: f"{m.group(1)} {m.group(2).lower()}", title, flags=re.I)
            items.append({"id": guid, "title": title, "link": link, "time": hhmm,
                          "details": [d for d in details if d]})
    return items  # du plus récent au plus ancien


def tg(method, **params):
    url = f"{TG_API}/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    try:
        return json.loads(http(url, data))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(body)
        except ValueError:
            j = {"ok": False, "description": body}
        j["http"] = e.code
        return j


def send(text, silent=False):
    for _ in range(3):
        r = tg("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="HTML", disable_web_page_preview="true",
               disable_notification="true" if silent else "false")
        if r.get("ok"):
            return True
        wait = (r.get("parameters") or {}).get("retry_after")
        if r.get("http") == 429 and wait:
            time.sleep(int(wait) + 1)
            continue
        log(f"Telegram a refusé l'envoi : {r.get('description')}")
        return False
    return False


IGNORER_PATH = os.path.join(BOT_DIR, "ignorer.txt")
IMPORTANT_PATH = os.path.join(BOT_DIR, "important.txt")
SILENCIEUX = CFG.get("SILENCIEUX", "oui").lower() != "non"  # titres normaux sans sonnerie, importants avec

IGNORER_DEFAUT = [
    "Interest Rate Probabilities", "Implied Volatility", "Currency Strength", "Strength Chart",
]
IMPORTANT_DEFAUT = [
    "Fed", "FOMC", "Federal Reserve", "Powell", "rate decision", "rate cut", "rate hike",
    "NFP", "nonfarm", "payrolls", "ADP", "CPI", "PCE", "PPI", "inflation", "unemployment", "jobless",
    "ISM", "tariff", "tariffs", "Trump", "Treasury", "gold", "XAU",
    "Iran", "Israel", "Houthi", "missile", "sanctions", "shutdown", "emergency",
]
GARDER_PATH = os.path.join(BOT_DIR, "garder.txt")
FORT_PATH = os.path.join(BOT_DIR, "fort.txt")
EXCLURE_PATH = os.path.join(BOT_DIR, "exclure.txt")
ETIQUETTES_PATH = os.path.join(BOT_DIR, "etiquettes.txt")
RETIRER_PATH = os.path.join(BOT_DIR, "retirer.txt")
DEMO_PATH = os.path.join(BOT_DIR, "demo.txt")
RENOMMER_PATH = os.path.join(BOT_DIR, "renommer.txt")
GARDER_DEFAUT = [
    # États-Unis, banque centrale, dollar, taux
    "US", "U.S.", "USD", "DXY", "United States", "American", "America", "Fed", "FOMC", "Federal Reserve", "Powell",
    "Treasury", "Treasuries", "yield", "yields", "dollar", "Wall Street", "S&P 500", "Nasdaq", "Dow",
    "Trump", "White House", "tariff", "tariffs",
    # données américaines
    "NFP", "nonfarm", "payrolls", "ADP", "jobless", "unemployment", "CPI", "PCE", "PPI", "ISM", "Michigan",
    "Conference Board", "durable goods",
    # or
    "gold", "XAU", "bullion",
    # géopolitique qui bouge l'or
    "Iran", "Israel", "Middle East", "Houthi", "Russia", "Ukraine", "China", "OPEC",
]


def read_terms(path, defaults, titre, explication):
    """Lit une liste de mots (un par ligne). Crée le fichier avec des valeurs par défaut s'il manque."""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {titre}\n# {explication}\n# Une entrée par ligne, en anglais (comme dans les titres d'origine).\n"
                    "# Les lignes qui commencent par # sont ignorées. Modifie sans arrêter le bot.\n")
            f.write("\n".join(defaults) + "\n")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def has_term(terms, title):
    """Mot entier. Les sigles en majuscules (US, CPI...) sont sensibles à la casse, pour ne pas confondre US et us."""
    for x in terms:
        flags = 0 if (x.isupper() and len(x) <= 5) else re.IGNORECASE
        if re.search(r"(?<!\w)" + re.escape(x) + r"(?:s|es)?(?!\w)", title, flags):  # pluriel accepté (Houthi -> Houthis)
            return True
    return False


STRONG_US = [
    "US", "U.S.", "USA", "United States", "American", "Fed", "FOMC", "Federal Reserve", "Powell", "Treasury", "Treasuries",
    "Trump", "White House", "Wall Street", "S&P 500", "Nasdaq", "Dow", "NFP", "nonfarm", "ADP", "ISM", "Michigan",
    "Conference Board", "PCE", "jobless claims", "Jobless Claims", "durable goods", "Philadelphia", "Empire State",
    "Richmond", "Chicago PMI", "Waller", "Williams", "Kashkari", "Bowman", "Jefferson", "Barr", "Logan", "Goolsbee",
    "Bostic", "Musalem", "Schmid", "Hammack", "Daly", "Collins", "Barkin", "Harker", "Cook", "Miran",
]
NON_US = [
    "Eurozone", "Euro Zone", "Euro Area", "euro zone", "EU", "ECB", "German", "Germany", "France", "French", "Italian", "Italy",
    "Spain", "Spanish", "UK", "British", "BoE", "Japan", "Japanese", "BoJ", "Canada", "Canadian", "BoC", "Australia",
    "Australian", "RBA", "Swiss", "Switzerland", "SNB", "Sweden", "Swedish", "Norway", "Norwegian", "New Zealand", "RBNZ",
    "India", "Indian", "Brazil", "Mexico", "Mexican", "Turkey", "Turkish", "Taiwan", "Korea", "Korean", "Poland", "Polish",
    "Hungary", "Czech", "Netherlands", "Dutch", "Belgium", "Austria", "Portugal", "Greece", "Ireland", "Finland",
]


def is_wanted(title):
    """Si garder.txt contient des entrées, seuls les titres qui en contiennent une sont envoyés.
    Garde-fous : une donnée chiffrée doit être américaine, et un titre sur un autre pays est écarté sauf lien avec les États-Unis."""
    terms = read_terms(GARDER_PATH, GARDER_DEFAUT, "Sujets à suivre (concentration États-Unis et or)",
                       "Seuls les titres qui contiennent l'une de ces expressions sont envoyés. Fichier vide = tout est envoyé.")
    if not terms:
        return True
    strong = read_terms(FORT_PATH, STRONG_US, "Repères du marché suivi",
                        "Une donnée chiffrée n'est envoyée que si elle contient l'un de ces repères (pays, banque centrale, indice...).")
    other = read_terms(EXCLURE_PATH, NON_US, "Repères des autres marchés",
                       "Un titre qui contient l'un de ces mots est écarté, sauf s'il contient aussi un repère du marché suivi.")
    us = has_term(strong, title)
    if BLOCK_PARTS.search(title) and not us:  # donnée chiffrée sans marqueur américain (ex. PPI zone euro)
        return False
    if has_term(other, title) and not us:  # autre pays, sans lien avec les États-Unis
        return False
    return has_term(terms + strong, title)


def is_ignored(title):
    terms = read_terms(IGNORER_PATH, IGNORER_DEFAUT, "Titres à ne pas envoyer",
                       "Si le titre contient l'une de ces expressions, il est ignoré.")
    t = title.lower()
    return any(x.lower() in t for x in terms)


def to_float(x):
    m = re.search(r"-?\d+(?:[.,]\d+)?", x or "")
    return float(m.group(0).replace(",", ".")) if m else None


def is_surprise(title):
    """Chiffre publié très différent de la prévision (ex. PMI 54.2 contre 51.7 attendu)."""
    m = BLOCK_PARTS.search(title)
    if not m:
        return False
    actual, forecast = to_float(m.group(1)), to_float(m.group(2))
    if actual is None or forecast is None:
        return False
    return abs(actual - forecast) >= max(0.3, 0.05 * abs(forecast))


def is_important(title):
    terms = read_terms(IMPORTANT_PATH, IMPORTANT_DEFAUT, "Mots qui rendent une annonce importante",
                       "Titre important = marqué d'un rond rouge, en majuscules, avec notification sonore.")
    return has_term(terms, title) or is_surprise(title)


BLOCK_RE = re.compile(r"(Actual\s+[^\s(]+\s*\(Forecast\s+[^,)]*,\s*Previous\s+[^)]*\))")
BLOCK_PARTS = re.compile(r"Actual\s+([^\s(]+)\s*\(Forecast\s+([^,)]*),\s*Previous\s+([^)]*)\)")
TRANSLATE = CFG.get("TRADUCTION", "oui").lower() != "non"


def comma(x):
    return re.sub(r"(\d)\.(\d)", r"\1,\2", x.strip())


class TranslationError(Exception):
    pass


_cache = {}


LAST_ERRORS = {}


def _google_gtx(text):
    q = urllib.parse.urlencode({"client": "gtx", "sl": "en", "tl": "fr", "dt": "t", "q": text})
    data = json.loads(http("https://translate.googleapis.com/translate_a/single?" + q, timeout=10))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def _google_chrome(text):
    q = urllib.parse.urlencode({"client": "dict-chrome-ex", "sl": "en", "tl": "fr", "q": text})
    data = json.loads(http("https://clients5.google.com/translate_a/t?" + q, timeout=10))
    if isinstance(data, dict):
        return "".join(x.get("trans", "") for x in data.get("sentences", [])).strip()
    first = data[0]
    return (first[0] if isinstance(first, list) else first).strip()


def _mymemory(text):
    q = urllib.parse.urlencode({"q": text, "langpair": "en|fr"})
    data = json.loads(http("https://api.mymemory.translated.net/get?" + q, timeout=10))
    out = data["responseData"]["translatedText"].strip()
    if "MYMEMORY WARNING" in out.upper() or "QUERY LENGTH LIMIT" in out.upper():
        raise ValueError(out)
    return out


GROQ_KEY = CFG.get("GROQ_API_KEY", "").strip()
GROQ_MODELS = [m.strip() for m in CFG.get("GROQ_MODELS", "").split(",") if m.strip()] or [
    "openai/gpt-oss-120b", "qwen/qwen3-32b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]
GROQ_DEAD = set()  # modèles indisponibles ou quota du jour atteint (pendant ce cycle)
GROQ_PROMPT = (
    "Tu es traducteur pour un canal Telegram francophone d'actualité des marchés financiers. "
    "Traduis en français le titre de dépêche anglais fourni, dans un style de dépêche financière, clair, naturel et concis. "
    "Règles : ne traduis jamais les noms de personnes, d'entreprises, de médias ni les tickers ; garde tous les chiffres exacts "
    "(virgule décimale française, % collé au chiffre avec une espace avant) ; 'official' = 'responsable' ; "
    "'Strait of Hormuz' ou 'Hormuz' = 'détroit d'Ormuz' ; 'bpd' = 'b/j' ; 'Fed' reste 'Fed' ; 'Treasury yields' = 'rendements des Treasuries' ; "
    "'X: told ... Thinking about it' signifie que l'on a dit quelque chose à X et qu'il répond qu'il y réfléchit. "
    "'auction' (Treasuries, Bund, OAT...) = 'adjudication' ; 'stops at' / 'clears at' = 'rendement de' ; "
    "'US' / 'U.S.' = 'États-Unis' ou 'américain' (jamais 'US' en français) ; 'US-Iran talks' = 'pourparlers entre les États-Unis et l'Iran' ; "
    "utilise des traits d'union normaux. "
    "Une mention de source à la fin ('- interview source', '- source', '- sources') se traduit '– selon une source' / '– selon des sources'. "
    "Fonctions : 'US VP Vance' = 'Le vice-président américain Vance' ; 'US Treasury Secretary X' = 'Le secrétaire américain au Trésor X' ; "
    "'Saudi FM' = 'Le ministre saoudien des Affaires étrangères' ; 'unclear' = 'reste flou' / 'n'est pas clair' (style court) ; "
    "exemple : 'US VP Vance: unclear how Iran makes decisions - source interview' -> "
    "'Le vice-président américain Vance : Le processus décisionnel de l'Iran reste flou – selon une source'. "
    "Préfère toujours la formulation la plus courte et la plus percutante, comme un titre de dépêche. "
    "Traduis TOUTE la phrase : ne supprime jamais une information ni une partie du titre. "
    "Pour un conflit entre deux pays, écris 'la guerre entre X et Y' (jamais d'adjectif du type 'russo-ukrainienne'). "
    "Traduis le SENS, jamais mot à mot : utilise les tournures qu'emploierait un journaliste financier français "
    "('finish it' / 'finish the job' = 'en finir', 'nearing an end' = 'touche à sa fin', 'going away' = 'va disparaître'). "
    "Si le titre a la forme 'Intervenant: déclaration', garde exactement cette forme : 'Intervenant : déclaration' "
    "(un seul deux-points, après l'intervenant ; 'Trump on Iran' = 'Trump à propos de l'Iran'). "
    "Exemples : 'Trump on Iran: We still have to finish it' -> 'Trump à propos de l'Iran : Il nous reste encore à en finir' ; "
    "'Trump: Russia-Ukraine war is nearing an end' -> 'Trump : La guerre entre la Russie et l'Ukraine touche à sa fin' ; "
    "'Trump, when told the federal gas tax needs suspending: Thinking about it' -> "
    "'Trump, à qui l'on dit que la taxe fédérale sur l'essence devrait être suspendue : J'y réfléchis' ; "
    "'Trump: Very soon you'll find out how we end Iran' -> 'Trump : Vous allez bientôt découvrir comment nous allons en finir avec l'Iran' ; "
    "'Trump: Iran's drone-making capability will soon be gone' -> 'Trump : La capacité de l'Iran à fabriquer des drones disparaîtra bientôt'. "
    "Ne commente pas, n'ajoute rien, ne mets pas de guillemets : réponds uniquement par la traduction.")


def _groq(text):
    if not GROQ_KEY:
        raise ValueError("pas de clé Groq")
    last = None
    for model in GROQ_MODELS:
        if model in GROQ_DEAD:
            continue
        body = json.dumps({"model": model, "temperature": 0.2, "max_tokens": 400,
                           "messages": [{"role": "system", "content": GROQ_PROMPT}, {"role": "user", "content": text}]}).encode()
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=body, headers={
            "Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last = f"{model}: HTTP {e.code}"
            if e.code in (400, 404, 413, 429, 403):  # modèle absent, quota atteint... : on passe au suivant
                GROQ_DEAD.add(model)
            continue
        out = re.sub(r"<think>.*?</think>", "", out or "", flags=re.S).strip()
        if len(out) > 1 and out[0] in '"\u00AB' and out[-1] in '"\u00BB':  # guillemets autour de toute la phrase
            out = out[1:-1].strip()
        if out:
            return out
    raise ValueError(last or "aucun modèle Groq disponible")


PROVIDERS = (("groq", _groq), ("google", _google_gtx), ("google-bis", _google_chrome), ("mymemory", _mymemory))


CORRECTIONS_PATH = os.path.join(BOT_DIR, "corrections.txt")
CORRECTIONS_DEFAUT = [
    "fonctionnaire = responsable", "fonctionnaires = responsables", "reporter = journaliste",
    "agissant comme médiateur = jouant le rôle de médiateur",
]


def fix_fr(text):
    """corrections.txt : 'mot traduit = bon mot', appliqué après la traduction (majuscule conservée)."""
    # '... - NewsNation reporter' -> '... – NewsNation'
    text = re.sub(r"\s+[-\u2013]\s*([A-Z][\w.&' ]{1,30}?)\s+(?:reporter|journalist|correspondent)\s*$",
                  " \u2013 " + r"\1", text)
    for line in read_terms(CORRECTIONS_PATH, CORRECTIONS_DEFAUT, "Corrections de traduction",
                           "Format : mauvaise traduction = bonne traduction (en français). Appliqué à chaque annonce."):
        bad, _, good = line.partition("=")
        bad, good = bad.strip(), good.strip()
        if bad and good:
            text = re.sub(r"(?<!\w)" + re.escape(bad) + r"(?!\w)",
                          lambda m: good[:1].upper() + good[1:] if m.group(0)[:1].isupper() else good, text, flags=re.I)
    return text


SOURCE_RE = re.compile(r"\s+[-\u2010-\u2015\u2212]\s*(?:per\s+|via\s+|citing\s+|according\s+to\s+)?"
                       r"([A-Z][\w.&'\u2019]*(?:\s+[A-Z][\w.&'\u2019]*){0,3})"   # le média : mots en majuscule
                       r"(?:\s+(?!X\b)[a-z][\w'\u2019-]*){0,6}"                   # reporter, post, on... : retirés
                       r"(?:\s+(?:X|Twitter))?\s*\.?\s*$")


def translate_text(text):
    """Traduit en français (3 services gratuits en secours l'un de l'autre). Lève TranslationError si tous échouent."""
    text = text.strip()
    if not text:
        return text
    gen = re.search(r"\s*[-\u2010-\u2015\u2212(]\s*(?:interview(?:ed)?|anonymous|unnamed|an?)?[\s:,/-]*(?:with\s+|w/\s*)?(?:an?\s+)?(sources?)"
                    r"(?:\s+(?:interview|say|says|said|familiar.*))?\s*\)?\s*\.?\s*$", text, re.I)
    if gen and gen.start() > 8:  # '... - interview source' / '- sources' -> '– selon une source' / '– selon des sources'
        return f"{translate_text(text[:gen.start()])} \u2013 selon {'des sources' if gen.group(1).lower() == 'sources' else 'une source'}"
    rep = re.search(r",\s*(?:the\s+)?([A-Z][\w.&'\u2019]*(?:\s+[A-Z][\w.&'\u2019]*){0,3})\s+(?:reports?|reported|says|said|writes|wrote)\s*\.?\s*$", text)
    if rep and rep.start() > 8:  # '..., Kyodo reports' -> '... – Kyodo'
        return f"{translate_text(text[:rep.start()])} \u2013 {rep.group(1).strip()}"
    src = SOURCE_RE.search(text)
    if src and src.start() > 8:  # '... - NewsNation reporter on X' : source retirée avant traduction, remise à la fin
        return f"{translate_text(text[:src.start()])} \u2013 {src.group(1).strip()}"
    if text in _cache:
        return _cache[text]
    for wait in (0, 3, 8):
        time.sleep(wait)
        for name, fn in PROVIDERS:
            try:
                out = fn(text)
                if out:
                    if name != "groq":  # corrections.txt : seulement pour la traduction Google (l'IA n'en a pas besoin)
                        out = fix_fr(out)
                        if GROQ_KEY:
                            log(f"Traduction de secours ({name}) - Groq indisponible : {LAST_ERRORS.get('groq', '?')}")
                    _cache[text] = out
                    time.sleep(0.4)  # petite pause pour ne pas se faire limiter
                    return out
            except Exception as e:
                LAST_ERRORS[name] = f"{type(e).__name__}: {e}"
    raise TranslationError(text)


RENOMMER_DEFAUT = [
    "ISM Services PMI = Indice PMI non manufacturier de l'ISM",
    "ISM Non-Manufacturing PMI = Indice PMI non manufacturier de l'ISM",
    "ISM Manufacturing PMI = Indice PMI manufacturier de l'ISM",
]


def custom_title(seg):
    """Titres imposés (renommer.txt, format 'texte anglais = titre français') : ils remplacent la traduction automatique."""
    t = seg.strip().lower()
    for line in read_terms(RENOMMER_PATH, RENOMMER_DEFAUT, "Titres personnalisés",
                           "Format : texte anglais = titre français. Le titre français remplace la traduction automatique."):
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and val and key.lower() in t and len(t) <= len(key) + 12:
            return val
    return None


INSTITUTIONS = {  # "ECB's Lane: ..." -> "Lane de la BCE : ..." (le nom de la personne n'est jamais traduit)
    "ECB": "de la BCE", "Fed": "de la Fed", "FED": "de la Fed", "BoE": "de la BoE", "BOE": "de la BoE",
    "SNB": "de la BNS", "BoJ": "de la BoJ", "BOJ": "de la BoJ", "BoC": "de la BoC", "BOC": "de la BoC",
    "RBA": "de la RBA", "RBNZ": "de la RBNZ", "RBI": "de la RBI", "PBoC": "de la PBoC", "PBOC": "de la PBoC",
    "BoK": "de la BoK", "BOK": "de la BoK", "Bundesbank": "de la Bundesbank", "Buba": "de la Bundesbank",
    "Riksbank": "de la Riksbank", "Norges Bank": "de la Norges Bank", "IMF": "du FMI", "EU": "de l'UE",
    "OPEC": "de l'OPEP", "Treasury": "du Trésor", "White House": "de la Maison-Blanche",
}
INST_RE = re.compile(r"^(?P<inst>[A-Z][A-Za-z ]{1,15}?)['\u2019]s\s+(?P<name>[A-Za-z][A-Za-z\-'\u2019. ]{1,30}?)\s*:\s*(?P<rest>.+)$", re.S)


def speaker_head(title):
    """'ECB's Lane: texte' -> ('Lane de la BCE', 'texte') ; None si ce n'est pas un discours d'une institution connue."""
    m = INST_RE.match(title.strip())
    inst = {k.upper(): v for k, v in INSTITUTIONS.items()}.get(m.group("inst").upper()) if m else None  # BoJ / BOJ / Boj
    if not inst or BLOCK_PARTS.search(title):
        return None
    name = m.group("name").strip()
    name = " ".join(w[:1].upper() + w[1:] for w in name.split())  # 'sato' -> 'Sato'
    return f"{name} {inst}", m.group("rest").strip()


def speech_split(title):
    """Repère un discours 'Intervenant: déclaration'. Renvoie (intervenant, déclaration, nom_déjà_en_français) ou None."""
    sp = speaker_head(title)
    if sp:
        return sp[0], sp[1], True
    if BLOCK_PARTS.search(title):
        return None
    m = SPEAKER_RE.match(title.strip())
    if m and len(m.group(1).split()) <= 5 and m.group(1).strip().lower() not in NOT_SPEAKER:
        return m.group(1).strip(), m.group(3).strip(), False
    return None


def speaker_fr(label, done):
    """'Vitol CEO' -> 'PDG de Vitol'. Un nom seul (Trump, Lagarde...) n'est jamais traduit."""
    if done or not TRANSLATE or len(label.split()) == 1:
        return label
    return translate_text(label)


def speech_fr(label, stmt_en, done):
    """Traduit 'Intervenant: déclaration' EN ENTIER (le contexte aide la traduction), puis sépare après coup."""
    if not TRANSLATE:
        return label, stmt_en
    who_en = label if not done else label  # pour une institution ('Lane de la BCE'), le nom français est déjà prêt
    fr = translate_text(f"{who_en}: {stmt_en}")
    m = re.match(r"^\s*([^:]{1,80}?)\s*:\s*(.+)$", fr, re.S)
    if m:
        who = label if done else m.group(1).strip()
        who = who[:1].upper() + who[1:]
        stmt = m.group(2).strip()
        return who, comma(stmt[:1].upper() + stmt[1:])
    return speaker_fr(label, done), comma(translate_text(stmt_en))  # découpage impossible : ancienne méthode


def to_french(title):
    if not TRANSLATE:
        return title
    sp = speaker_head(title)
    if sp:  # discours : nom gardé tel quel, seule la déclaration est traduite
        return f"{sp[0]} : {comma(translate_text(sp[1]))}"
    out = []
    for seg in BLOCK_RE.split(title):
        m = BLOCK_PARTS.fullmatch(seg.strip())
        if m:  # bloc chiffré : mis en forme sans passer par la traduction
            a, f, p = (comma(g) for g in m.groups())
            out.append(f"Publié {a} (prévu {f}, précédent {p})")
        elif seg.strip():
            out.append(custom_title(seg) or comma(translate_text(seg)))
    return " ".join(out)


def split_subject(text):
    """Sépare le sujet du reste : 'Indice PMI ... allemands | Publié 52,9 (...)' ou 'Williams (Fed) | : ...'."""
    i = text.find(" Publié ")
    if i > 0:
        return text[:i], text[i:]
    m = re.match(r"^(.{3,80}?)(\s*:\s*)(.+)$", text)
    if m:
        return m.group(1), m.group(2) + m.group(3)
    return None, text


SPEAKER_RE = re.compile(r"^([^:\d]{2,45}?)(\s*:\s*)(.+)$", re.S)
NOT_SPEAKER = ("breaking", "urgent", "exclusive", "update", "alert", "flash", "rumor", "report", "reports", "source", "sources")


def style(title, base):
    """Met le texte en forme ('i' ou 'bi') ; si une personne parle ('Powell : ...'), son nom est souligné."""
    def wrap(t):
        t = html.escape(t)
        return f"<b><i>{t}</i></b>" if base == "bi" else f"<i>{t}</i>"
    m = SPEAKER_RE.match(title)
    if m and len(m.group(1).split()) <= 5 and m.group(1).strip().lower() not in NOT_SPEAKER:
        name, sep, rest = m.groups()
        return wrap(name).replace(html.escape(name), f"<u>{html.escape(name)}</u>") + wrap(sep + rest)
    return wrap(title)


DATA_RE = re.compile(r"^(.*?)\s*Publié (.+?) \(prévu (.+?), précédent (.+?)\)\s*$", re.S)


SEP = "\u2500" * 14


ETIQUETTES_DEFAUT = [
    "donnee: US, U.S., USA, United States, American, Fed, FOMC, ADP, ISM, NFP, nonfarm, Michigan, Conference Board, PCE, jobless claims, Jobless Claims, durable goods, Philadelphia, Empire State, Richmond = \U0001F1FA\U0001F1F8",
    "autre: Fed, FOMC, Federal Reserve, rate decision, rate cut, rate hike = \U0001F3E6",
    "autre: gold, XAU = \U0001F947",
]


def labels(kind):
    """Lit etiquettes.txt : lignes 'donnee: mots = emoji' (donnée chiffrée) ou 'autre: mots = emoji'."""
    out = []
    for line in read_terms(ETIQUETTES_PATH, ETIQUETTES_DEFAUT, "Petits repères devant les annonces importantes",
                           "Format : donnee: mot1, mot2 = emoji (donnée chiffrée) ou autre: mot1, mot2 = emoji. La première ligne qui correspond gagne."):
        k, _, rest = line.partition(":")
        if k.strip().lower() == kind and "=" in rest:
            words, emoji = rest.rsplit("=", 1)
            out.append(([w.strip() for w in words.split(",") if w.strip()], emoji.strip()))
    return out


def tag_for(original, title):
    """Petit repère de catégorie devant les annonces importantes."""
    if BLOCK_PARTS.search(original):  # donnée chiffrée : drapeau du pays, sinon graphique
        for words, emoji in labels("donnee"):
            if has_term(words, original):
                return emoji
        return "\U0001F4CA"
    m = SPEAKER_RE.match(title)
    if m and len(m.group(1).split()) <= 5 and m.group(1).strip().lower() not in NOT_SPEAKER:
        return "\U0001F399"  # micro : discours
    for words, emoji in labels("autre"):
        if has_term(words, original):
            return emoji
    return ""


RETIRER_DEFAUT = [
    r"\s+(?:aux|des|du|en|de|d')\s*(?:les\s+)?(?:États-Unis|Etats-Unis|USA)\b",
    r"\s+(?:américain|américaine|américains|américaines)\b",
    r"^(?:US|U\.S\.)\s+",
]


def drop_us(subject):
    """Le drapeau indique déjà le pays : on retire les mentions du pays du sujet (expressions dans retirer.txt)."""
    s = subject
    for pat in read_terms(RETIRER_PATH, RETIRER_DEFAUT, "Mots retirés des titres de données chiffrées",
                          "Expressions régulières, une par ligne : le drapeau affiché devant le titre remplace ces mentions."):
        try:
            s = re.sub(pat, "", s, flags=re.I)
        except re.error:
            pass
    return s.strip(" :-") or subject


def vs_forecast(actual, forecast):
    a, f = to_float(actual), to_float(forecast)
    if a is None or f is None:
        return ""
    if abs(a - f) < 1e-9:
        return " ="
    return " \u25B2" if a > f else " \u25BC"


MONNAIE_PATH = os.path.join(BOT_DIR, "monnaie.txt")
SUFFIXES = {"K": " k", "M": " M", "B": " Md", "T": " Bn"}


def money_symbol(original):
    """monnaie.txt : 'mot-clé = symbole' (ex. Trade Balance = $). Renvoie le symbole si le titre correspond."""
    for line in read_terms(MONNAIE_PATH, [], "Montants en devise",
                           "Format : mot-clé = symbole. Ex. Trade Balance = $ -> -105,6 Md$ au lieu de -105,6B."):
        key, _, sym = line.partition("=")
        if key.strip() and sym.strip() and key.strip().lower() in original.lower():
            return sym.strip()
    return ""


def money(x, sym):
    """'-105,6B' -> '-105,6 Md$' ; laisse la valeur telle quelle si ce n'est pas un montant."""
    m = re.fullmatch(r"\s*([+-]?)\s*[$\u20AC\u00A3\u00A5]?\s*([\d.,]+)\s*([KMBT]?)\s*", x)
    if not m:
        return x.strip()
    return f"{m.group(1)}{m.group(2)}{SUFFIXES.get(m.group(3), ' ')}{sym}".replace("  ", " ")


def figures(original, m):
    """Chiffres publié / prévu / précédent, avec devise éventuelle et révision mise en forme."""
    a, f, p = (g.strip() for g in m.group(2, 3, 4))
    rev = re.match(r"^(.*?),\s*Revised\s+(.+)$", p, re.I)
    sym = money_symbol(original)
    conv = (lambda x: money(x, sym)) if sym else (lambda x: x)
    a, f = conv(a), conv(f)
    p = f"{conv(rev.group(1))} (révisé {conv(rev.group(2))})" if rev else conv(p)
    return html.escape(a), html.escape(f), html.escape(p)


def full_text(item):
    """Titre + détails, pour les filtres."""
    return " ".join([item["title"]] + item.get("details", []))


def fmt_details(item, english=False):
    """Annonce avec plusieurs lignes de détails (ex. Déséquilibre MOO, rapport EIA...)."""
    original = item["title"]
    head = original if english or not TRANSLATE else (custom_title(original) or comma(translate_text(original)))
    lines, texte = [], False
    for d in item["details"]:
        chiffre = re.fullmatch(r"\s*([^:]{1,40}?)\s*:\s*([-+]?\s*\$?[\d.,]+)\s*(mln|bln|k|m|b)?\s*", d, re.I)
        if chiffre:  # ligne 'Indice : valeur' (ex. S&P 500 : -66 mln) -> montant en dollars
            unit = {"mln": " M$", "m": " M$", "bln": " Md$", "b": " Md$", "k": " k$"}.get((chiffre.group(3) or "").lower(), "")
            d = f"{chiffre.group(1)} : {chiffre.group(2).replace(' ', '')}{unit}"
        else:  # vraie phrase : traduite
            texte = True
            if TRANSLATE and not english:
                d = translate_text(d)
        lines.append(comma(d))
    puce = "\u2022 " if texte and len(lines) > 1 else ""
    body = "\n".join(f"<i>{puce}{html.escape(l)}</i>" for l in lines)
    if is_important(full_text(item)):
        return f"\U0001F534 <b><u>{html.escape(head.upper())}</u></b>\n\n{body}\n{SEP}"
    return f"\u25AB\uFE0F <i><u>{html.escape(head)}</u></i>\n{body}"


def fmt(item, english=False):
    if item.get("details"):
        return fmt_details(item, english)
    original = item["title"]
    title = original if english else to_french(original)
    hhmm = item.get("time", "")
    when = ""  # heure retirée
    if not is_important(original):
        m = DATA_RE.match(title)
        if m:  # donnée chiffrée normale : drapeau + sujet en italique, puis les chiffres sur une ligne
            subject = drop_us(m.group(1).strip(" :-") or "Annonce")
            a, f, p = figures(original, m)
            flag = tag_for(original, title) or "\u25AB\uFE0F"
            return (f"{flag} <i>{html.escape(subject)}</i>\n\n"
                    f"<b><i>Publié : {a}</i></b>{vs_forecast(m.group(2), m.group(3))}\n"
                    f"<i>Prévu : {f} \u00B7 Précédent : {p}</i>")
        return f"\u25AB\uFE0F {style(title, 'i')}{when}"  # autre annonce normale : une ligne compacte, italique
    tag = tag_for(original, title)
    head = f"\U0001F534 {tag} " if tag else "\U0001F534 "
    m = DATA_RE.match(title)
    if m:  # donnée chiffrée : sujet souligné, Publié en gras + écart, prévu/précédent en italique
        subject = drop_us(m.group(1).strip(" :-") or "Annonce")
        a, f, p = figures(original, m)
        return (f"{head}<b><u>{html.escape(subject.upper())}</u></b>{when}\n\n"
                f"<b><i>Publié : {a}</i></b>{vs_forecast(m.group(2), m.group(3))}\n"
                f"<i>Prévu : {f} \u00B7 Précédent : {p}</i>\n{SEP}")
    sp = SPEAKER_RE.match(title)
    if tag == "\U0001F399" and sp:  # discours : nom souligné au-dessus, déclaration en dessous
        name, _, rest = sp.groups()
        return (f"{head}<b><u>{html.escape(name.strip())}</u></b>{when}\n\n"
                f"<i>{html.escape(rest.strip())}</i>\n{SEP}")
    return f"{head}{style(title, 'bi')}{when}\n{SEP}"  # autre annonce importante : gras italique


def fmt_speech(group):
    """Plusieurs déclarations d'une même personne -> un seul message (nom en tête, une ligne par déclaration)."""
    name = html.escape(group[0][1])
    lines = [f"<i>{html.escape(g[2])}</i>" for g in group]
    if len(lines) > 1:
        lines = [f"\u2022 {l}" for l in lines]
    body = "\n\n".join(lines)
    if any(g[3] for g in group):  # au moins une déclaration importante : rond rouge + sonnerie
        return f"\U0001F534 \U0001F399 <b><u>{name}</u></b>\n\n{body}\n{SEP}"
    if len(group) == 1:  # une seule déclaration normale : une ligne compacte
        return f"\u25AB\uFE0F <i><u>{name}</u> : {html.escape(group[0][2])}</i>"
    return f"\u25AB\uFE0F \U0001F399 <u>{name}</u>\n\n{body}"


ALERTE_PATH = os.path.join(BOT_DIR, "alerte.txt")
ALERTE_DEFAUT = ["Iran, Iranian, Tehran, Hormuz, IRGC, Khamenei, Persian Gulf = IRAN \u00B7 ORMUZ"]
LINE = "\u2501" * 14


def alert_label(text):
    """alerte.txt : 'mot1, mot2 = TITRE'. Renvoie le titre de l'alerte si l'annonce en parle."""
    for line in read_terms(ALERTE_PATH, ALERTE_DEFAUT, "Alertes spéciales (format le plus visible)",
                           "Format : mot1, mot2 = TITRE DE L'ALERTE. Une annonce qui contient un de ces mots passe en alerte."):
        words, _, label = line.rpartition("=")
        terms = [w.strip() for w in words.split(",") if w.strip()]
        if terms and label.strip() and has_term(terms, text):
            return label.strip()
    return ""


def alertify(text, original):
    """Habille un message en ALERTE (bandeau + cadre) s'il concerne un sujet d'alerte."""
    label = alert_label(original)
    if not label:
        return text, False
    body = re.sub(r"^(?:\U0001F534|\u25AB\uFE0F)\s*", "", text)
    body = re.sub(r"\n?" + re.escape(SEP) + r"\s*$", "", body).strip()
    return f"\U0001F6A8 <b>ALERTE {html.escape(label)}</b> \U0001F6A8\n{LINE}\n{body}\n{LINE}", True


def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            return json.load(open(SEEN_PATH, encoding="utf-8"))
        except ValueError:
            pass
    return None


def save_seen(ids):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(ids[-KEEP:], f)


def need_env(*names):
    missing = [n for n in names if not CFG.get(n)]
    if missing:
        sys.exit("Il manque dans config.env : " + ", ".join(missing))


def cmd_chat_id():
    need_env("TELEGRAM_BOT_TOKEN")
    r = tg("getUpdates")
    if not r.get("ok"):
        sys.exit(f"Erreur Telegram : {r.get('description')}")
    seen = {}
    for u in r.get("result", []):
        m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        c = m.get("chat")
        if c:
            seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name") or "?"
    if not seen:
        sys.exit("Aucun message reçu. Ajoute le bot au groupe, écris /start dans le groupe, puis relance.")
    for cid, name in seen.items():
        print(f"{cid}   {name}")


def cmd_dry():
    items = fetch_items()
    print(f"{len(items)} titres lus. Les 5 plus récents :")
    for it in items[:5]:
        print(" -", it["title"])


def cmd_test():
    need_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    ok = send("<b>Test</b> : le bot FinancialJuice est bien relié à ce groupe.")
    print("Message de test envoyé." if ok else "Échec de l'envoi (voir le message ci-dessus).")


def run():
    if DEADLINE and not (CFG.get("TELEGRAM_BOT_TOKEN") and CFG.get("TELEGRAM_CHAT_ID")):
        log("Bot pas encore configuré (token ou identifiant de canal manquant) : rien à faire.")
        return
    need_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    seen = load_seen()
    errors = 0
    delay = INTERVAL
    fails = {}  # nombre d'échecs de traduction par titre
    log("Bot lancé. Ctrl+C pour arrêter.")
    while True:
        try:
            items = fetch_items()
            errors = 0
            delay = INTERVAL
            if seen is None:  # premier lancement : on mémorise l'existant sans rien envoyer
                seen = [i["id"] for i in reversed(items)]
                save_seen(seen)
                log(f"Premier lancement : {len(seen)} titres existants ignorés, j'envoie les suivants.")
            else:
                known = set(seen)
                new = [i for i in reversed(items) if i["id"] not in known]
                pending = []  # discours en cours de regroupement : (titre, nom, déclaration, important)

                def flush():
                    """Envoie les déclarations regroupées (découpées si le message serait trop long)."""
                    ok = True
                    while pending:
                        group, size = [], 0
                        while pending and (not group or size + len(pending[0][2]) < 3500):
                            size += len(pending[0][2]) + 10
                            group.append(pending.pop(0))
                        imp = any(g[3] for g in group)
                        msg, alerte = alertify(fmt_speech(group), " ".join(g[0]["title"] for g in group))
                        if send(msg, silent=SILENCIEUX and not imp and not alerte):
                            seen.extend(g[0]["id"] for g in group)
                            log(f"Envoyé : {group[0][1]} ({len(group)} déclaration(s))")
                        else:
                            pending.clear()  # pas mémorisées : renvoyées au prochain tour
                            ok = False
                    return ok

                for it in new:
                    if is_ignored(full_text(it)) or not is_wanted(full_text(it)):  # graphiques, hors sujet : on passe
                        seen.append(it["id"])
                        continue
                    sp = None if it.get("details") else speech_split(it["title"])
                    if sp:  # discours : on accumule les déclarations consécutives de la même personne
                        label, stmt_en, done = sp
                        if pending and pending[0][4] != label and not flush():
                            break
                        try:
                            who, stmt = speech_fr(label, stmt_en, done)
                        except TranslationError:
                            fails[it["id"]] = fails.get(it["id"], 0) + 1
                            if fails[it["id"]] < 4:
                                log("Traduction impossible pour l'instant, nouvel essai au prochain tour.")
                                break
                            who, stmt = label, stmt_en  # dernier recours : en anglais
                        pending.append((it, who, stmt, is_important(it["title"]), label))
                        continue
                    if not flush():
                        break
                    try:
                        text = fmt(it)
                    except TranslationError:
                        fails[it["id"]] = fails.get(it["id"], 0) + 1
                        if fails[it["id"]] < 4:
                            log("Traduction impossible pour l'instant, nouvel essai au prochain tour.")
                            break  # on garde l'ordre : on réessaiera ce titre
                        text = fmt(it, english=True)  # dernier recours : le titre en anglais
                    text, alerte = alertify(text, full_text(it))
                    if send(text, silent=SILENCIEUX and not is_important(full_text(it)) and not alerte):
                        seen.append(it["id"])
                        log("Envoyé : " + it["title"][:80])
                    else:
                        break  # on réessaiera au prochain tour, sans perdre l'ordre
                flush()
                if new:
                    save_seen(seen)
        except KeyboardInterrupt:
            raise
        except urllib.error.HTTPError as e:
            errors += 1
            if e.code == 429:  # le site demande de ralentir
                try:
                    asked = int(e.headers.get("Retry-After", "0"))
                except ValueError:
                    asked = 0
                delay = min(max(delay * 2, asked, 120), MAX_WAIT)
                log(f"Le site demande de ralentir (429). Prochaine lecture dans {delay} s.")
            else:
                delay = INTERVAL
                log(f"Lecture impossible (HTTP {e.code}). Nouvel essai dans {delay} s.")
        except Exception as e:  # réseau, flux illisible...
            errors += 1
            delay = INTERVAL
            log(f"Lecture impossible ({type(e).__name__}: {e}). Nouvel essai dans {delay} s.")
        if errors == 10:
            send("Le bot n'arrive plus à lire le flux FinancialJuice depuis un moment.")
        if DEADLINE and time.time() + delay >= DEADLINE:
            log("Fin du cycle.")
            return
        time.sleep(delay)


DEMO = [
    "US ISM Services PMI Actual 55.2 (Forecast 54.0, Previous 55.4)",
    "Fed's Williams: policy is well positioned to respond to a weaker labor market",
    "Gold hits record high above $4,000",
    "German Services PMI Final Actual 52.9 (Forecast 52.9, Previous 52.9)",
    "Trump: tariffs on Chinese goods will rise next month",
    "US Initial Jobless Claims Actual 200K (Forecast 220K, Previous 197K)",
    "Treasury yields rise as 10-year hits 4.5%",
    "Goldman Sachs raises S&P 500 year-end target",
    "Powell: inflation is still too high, we will remain data dependent",
    "US Dollar Index (DXY) climbs to a two-week high",
    "Taiwan stocks gain over 2%",
    "US Nonfarm Payrolls Actual 254K (Forecast 150K, Previous 159K)",
    "Fed's Waller: a rate cut in December is possible",
    "Wall Street opens higher as tech rebounds",
    "Iran says it will respond to any attack on its oil facilities",
    "US ADP Employment Change Actual 143K (Forecast 120K, Previous 122K)",
    "Gold futures extend gains as the dollar weakens",
    "Italian Services PMI Actual 51.7 (Forecast 54.5, Previous 55.2)",
    "Treasury Secretary says the US will not default",
    "US Core PCE Price Index m/m Actual 0.3% (Forecast 0.2%, Previous 0.2%)",
    "Nasdaq closes at a fresh record high",
    "Fed's Kashkari: the labor market is cooling but inflation is sticky",
]


def cmd_demo():
    need_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    n = 0
    demo = DEMO
    if os.path.exists(DEMO_PATH):
        with open(DEMO_PATH, encoding="utf-8") as f:
            demo = [l.strip() for l in f if l.strip() and not l.startswith("#")] or DEMO
    for t in demo:
        if is_ignored(t) or not is_wanted(t):
            print("Écarté :", t)
            continue
        try:
            now = time.strftime("%H:%M")
            send(fmt({"title": t, "time": now}))
        except TranslationError:
            send(fmt({"title": t, "time": now}, english=True))
        n += 1
        time.sleep(1.5)
    print(f"{n} titres envoyés, {len(demo) - n} écartés (hors marché suivi).")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        {"--chat-id": cmd_chat_id, "--dry": cmd_dry, "--test": cmd_test, "--demo": cmd_demo}.get(arg, run)()
    except KeyboardInterrupt:
        print("\nArrêté.")
