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


def tweet(message_html):
    """Construit le tweet : texte de l'annonce + hashtags + signature, 280 caractères maximum."""
    corps = nettoyer(message_html)
    tags = hashtags(corps)
    sig = lire("signature.txt", [SIGNATURE_DEFAUT])
    pied = []
    if tags:
        pied.append(" ".join(tags))
    if sig:
        pied.append(sig[0])
    fin = ("\n\n" + "\n".join(pied)) if pied else ""
    corps = couper(corps, LIMITE - poids(fin))
    return corps + fin


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
        texte = tweet(message_html)
        lien = "https://x.com/intent/post?text=" + urllib.parse.quote(texte, safe="")
        entete = f"<b>📝 Brouillon X</b>{' · ' + html.escape(source) if source else ''} · {poids(texte)}/{LIMITE}"
        corps = f"{entete}\n\n<blockquote>{html.escape(texte)}</blockquote>"
        bouton = json.dumps({"inline_keyboard": [[{"text": "Publier sur X", "url": lien}]]})
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
    ("US", "\U0001F534 <b><u>Powell</u> :</b>\n\n<i>L'inflation reste trop élevée, nous resterons dépendants des données</i>\n"
           + "─" * 14),
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
    if not (TOKEN and CHAT_ID):
        sys.exit("Il manque X_DRAFTS_TOKEN ou X_DRAFTS_CHAT_ID.")
    n = sum(brouillon(m, f"{src} · TEST", silencieux=True) for src, m in TESTS)
    print(f"{n}/{len(TESTS)} brouillons de test envoyés.")
    if n < len(TESTS):
        sys.exit(1)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    {"--chat-id": cmd_chat_id, "--test": cmd_test}.get(arg, lambda: print(__doc__))()
