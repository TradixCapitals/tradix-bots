#!/usr/bin/env python3
"""Brouillons X (Twitter) : chaque annonce importante devient un tweet prêt à publier.

Le tweet est envoyé dans un canal Telegram privé (« Tradix - Brouillons X »), avec un bouton
« Publier sur X » qui ouvre X avec le texte déjà rempli : il ne reste qu'à appuyer sur Poster.
Aucune API X, donc 100 % gratuit.

Réglages (secrets du dépôt) : X_DRAFTS_TOKEN (bot des brouillons) et X_DRAFTS_CHAT_ID (canal privé).
Sans ces deux secrets, rien n'est envoyé et les bots fonctionnent comme avant.

Fichiers modifiables dans x/ :
    hashtags.txt   mots-clés -> hashtag (2 hashtags maximum par tweet)
    signature.txt  ligne ajoutée en bas de chaque tweet (fichier vide = pas de signature)

Usage :
    python3 x_drafts.py --chat-id   affiche l'identifiant du canal (demande le token, invisible)
    python3 x_drafts.py --test      envoie 5 brouillons de test, sans notification
"""
import getpass
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
X_DIR = os.path.join(HERE, "x")
TOKEN = os.environ.get("X_DRAFTS_TOKEN", "").strip()
CHAT_ID = os.environ.get("X_DRAFTS_CHAT_ID", "").strip()
LIMITE = 280
X_PAGE = os.environ.get("X_PAGE", "https://tradixcapitals.github.io/tradix-legal/x.html")

HASHTAGS_DEFAUT = [
    "Fed, FOMC, Powell, Réserve fédérale = #Fed",
    "or, gold, XAU = #Or",
    "NFP, emplois non agricoles, payrolls = #NFP",
    "CPI, PCE, inflation = #Inflation",
    "BCE, Lagarde = #BCE",
    "Iran, Ormuz, Israël = #Géopolitique",
    "BTC, Bitcoin = #Bitcoin",
    "ETH, Ethereum = #Ethereum",
    "SOL, Solana = #Solana",
    "XRP = #XRP",
    "BNB = #BNB",
]
SIGNATURE_DEFAUT = "⚡ Le live des marchés en français : lien en bio"


def lire(nom, defaut):
    """Lit un fichier de réglages de x/ (lignes vides et # ignorées). Le crée s'il n'existe pas."""
    chemin = os.path.join(X_DIR, nom)
    if not os.path.exists(chemin):
        return defaut
    with open(chemin, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def poids(texte):
    """Longueur comptée comme X : la plupart des caractères = 1, emojis et caractères asiatiques = 2."""
    n = 0
    for c in texte:
        o = ord(c)
        if o in (0xFE0F, 0x200D):
            continue
        n += 1 if (o <= 0x10FF or 0x2000 <= o <= 0x206F) else 2
    return n


def couper(texte, maxi):
    if poids(texte) <= maxi:
        return texte
    while texte and poids(texte + "…") > maxi:
        texte = texte[:-1]
    return texte.rstrip(" ,;:-") + "…"


def mot_present(mot, texte):
    return re.search(r"(?<![\w#])" + re.escape(mot) + r"(?!\w)", texte, re.I) is not None


def hashtags(texte):
    tags = []
    for ligne in lire("hashtags.txt", HASHTAGS_DEFAUT):
        mots, _, tag = ligne.rpartition("=")
        tag = tag.strip()
        if tag and tag not in tags and tag.lower() not in texte.lower() and \
                any(mot_present(m.strip(), texte) for m in mots.split(",") if m.strip()):
            tags.append(tag)
        if len(tags) == 2:
            break
    return tags


def nettoyer(message_html):
    """Message Telegram (HTML) -> texte brut, sans les lignes de séparation."""
    t = re.sub(r"<br\s*/?>", "\n", message_html)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    lignes = [l.strip() for l in t.split("\n")]
    lignes = [l for l in lignes if not re.fullmatch(r"[─━\-─━=_ ]{3,}", l)]
    t = "\n".join(lignes)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


# ---------- Modèle unique des tweets : « EMOJI TYPE | Sujet », contenu, hashtags + signature ----------
SIGLES = {"NFP", "ADP", "ISM", "PMI", "CPI", "PCE", "PPI", "PIB", "GDP", "BCE", "BOE", "BOJ", "BNS", "RBA", "RBNZ",
          "FED", "FOMC", "US", "USA", "UE", "EU", "ZEW", "IFO", "JOLTS", "API", "EIA", "OPEP", "OPEC", "IPC",
          "HICP", "IPCH", "S&P", "CFTC", "BTC", "ETH", "SOL", "XRP", "BNB", "ATH", "ETF", "IA", "PBOC", "BPC"}
REGIONS = {"us": "États-Unis", "eur": "Europe", "asia": "Asie"}
CRYPTOS_NOMS = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "XRP", "BNB": "BNB"}
EMOJI_RE = re.compile(r"^((?:[\U0001F1E6-\U0001F1FF]{2})|[\U0001F300-\U0001FAFF☀-➿]️?)\s*")


def casse(texte):
    """'EMPLOIS NON AGRICOLES (NFP)' -> 'Emplois non agricoles (NFP)' (sigles et parenthèses gardés)."""
    mots, dans_paren = [], False
    for m in texte.split(" "):
        if m.startswith("("):
            dans_paren = True
        brut = re.sub(r"[^\w&]", "", m).upper()
        garder = dans_paren or brut in SIGLES or re.fullmatch(r"[\d.,/%]+\w{0,2}", brut or "x") is not None
        mots.append(m if garder else m.lower())
        if m.endswith(")"):
            dans_paren = False
    t = " ".join(mots)
    return t[:1].upper() + t[1:]


def titre_mots(texte):
    """'IRAN · ORMUZ' -> 'Iran · Ormuz'."""
    return " ".join(m if re.sub(r"[^\w&]", "", m).upper() in SIGLES else m[:1].upper() + m[1:].lower()
                    for m in texte.split(" "))


def sans_emoji(ligne):
    while True:
        m = EMOJI_RE.match(ligne)
        if not m:
            return ligne.strip()
        ligne = ligne[m.end():]


def structurer(message_html, source=""):
    """Renvoie (en-tête, liste de blocs de contenu) selon le type d'annonce."""
    texte = nettoyer(message_html)
    lignes = texte.split("\n")
    premiere = lignes[0].strip()
    reste = "\n".join(lignes[1:]).strip()
    blocs = [b.strip() for b in re.split(r"\n\s*\n", reste) if b.strip()]
    if not blocs and len(reste) == 0:
        blocs = []
    crypto = source.lower().startswith("crypto")

    if crypto:  # bot Crypto Alerts
        m = re.search(r"ALERTE\s+(\w+)", premiere)
        a = re.search(r"NOUVEL ATH\s+(\w+)", premiere)
        if a:
            sujet = CRYPTOS_NOMS.get(a.group(1), a.group(1))
        elif m:
            sujet = CRYPTOS_NOMS.get(m.group(1), titre_mots(m.group(1)))
        elif "RÉSUMÉ" in premiere.upper():
            date = premiere.split("·", 1)[1].strip() if "·" in premiere else ""
            sujet = "Résumé du matin" + (f" · {date}" if date else "")
        else:
            sujet = "Marché crypto"
        return f"🪙 CRYPTO | {sujet}", blocs or [sans_emoji(premiere)]

    m = re.match(r"^🚨\s*ALERTE\s+(.+?)\s*🚨$", premiere)
    if m:  # alerte géopolitique
        return f"🚨 ALERTE | {titre_mots(m.group(1))}", ["\n".join(blocs)] if blocs else []

    corps_premiere = sans_emoji(premiere)
    emoji_tag = ""
    m = re.match(r"^🔴\s*((?:[\U0001F1E6-\U0001F1FF]{2})|[\U0001F300-\U0001FAFF]️?)", premiere)
    if m:
        emoji_tag = m.group(1)

    if "Publié :" in texte:  # donnée chiffrée
        return f"{emoji_tag or '📊'} MACRO | {casse(corps_premiere)}", ["\n".join(blocs)]

    if corps_premiere.endswith(":") and blocs:  # discours ou série de déclarations
        nom = corps_premiere[:-1].strip()
        if re.search(r"minutes|procès-verbal|compte rendu", nom, re.I):
            return f"🏦 MACRO | {nom}", blocs
        cites = []
        for b in blocs:
            puce = b.startswith("•")
            phrase = re.sub(r"^[•\-]\s*", "", b).strip()
            cites.append(("• " if puce else "") + f"« {phrase} »")
        return f"🎙 DISCOURS | {nom}", cites

    region = REGIONS.get(source.split()[0].lower(), "Marchés") if source else "Marchés"
    if blocs and corps_premiere.upper() == corps_premiere:  # annonce avec détails
        return f"🔴 FLASH | {casse(corps_premiere)}", blocs
    return f"🔴 FLASH | {region}", [corps_premiere] + blocs


MAX_TWEETS = 4  # au-delà, le reste est laissé de côté (les points les plus récents passent en premier)


def pied_de(texte):
    tags = hashtags(texte)
    sig = lire("signature.txt", [SIGNATURE_DEFAUT])
    pied = ([" ".join(tags)] if tags else []) + ([sig[0]] if sig else [])
    return ("\n\n" + "\n".join(pied)) if pied else ""


def tweets(message_html, source=""):
    """Découpe l'annonce en tweets complets de 280 caractères maximum, sans couper une phrase.

    Une annonce courte = 1 tweet. Une longue série (ex. minutes de la Fed) = plusieurs tweets autonomes,
    chacun avec le titre, autant de points entiers que possible, les hashtags et la signature.
    """
    titre, points = structurer(message_html, source)
    sortie, courant = [], []

    def assembler(liste):
        if len(liste) == 1:  # un seul point : pas de puce
            liste = [re.sub(r"^[\u2022\-]\s*", "", liste[0])]
        return "\n\n".join(([titre] if titre else []) + liste)

    def fermer():
        if courant:
            t = assembler(courant)
            sortie.append(t + pied_de(t))
            courant.clear()

    for pt in points:
        essai = assembler(courant + [pt])
        if poids(essai + pied_de(essai)) <= LIMITE:
            courant.append(pt)
            continue
        fermer()
        seul = assembler([pt])
        place = LIMITE - poids(pied_de(seul)) - (poids(titre) + 2 if titre else 0)
        courant.append(pt if poids(seul + pied_de(seul)) <= LIMITE else couper_phrase(pt, place))
    fermer()
    return sortie[:MAX_TWEETS]


def couper_phrase(texte, maxi):
    """Raccourcit à la dernière phrase entière qui tient, sinon au dernier mot."""
    if poids(texte) <= maxi:
        return texte
    morceau = texte
    while poids(morceau) > maxi:
        k = max(morceau.rfind(". ", 0, len(morceau) - 1), morceau.rfind("; ", 0, len(morceau) - 1))
        if k <= 0:
            return couper(texte, maxi)
        morceau = morceau[:k + 1]
    return morceau


def tweet(message_html, source=""):
    return tweets(message_html, source)[0]


def tg(methode, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{methode}", data=data,
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            return {"ok": False, "description": f"HTTP {e.code}"}


def brouillon(message_html, source="", silencieux=False):
    """Envoie le brouillon de tweet dans le canal privé. Ne bloque jamais le bot si ça échoue."""
    if not (TOKEN and CHAT_ID):
        return False
    try:
        liste = tweets(message_html, source)
    except Exception as e:
        print("Brouillon X impossible :", e, flush=True)
        return False
    ok = True
    for n, texte in enumerate(liste, 1):
        src = source + (f" · {n}/{len(liste)}" if len(liste) > 1 else "")
        ok = envoyer_brouillon(texte, src, silencieux) and ok
    return ok


def envoyer_brouillon(texte, source, silencieux):
    try:
        # Page relais (GitHub Pages) qui ouvre l'app X avec le texte ; le texte reste après « # », jamais envoyé au serveur
        lien = X_PAGE + "#" + urllib.parse.quote(texte, safe="")
        entete = f"<b>📝 Brouillon X</b>{' · ' + html.escape(source) if source else ''} · {poids(texte)}/{LIMITE}"
        corps = f"{entete}\n\n<blockquote>{html.escape(texte)}</blockquote>"
        ligne = [{"text": "Publier sur X", "url": lien}]
        if len(texte) <= 256:  # limite Telegram du bouton « copier »
            ligne.insert(0, {"text": "Copier le tweet", "copy_text": {"text": texte}})
        bouton = json.dumps({"inline_keyboard": [ligne]})
        for _ in range(3):
            r = tg("sendMessage", chat_id=CHAT_ID, text=corps, parse_mode="HTML",
                   disable_web_page_preview="true", reply_markup=bouton,
                   disable_notification="true" if silencieux else "false")
            if r.get("ok"):
                return True
            attente = (r.get("parameters") or {}).get("retry_after")
            if not attente:
                print("Brouillon X refusé par Telegram :", r.get("description"), flush=True)
                return False
            time.sleep(int(attente) + 1)
    except Exception as e:
        print("Brouillon X impossible :", e, flush=True)
    return False


TESTS = [
    ("US", "\U0001F534 \U0001F1FA\U0001F1F8 <b><u>EMPLOIS NON AGRICOLES (NFP)</u></b>\n\n<b><i>Publié : 254K</i></b> ▲\n"
           "<i>Prévu : 150K · Précédent : 159K</i>\n" + "─" * 14),
    ("US", "\U0001F534 <b><u>Minutes du FOMC</u> :</b>\n\n"
           "<i>• La plupart des participants ont jugé approprié de poursuivre l'assouplissement monétaire lors des prochaines réunions</i>\n\n"
           "<i>• Plusieurs participants ont noté que les risques à la hausse sur l'inflation restaient élevés en raison des droits de douane</i>\n\n"
           "<i>• Le marché du travail montre des signes de ralentissement progressif</i>\n" + "─" * 14),
    ("US", "\U0001F6A8 <b>ALERTE IRAN · ORMUZ</b> \U0001F6A8\n" + "━" * 14 +
           "\n<b><i>L'Iran affirme qu'il répondra à toute attaque contre ses installations pétrolières</i></b>\n" + "━" * 14),
    ("EUR", "\U0001F534 <b><u>Lagarde</u> :</b>\n\n<i>La BCE n'est pas pressée de baisser à nouveau ses taux</i>\n"
            + "─" * 14),
    ("Crypto Alerts", "\U0001F6A8 <b>ALERTE BTC</b> \U0001F6A8\n━━━━━━━━━━━━━━━━\n<i>▲ Hausse de <b>4,2 %</b> en 1 h\n"
                      "Prix : <b>124 500 $</b> · 24 h : <b>+5,1 %</b></i>\n━━━━━━━━━━━━━━━━"),
]


def cmd_chat_id():
    global TOKEN
    TOKEN = TOKEN or getpass.getpass("Token du bot des brouillons (invisible, colle puis Entrée) : ").strip()
    r = tg("getUpdates", allowed_updates=json.dumps(["channel_post", "my_chat_member", "message"]))
    if not r.get("ok"):
        sys.exit("Erreur Telegram : " + str(r.get("description")))
    vus = {}
    for u in r.get("result", []):
        m = u.get("channel_post") or u.get("my_chat_member") or u.get("message") or {}
        c = m.get("chat")
        if c:
            vus[c["id"]] = c.get("title") or c.get("username") or "?"
    if not vus:
        sys.exit("Rien reçu. Écris un message (ex. « test ») dans le canal privé, puis relance la commande.")
    for cid, nom in vus.items():
        print(f"{cid}   {nom}")


def cmd_test():
    global TOKEN, CHAT_ID
    CHAT_ID = CHAT_ID or "-1003875078448"  # canal « Tradix - Brouillons X »
    TOKEN = TOKEN or getpass.getpass("Token du bot des brouillons (invisible, colle puis Entrée) : ").strip()
    n = sum(brouillon(m, f"{src} · TEST", silencieux=True) for src, m in TESTS)
    print(f"{n}/{len(TESTS)} annonces de test envoyées en brouillons.")
    if n < len(TESTS):
        sys.exit(1)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    {"--chat-id": cmd_chat_id, "--test": cmd_test}.get(arg, lambda: print(__doc__))()
