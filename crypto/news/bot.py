import os, sys, json, re, time, html, getpass, urllib.request, urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

CHAT_ID = "-1004378081214"
DOSSIER = os.path.dirname(os.path.abspath(__file__))
FICHIER_VUS = os.path.join(DOSSIER, "vus.json")
FICHIER_TITRES = os.path.join(DOSSIER, "titres.json")
MAX_PAR_PASSAGE = 10
SEUIL_DOUBLON = 0.45
ATOM = "{http://www.w3.org/2005/Atom}"

FLUX = {
    "Cointribune":     "https://www.cointribune.com/feed/",
    "Cryptonaute":     "https://cryptonaute.fr/feed/",
    "Journal du Coin": "https://journalducoin.com/feed/",
    "Cryptoast":       "https://cryptoast.fr/feed/",
    "BeInCrypto":      "https://fr.beincrypto.com/feed/",
}

MOTS_CLES = [
    r"bitcoins?", r"btc", r"ethereum", r"ether", r"eth", r"crypto\w*", r"stablecoins?",
    r"blockchains?", r"defi", r"nfts?", r"tokens?", r"tokenis\w*", r"jetons?", r"solana",
    r"xrp", r"ripple", r"cardano", r"dogecoin", r"doge", r"bnb", r"binance", r"coinbase",
    r"kraken", r"okx", r"bybit", r"bitget", r"tether", r"usdt", r"usdc", r"circle",
    r"saylor", r"microstrategy", r"bitmine", r"etfs?", r"sec", r"cftc", r"esma", r"mica",
    r"amf", r"cbdcs?", r"euro numérique", r"pirat\w*", r"hack\w*", r"faille\w*",
    r"exploit", r"altcoins?", r"memecoins?", r"web3", r"satoshi", r"halving", r"minage",
    r"mineurs?", r"hyperliquid", r"zachxbt", r"lazarus", r"on-?chain",
]
FILTRE = re.compile(r"\b(" + "|".join(MOTS_CLES) + r")\b", re.I)
EXCLUS = re.compile(
    r"(^analyse|objectif de prix|prévision|prédiction|pronostic|pourquoi cette crypto|"
    r"signaux (haussiers|baissiers)|meilleures? crypto|à acheter|prévente|presale|"
    r"sponsoris|communiqué|bull score|coin hebdo)", re.I)

MOTS_VIDES = set("les des une dans pour par avec sur aux est son ses sa cette ce qui que plus leur leurs ont après avant".split())

def charger(fichier):
    try:
        with open(fichier) as f:
            return json.load(f)
    except Exception:
        return []

def sauver(fichier, donnees, garder):
    with open(fichier, "w") as f:
        json.dump(donnees[-garder:], f, ensure_ascii=False)

def lire_token():
    try:
        with open(os.path.join(DOSSIER, ".telegram_token")) as f:
            t = f.read().strip()
            if t:
                return t
    except FileNotFoundError:
        pass
    t = os.environ.get("TELEGRAM_TOKEN", "").strip()
    return t or getpass.getpass("Token (invisible, colle puis Entrée) : ").strip()

def date_ts(texte):
    try:
        return parsedate_to_datetime(texte).timestamp()
    except Exception:
        return 0

AVEC_IMAGE = False  # False = revenir à l'aperçu automatique de Telegram
MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENU = "{http://purl.org/rss/1.0/modules/content/}encoded"

def image_de(it):
    for el in it.findall(f".//{MEDIA}content") + it.findall(f".//{MEDIA}thumbnail"):
        u = (el.get("url") or "").strip()
        typ = (el.get("type") or "") + (el.get("medium") or "")
        if u.startswith("http") and "video" not in typ and not re.search(r"\.(mp4|webm|mov)(\?|$)", u, re.I):
            return html.unescape(u)
    for el in it.findall("enclosure"):
        if (el.get("type") or "").startswith("image") and el.get("url"):
            return html.unescape(el.get("url"))
    contenu = (it.findtext(CONTENU) or "") + (it.findtext("description") or "")
    m = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)', contenu)
    return html.unescape(m.group(1)) if m else ""

def lire_flux(nom, url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    articles = []
    for it in items:
        titre = html.unescape((it.findtext("title") or it.findtext(f"{ATOM}title") or "").strip())
        lien = (it.findtext("link") or "").strip()
        if not lien:
            l = it.find(f"{ATOM}link")
            lien = l.get("href", "") if l is not None else ""
        date = it.findtext("pubDate") or it.findtext(f"{ATOM}updated") or ""
        if titre and lien:
            articles.append({"source": nom, "titre": titre, "lien": lien.strip(),
                             "ts": date_ts(date), "image": image_de(it)})
    return articles

def tous_les_articles():
    tous = []
    for nom, url in FLUX.items():
        try:
            tous.extend(lire_flux(nom, url))
        except Exception as e:
            print(f"⚠️ {nom} : {e}")
    return sorted(tous, key=lambda a: a["ts"])  # du plus ancien au plus récent

FAIT_DIVERS = re.compile(r"(séquestr\w*|enl[eè]v\w*|kidnapp\w*|rapt\w*|otage\w*|braquage\w*|agress\w*|cambriol\w*|meurtre\w*|tortur\w*|home.?jacking|dépouill\w*)", re.I)
HORS_CRYPTO = re.compile(r"(\bl['’]or\b|\blingots?\b|\bor physique\b|négociant en or)", re.I)

def est_crypto(a):
    t = a["titre"]
    if FAIT_DIVERS.search(t) and HORS_CRYPTO.search(t):
        return False
    return bool(FILTRE.search(t)) and not EXCLUS.search(t)

def mots(titre):
    t = re.sub(r"[^\w\s]", " ", titre.lower())
    return {m for m in t.split() if len(m) > 2 and m not in MOTS_VIDES}

def est_doublon(titre, recents):
    a = mots(titre)
    for r in recents:
        b = set(r)
        if a and b and len(a & b) / len(a | b) >= SEUIL_DOUBLON:
            return True
    return False

STYLE_ARTICLE = "actuel"  # "actuel", "A" ou "B"

def format_article(a, style):
    s, t, l = html.escape(a["source"]), html.escape(a["titre"]), html.escape(a["lien"])
    if style == "A":
        return f"▫️ <i><u>{s}</u> : {t}</i>\n<a href=\"{l}\">Lire l'article</a>", True
    if style == "B":
        return f"<b>CRYPTO NEWS</b> · <i>{s}</i>\n\n<b>{t}</b>\n\n<a href=\"{l}\">Lire l'article →</a>", False
    return f"🪙 <b>CRYPTO NEWS</b> · <i>{s}</i>\n\n<b>{t}</b>\n\n🔗 <a href=\"{l}\">Lire l'article</a>", False

def image_page(lien):
    """Image principale de l'article (balise og:image de la page)."""
    try:
        req = urllib.request.Request(lien, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9"})
        page = urllib.request.urlopen(req, timeout=10).read(500000).decode("utf-8", "ignore")
    except Exception:
        return ""
    for m in re.finditer(r"<meta\b[^>]*>", page, re.I):
        balise = m.group(0)
        if re.search(r'(property|name)=["\'](og:image|og:image:url|twitter:image)["\']', balise, re.I):
            c = re.search(r'content=["\']([^"\']+)', balise, re.I)
            if c and c.group(1).startswith("http"):
                return html.unescape(c.group(1))
    return ""

def appel(token, methode, params):
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{methode}", data=data, timeout=30) as r:
            return bool(json.load(r).get("ok"))
    except urllib.error.HTTPError as e:
        try:
            print("   Telegram :", json.load(e).get("description"))
        except Exception:
            print("   Telegram :", e)
    except Exception as e:
        print("   Erreur :", e)
    return False

def envoyer(token, a, style=None):
    texte, sans_apercu = format_article(a, style or STYLE_ARTICLE)
    ok, mode = False, "texte"
    img = (image_page(a["lien"]) or a.get("image")) if AVEC_IMAGE else ""
    if img:
        ok = appel(token, "sendPhoto", {"chat_id": CHAT_ID, "photo": img,
                                        "caption": texte, "parse_mode": "HTML",
                                        "show_caption_above_media": "true"})
        mode = "photo"
        if not ok:
            print("   (image refusée, envoi en texte)")
            mode = "texte"
    if not ok:
        params = {"chat_id": CHAT_ID, "text": texte, "parse_mode": "HTML"}
        if sans_apercu:
            params["disable_web_page_preview"] = "true"
        ok = appel(token, "sendMessage", params)
    print(("✅ " if ok else "❌ ") + f"[{mode}] " + a["titre"])
    time.sleep(3)
    return ok

def apercu():
    """Affiche ce qui serait gardé ou écarté, sans rien envoyer."""
    for a in tous_les_articles():
        print(("✅ " if est_crypto(a) else "🚫 ") + f"[{a['source']}] {a['titre']}")

def passage(token, mode_test=False):
    tous = tous_les_articles()
    if mode_test:
        crypto = [a for a in tous if est_crypto(a)]
        print(f"Mode test : envoi de 3 articles sur {len(crypto)} articles crypto trouvés.")
        for a in crypto[-3:]:
            envoyer(token, a)
        return

    premier = not os.path.exists(FICHIER_VUS)
    vus, recents = charger(FICHIER_VUS), charger(FICHIER_TITRES)
    deja = set(vus)
    nouveaux = []
    for a in tous:
        cle = a["lien"].split("?")[0]
        if cle not in deja:
            deja.add(cle)
            nouveaux.append((cle, a))

    if premier:
        vus += [c for c, _ in nouveaux]
        recents += [sorted(mots(a["titre"])) for _, a in nouveaux if est_crypto(a)]
        sauver(FICHIER_VUS, vus, 3000)
        sauver(FICHIER_TITRES, recents, 300)
        print(f"Initialisation : {len(vus)} articles marqués comme déjà vus, rien n'est envoyé.")
        return

    a_envoyer = []
    for cle, a in nouveaux:
        if est_crypto(a):
            a_envoyer.append((cle, a))
        else:
            vus.append(cle)
    if not a_envoyer:
        print(time.strftime("%H:%M:%S"), "— rien de nouveau")
    for cle, _ in a_envoyer[:-MAX_PAR_PASSAGE]:
        vus.append(cle)
    for cle, a in a_envoyer[-MAX_PAR_PASSAGE:]:
        if est_doublon(a["titre"], recents):
            print("↩️ Doublon ignoré :", a["titre"])
            vus.append(cle)
            continue
        if envoyer(token, a):
            vus.append(cle)
            recents.append(sorted(mots(a["titre"])))
    sauver(FICHIER_VUS, vus, 3000)
    sauver(FICHIER_TITRES, recents, 300)

# ===================== FLASHS (canaux anglais, traduits et nettoyés) =====================
from datetime import datetime

CANAUX_FLASH = ["WatcherGuru", "wublockchainenglish", "cointelegraph", "unfolded"]
MAX_FLASH_PAR_PASSAGE = 5
EXCLUS_FLASH = re.compile(r"\b(opinion|highlight clip|podcast|ama|giveaway|sponsored|advertisement|promo)\b", re.I)
PRIX_FLASH = re.compile(
    r"\b(bitcoin|btc|ether|ethereum|eth|solana|sol|xrp|bnb)\b[^.]{0,40}\b(falls?|drops?|dips?|slips?|plunges?|"
    r"rises?|surges?|climbs?|jumps?|soars?|tops?|breaks?|reclaims?|hits?|crosses|tumbles?)\b[^.]{0,30}\$\s?\d", re.I)
_cache = {}

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

def _google_gtx(t):
    d = http_json("https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": "en", "tl": "fr", "dt": "t", "q": t}))
    return "".join(m[0] for m in d[0] if m[0]).strip()

def _google_chrome(t):
    d = http_json("https://clients5.google.com/translate_a/t?" + urllib.parse.urlencode(
        {"client": "dict-chrome-ex", "sl": "en", "tl": "fr", "q": t}))
    while isinstance(d, list) and d:
        d = d[0]
    return d.strip() if isinstance(d, str) else ""

def _mymemory(t):
    d = http_json("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({"q": t, "langpair": "en|fr"}))
    out = html.unescape(d["responseData"]["translatedText"]).strip()
    if "MYMEMORY WARNING" in out.upper() or "QUERY LENGTH LIMIT" in out.upper():
        raise ValueError(out)
    return out

FOURNISSEURS = (("Google", _google_gtx), ("Google-bis", _google_chrome), ("MyMemory", _mymemory))

def traduire(texte):
    texte = texte.strip()[:400]
    if texte in _cache:
        return _cache[texte]
    erreurs = {}
    for attente in (0, 3, 8):
        time.sleep(attente)
        for nom, fn in FOURNISSEURS:
            try:
                out = fn(texte)
                if out:
                    _cache[texte] = out
                    time.sleep(0.4)
                    return out
            except Exception as e:
                erreurs[nom] = f"{type(e).__name__}: {e}"
    print("⚠️ Traduction impossible :", erreurs)
    return None

def nettoyer_flash(brut):
    lignes = [l.strip() for l in brut.split("\n") if l.strip()]
    if not lignes:
        return ""
    t = lignes[0]
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"@\w+", "", t)
    t = re.sub(r"—?\s*link\s*\|\s*AI comment", "", t, flags=re.I)
    t = re.sub(r"News\s*\|\s*Markets\s*\|\s*YouTube", "", t, flags=re.I)
    t = re.sub(r"^[^\w$]+", "", t)
    t = re.sub(r"^(JUST IN|BREAKING|NEW|BIG|UPDATE|ALERT|LATEST)\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"^[^\w$]+", "", t)
    t = re.sub(r"[#$](?=[A-Za-z])", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" -—|")

def lire_canal(canal):
    req = urllib.request.Request(f"https://t.me/s/{canal}", headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
    flashs = []
    for m in page.split('data-post="')[1:]:
        post = m.split('"', 1)[0]
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', m, re.S)
        d = re.search(r'<time[^>]*datetime="([^"]+)"', m)
        if not t:
            continue
        brut = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", t.group(1))))
        premiere = next((l.strip() for l in brut.split("\n") if l.strip()), "")
        urgent = bool(re.search(r"🚨|\bBREAKING\b|^\W*BIG\b", premiere[:40]))
        texte = nettoyer_flash(brut)
        try:
            ts = datetime.fromisoformat(d.group(1)).timestamp() if d else 0
        except Exception:
            ts = 0
        if texte:
            flashs.append({"id": "tg:" + post, "texte": texte, "ts": ts, "canal": canal, "urgent": urgent})
    return flashs

FJ_URL = "https://www.financialjuice.com/feed.ashx?xy=rss"
FILTRE_FJ = re.compile(
    r"\b(bitcoins?|btc|ethereum|eth|ether|crypto\w*|stablecoins?|blockchains?|solana|xrp|ripple|tether|usdt|usdc|"
    r"coinbase|binance|kraken|okx|bybit|bitget|defi|tokeni[sz]\w*|digital assets?|microstrategy|saylor)\b", re.I)

def lire_fj():
    req = urllib.request.Request(FJ_URL, headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())
    flashs = []
    for it in root.findall(".//item"):
        titre = html.unescape((it.findtext("title") or "").strip())
        titre = re.sub(r"^FinancialJuice:\s*", "", titre, flags=re.I)
        cle = (it.findtext("guid") or it.findtext("link") or titre).strip()
        if titre:
            flashs.append({"id": "fj:" + cle, "texte": nettoyer_flash(titre) or titre,
                           "ts": date_ts(it.findtext("pubDate") or ""), "canal": "FinancialJuice", "urgent": False})
    return flashs

FJ_INTERVALLE = 180
_fj = {"t": 0, "cache": [], "pause": 0}

def flashs_fj():
    now = time.time()
    if not FJ_URL or now < _fj["pause"] or now - _fj["t"] < FJ_INTERVALLE:
        return _fj["cache"]
    _fj["t"] = now
    try:
        _fj["cache"] = lire_fj()
    except Exception as e:
        if getattr(e, "code", None) == 429:
            _fj["pause"] = now + 900
            print("⚠️ FinancialJuice limite les requêtes : pause de 15 min")
        else:
            print(f"⚠️ Flashs FinancialJuice : {e}")
    return _fj["cache"]

def tous_les_flashs():
    flashs = []
    for canal in CANAUX_FLASH:
        try:
            flashs.extend(lire_canal(canal))
        except Exception as e:
            print(f"⚠️ Flashs {canal} : {e}")
    flashs.extend(flashs_fj())
    return sorted(flashs, key=lambda f: f["ts"])

def est_flash(f):
    t = f["texte"]
    filtre = FILTRE_FJ if f.get("canal") == "FinancialJuice" else FILTRE
    return bool(filtre.search(t)) and not EXCLUS_FLASH.search(t) and not PRIX_FLASH.search(t)

CATEGORIES = [
    (r"\b(hack\w*|exploit\w*|stolen|drained|breach)\b", "🔓", "PIRATAGE"),
    (r"\b(sues?|sued|lawsuit|court|judge|charged|sentenced|arrest\w*|fraud|indict\w*|settle\w*)\b", "⚖️", "JUSTICE"),
    (r"\betfs?\b", "📊", "ETF"),
    (r"\b(sec|cftc|regulat\w*|bill|law|senate|congress|mica|esma|licen[cs]e\w*|ban\w*|treasury)\b", "🏛️", "RÉGULATION"),
    (r"\b(stablecoins?|usdt|usdc|tether|rlusd)\b", "💵", "STABLECOIN"),
    (r"\b(list(s|ing|ed)?|delist\w*)\b", "🆕", "LISTING"),
    (r"\b(buys?|bought|acquires?|adds?|holdings|reserves?)\b.*\b(bitcoin|btc|eth|ether|sol|xrp|bnb)\b", "🐋", "ACHATS"),
    (r"\b(raises?|funding|valuation|ipo|acquisition|merger|shut\w* down|layoffs?)\b", "🏢", "ENTREPRISES"),
]

def categorie(texte_en):
    for motif, emoji, nom in CATEGORIES:
        if re.search(motif, texte_en, re.I):
            return emoji, nom
    return "⚡", "FLASH"

def polir(fr):
    t = fr.strip()
    t = re.sub(r"\bla cryptographie\b", "la crypto", t, flags=re.I)
    t = re.sub(r"\bcryptographie\b", "crypto", t, flags=re.I)
    t = re.sub(r"(\d[\d.,]*)\s*milliards? de dollars", r"\1 Md$", t)
    t = re.sub(r"(\d[\d.,]*)\s*millions? de dollars", r"\1 M$", t)
    t = re.sub(r"(\d[\d.,]*)\s*milliards? de \$", r"\1 Md$", t)
    t = re.sub(r"(\d[\d.,]*)\s*millions? de \$", r"\1 M$", t)
    t = re.sub(r'"([^"]+)"', lambda m: "« " + m.group(1).strip() + " »", t)
    if t and t[-1] not in ".!?»":
        t += "."
    return t[0].upper() + t[1:] if t else t

IMPORTANT = re.compile(
    r"\b(approv\w*|reject\w*|bankrupt\w*|insolven\w*|halt\w*|suspend\w*|strategic (bitcoin )?reserve|"
    r"executive order|emergency|collaps\w*|depeg\w*|hack\w*|exploit\w*|drained|stolen|seiz\w*)\b", re.I)
SEPARATEUR = "———————————————"
LIB = {"PIRATAGE": "Piratage", "JUSTICE": "Justice", "ETF": "ETF", "RÉGULATION": "Régulation",
       "STABLECOIN": "Stablecoin", "LISTING": "Listing", "ACHATS": "Achats",
       "ENTREPRISES": "Entreprises", "FLASH": "Crypto"}

def est_alerte(f):
    return bool(f.get("urgent")) or bool(IMPORTANT.search(f["texte"]))

def envoyer_flash(token, f, recents=None, force_alerte=False):
    fr = traduire(f["texte"])
    if not fr:
        print("⏳ Flash reporté (traduction impossible) :", f["texte"][:80])
        return None
    fr = polir(fr)
    if recents is not None and est_doublon(fr, recents):
        print("↩️ Doublon ignoré :", fr)
        return False
    emoji, nom = categorie(f["texte"])
    if force_alerte or est_alerte(f):
        titre = "CRYPTO" if nom == "FLASH" else nom
        texte = f"🚨 <b>ALERTE {titre}</b> 🚨\n{SEPARATEUR}\n<i>{html.escape(fr)}</i>\n{SEPARATEUR}"
    else:
        texte = f"▫️ <i><u>{LIB.get(nom, nom)}</u> : {html.escape(fr)}</i>"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": texte, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20) as r:
            ok = bool(json.load(r).get("ok"))
    except Exception as e:
        print("❌ Envoi Telegram impossible :", e)
        ok = False
    print(("✅ " if ok else "❌ ") + texte.split("\n")[0] + " | " + fr)
    time.sleep(3)
    if ok and recents is not None:
        recents.append(sorted(mots(fr)))
    return True if ok else None

def passage_flash(token, mode_test=False):
    flashs = tous_les_flashs()
    if mode_test:
        ok = [f for f in flashs if est_flash(f)]
        print(f"Mode test flashs : envoi de 3 flashs sur {len(ok)} retenus.")
        for f in ok[-3:]:
            envoyer_flash(token, f)
        return
    vus, recents = charger(FICHIER_VUS), charger(FICHIER_TITRES)
    deja = set(vus)
    premier = not any(str(v).startswith("tg:") for v in vus)
    nouveaux = [f for f in flashs if f["id"] not in deja]
    if not any(str(v).startswith("fj:") for v in vus):
        vus += [f["id"] for f in nouveaux if f["id"].startswith("fj:")]
        nouveaux = [f for f in nouveaux if not f["id"].startswith("fj:")]
    if premier:
        vus += [f["id"] for f in nouveaux]
        sauver(FICHIER_VUS, vus, 3000)
        print(f"Initialisation des flashs : {len(nouveaux)} flashs marqués comme déjà vus, rien n'est envoyé.")
        return
    retenus = []
    for f in nouveaux:
        if est_flash(f):
            retenus.append(f)
        else:
            vus.append(f["id"])
    for f in retenus[:-MAX_FLASH_PAR_PASSAGE]:
        vus.append(f["id"])
    for f in retenus[-MAX_FLASH_PAR_PASSAGE:]:
        if envoyer_flash(token, f, recents) is not None:
            vus.append(f["id"])
    sauver(FICHIER_VUS, vus, 3000)
    sauver(FICHIER_TITRES, recents, 300)

def apercu_flash():
    for f in tous_les_flashs():
        etat = "✅" if est_flash(f) else ("💲" if PRIX_FLASH.search(f["texte"]) else "🚫")
        print(f"{etat} [{f['canal']}] {f['texte'][:150]}")

def test_styles(token):
    crypto = [a for a in tous_les_articles() if est_crypto(a)]
    if not crypto:
        print("Aucun article crypto trouvé.")
        return
    for style in ("actuel", "A", "B"):
        print(f"--- Style {style} ---")
        envoyer(token, crypto[-1], style)

def test_alerte(token):
    ok = [f for f in tous_les_flashs() if est_flash(f)]
    if ok:
        envoyer_flash(token, ok[-1], force_alerte=True)

def test_images(token):
    articles = [a for a in tous_les_articles() if est_crypto(a)]
    for source in FLUX:
        derniers = [a for a in articles if a["source"] == source]
        if derniers:
            a = derniers[-1]
            print(f"--- {source} : {'image trouvée' if a.get('image') else 'pas d image dans le flux'}")
            envoyer(token, a)

if __name__ == "__main__":
    if "--apercu" in sys.argv:
        apercu()
        print("\n----- FLASHS (✅ gardé · 🚫 écarté · 💲 flash de prix, laissé au bot Alerts) -----")
        apercu_flash()
        sys.exit()
    token = lire_token()
    if "--test" in sys.argv:
        passage(token, mode_test=True)
    elif "--test-styles" in sys.argv:
        test_styles(token)
    elif "--test-alerte" in sys.argv:
        test_alerte(token)
    elif "--test-images" in sys.argv:
        test_images(token)
    elif "--test-flash" in sys.argv:
        passage_flash(token, mode_test=True)
    elif "--cycle" in sys.argv:
        fin = time.time() + int(os.environ.get("CYCLE_SECONDS", "270"))
        while True:
            for fn in (passage, passage_flash):
                try:
                    fn(token)
                except Exception as e:
                    print("⚠️ Erreur :", e)
            if time.time() + 60 > fin:
                break
            time.sleep(60)
    elif "--boucle" in sys.argv:
        print("Bot News lancé en continu : articles + flashs (Ctrl+C pour arrêter).")
        while True:
            for fn in (passage, passage_flash):
                try:
                    fn(token)
                except Exception as e:
                    print("⚠️ Erreur :", e)
            time.sleep(60)
    else:
        passage(token)
        passage_flash(token)
