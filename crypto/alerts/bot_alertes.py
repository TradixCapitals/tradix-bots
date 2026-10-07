import os, sys, json, time, math, getpass, re, html, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

CHAT_ID = "-1004338002022"
DOSSIER = os.path.dirname(os.path.abspath(__file__))
FICHIER_ETAT = os.path.join(DOSSIER, "etat.json")
TZ = ZoneInfo("Europe/Paris")
HEURE_RESUME = 8

CRYPTOS = {  # id CoinGecko : (symbole, pas des niveaux ronds)
    "bitcoin":     ("BTC", 1000),
    "ethereum":    ("ETH", 100),
    "solana":      ("SOL", 5),
    "ripple":      ("XRP", 0.05),
    "binancecoin": ("BNB", 25),
}
SEUIL_1H = 3.0      # % en 1 h
PAS_24H = 5.0       # paliers de % sur 24 h
SEUILS = {"BTC": (2.0, 4.0), "ETH": (3.0, 5.0), "BNB": (3.0, 5.0), "SOL": (4.0, 7.0), "XRP": (4.0, 7.0)}  # (1 h, 24 h)
ANTI_SPAM = 3600    # secondes entre deux alertes identiques

FG_FR = {"Extreme Fear": "Peur extrême", "Fear": "Peur", "Neutral": "Neutre",
         "Greed": "Avidité", "Extreme Greed": "Avidité extrême"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
CG = "https://api.coingecko.com/api/v3"

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

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def charger_etat():
    try:
        with open(FICHIER_ETAT) as f:
            return json.load(f)
    except Exception:
        return {}

def sauver_etat(etat):
    with open(FICHIER_ETAT, "w") as f:
        json.dump(etat, f, indent=1)

def fmt_prix(p):
    if p >= 1000:
        s = f"{p:,.0f}".replace(",", " ")
    elif p >= 1:
        s = f"{p:.2f}".replace(".", ",")
    else:
        s = f"{p:.4f}".replace(".", ",")
    return s + " $"

def fmt_pct(x):
    return f"{x:+.1f}".replace(".", ",").replace("-", "−") + " %"

SEP = "━━━━━━━━━━━━━━━━"
NOMS = {"BTC": "BITCOIN", "ETH": "ETHEREUM", "SOL": "SOLANA", "XRP": "XRP", "BNB": "BNB"}

def fmt_abs(x):
    return f"{abs(x):.1f}".replace(".", ",") + " %"

def grosse(titre, *lignes):
    return f"{titre}\n{SEP}\n<i>" + "\n".join(lignes) + f"</i>\n{SEP}"

def petite(texte):
    return f"▫️ <i>{texte}</i>"

def peut(etat, cle, t):
    if t - etat["derniere"].get(cle, 0) >= ANTI_SPAM:
        etat["derniere"][cle] = t
        return True
    return False

def envoyer(token, texte):
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": texte, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20) as r:
            ok = bool(json.load(r).get("ok"))
    except Exception as e:
        print("❌ Envoi Telegram impossible :", e)
        ok = False
    print(("✅ " if ok else "❌ ") + texte.split("\n")[0])
    time.sleep(1)
    return ok

def resume(marche, etat, d):
    lignes = []
    for cid, (sym, _) in CRYPTOS.items():
        c = next((x for x in marche if x["id"] == cid), None)
        if c:
            h24 = c.get("price_change_percentage_24h_in_currency") or 0
            fleche = "▲" if h24 >= 0 else "▼"
            lignes.append(f"{fleche} <u>{sym}</u> : <b>{fmt_prix(c['current_price'])}</b> ({fmt_pct(h24)})")
    try:
        dom = f"{get(CG + '/global')['data']['market_cap_percentage']['btc']:.1f}".replace(".", ",") + " %"
    except Exception:
        dom = "indisponible"
    fg = f"{etat.get('fg_val', '?')} — {FG_FR.get(etat.get('fg'), etat.get('fg', '?'))}"
    date = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return (f"☀️ <b>RÉSUMÉ CRYPTO</b> ☀️ · <i>{date}</i>\n{SEP}\n" + "\n".join(lignes) +
            f"\n\n<i>Fear & Greed : <b>{fg}</b>\nDominance BTC : <b>{dom}</b></i>\n{SEP}")

# ===================== FLUX ETF (point quotidien) =====================
MOIS_EN = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
ETF_ACTIFS = [("Bitcoin", "BTC"), ("Ethereum", "ETH"), ("Solana", "SOL"), ("XRP", "XRP")]

def montant_fr(signe, val, unite):
    v = float(val.replace(",", ""))
    s = f"{v:,.1f}".replace(",", " ").replace(".", ",")
    s = s[:-2] if s.endswith(",0") else s
    return ("−" if signe == "-" else "+") + s + {"K": " k$", "M": " M$", "B": " Md$", "": " $"}[unite.upper()]

def lire_etf():
    req = urllib.request.Request("https://t.me/s/lookonchainchannel", headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
    dernier = None
    for m in page.split('data-post="')[1:]:
        post = m.split('"', 1)[0]
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', m, re.S)
        if t:
            texte = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", t.group(1))))
            if "ETF" in texte and "1D NetFlow" in texte:
                dernier = (post, texte)
    return dernier

def parse_etf(texte):
    d = re.search(r"\b([A-Z][a-z]{2})\w*\s+(\d{1,2})\s+Update", texte)
    date = f"{int(d.group(2))} {MOIS[MOIS_EN[d.group(1)] - 1]}" if d and d.group(1) in MOIS_EN else ""
    flux = r"NetFlow\s*:\s*([+-]?)([\d,.]+)\s*\$?\s*\w+\s*\(\s*([+-]?)\s*\$\s*([\d,.]+)\s*([KMB]?)\s*\)"
    lignes, semaine = [], []
    for nom, tick in ETF_ACTIFS:
        bloc = re.search(rf"{nom}\s+ETFs?\s*:(.*?)(?=#|$)", texte, re.S | re.I)
        if not bloc:
            continue
        un = re.search(r"1D\s*" + flux, bloc.group(1), re.I)
        sept = re.search(r"7D\s*" + flux, bloc.group(1), re.I)
        if un:
            sg = un.group(3) or un.group(1)
            lignes.append(f"{'▼' if sg == '-' else '▲'} <u>{tick}</u> : <b>{montant_fr(sg, un.group(4), un.group(5))}</b> "
                          f"({'−' if sg == '-' else '+'}{un.group(2).replace(',', ' ')} {tick})")
        if sept:
            s7 = sept.group(3) or sept.group(1)
            semaine.append(f"{tick} <b>{montant_fr(s7, sept.group(4), sept.group(5))}</b>")
    return date, lignes, semaine

def message_etf(date, lignes, semaine):
    corps = "\n".join(lignes)
    if semaine:
        corps += "\n\n<i>Sur 7 jours : " + " · ".join(semaine) + "</i>"
    return f"🔹 <b>FLUX ETF</b> 🔹 · <i>{date}</i>\n{SEP}\n{corps}\n{SEP}"

def verifier_etf(etat, alertes, premier, maintenant):
    if maintenant - etat.get("etf_ts", 0) < 600:
        return
    etat["etf_ts"] = maintenant
    try:
        r = lire_etf()
    except Exception as e:
        print("⚠️ Flux ETF :", e)
        return
    if not r or r[0] == etat.get("etf_post"):
        return
    deja = "etf_post" in etat
    etat["etf_post"] = r[0]
    if premier or not deja:
        return
    date, lignes, semaine = parse_etf(r[1])
    if lignes:
        alertes.append(message_etf(date, lignes, semaine))

# ===================== BALEINES (gros transferts) =====================
SEUIL_BALEINE = 50_000_000   # montant minimum en $
JETONS_BALEINE = {"BTC", "ETH", "SOL", "XRP", "BNB", "USDT", "USDC"}
INCLURE_INCONNUS = False     # False = ignorer les transferts entre deux portefeuilles inconnus
TRAD_BALEINE = {"unknown wallet": "wallet inconnu", "unknown new wallet": "nouveau wallet inconnu"}

def qte_fr(x):
    for div, suf in ((1e9, " Md"), (1e6, " M"), (1e3, " k")):
        if x >= div:
            s = f"{x / div:.1f}".replace(".", ",")
            return (s[:-2] if s.endswith(",0") else s) + suf
    return f"{x:.0f}"

def lieu(t):
    t = (t or "").strip().rstrip(".").lstrip("#").strip()
    if re.match(r"unknown whale", t, re.I):
        return "whale inconnue"
    return TRAD_BALEINE.get(t.lower(), t)

def lire_baleines():
    req = urllib.request.Request("https://t.me/s/whale_alert_io", headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
    res = []
    for m in page.split('data-post="')[1:]:
        post = m.split('"', 1)[0]
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', m, re.S)
        if not t:
            continue
        texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t.group(1)))).replace("Details", "").strip()
        mm = re.search(r"([\d,.]+)\s*#?\$?([A-Z0-9]{2,10})\s*\(\s*([\d,.]+)\s*USD\s*\)\s*(transferred|minted|burned|burnt)\b"
                       r"(?:\s+at\s+(.+?))?(?:\s+from\s+(.+?))?(?:\s+to\s+(.+?))?\s*$", texte, re.I)
        if mm:
            res.append((post, mm))
    return res

def message_baleine(mm):
    qty, tok, usd = float(mm.group(1).replace(",", "")), mm.group(2).upper(), float(mm.group(3).replace(",", ""))
    action = mm.group(4).lower()
    if tok not in JETONS_BALEINE or usd < SEUIL_BALEINE:
        return None
    if action == "transferred":
        a, d = lieu(mm.group(6) or "?"), lieu(mm.group(7) or "?")
        if not INCLURE_INCONNUS and "inconnu" in a and "inconnu" in d:
            return None
        detail = f"{a} → {d}"
    else:
        ou = lieu(mm.group(5) or mm.group(7) or mm.group(6) or "")
        detail = ("créés" if action == "minted" else "détruits") + (f" ({ou})" if ou else "")
    return petite(f"<u>Whale {tok}</u> : <b>{qte_fr(qty)} {tok}</b> (<b>{qte_fr(usd)}$</b>) · {detail}")

def verifier_baleines(etat, alertes, premier, maintenant):
    if maintenant - etat.get("baleines_ts", 0) < 120:
        return
    etat["baleines_ts"] = maintenant
    try:
        liste = lire_baleines()
    except Exception as e:
        print("⚠️ Baleines :", e)
        return
    deja = "baleines_vus" in etat
    vus = etat.setdefault("baleines_vus", [])
    nouveaux = [(p, mm) for p, mm in liste if p not in vus]
    vus.extend(p for p, _ in nouveaux)
    del vus[:-300]
    if premier or not deja:
        return
    envoyes = 0
    for _, mm in nouveaux:
        msg = message_baleine(mm)
        if msg and envoyes < 5:
            alertes.append(msg)
            envoyes += 1

# ===================== FUNDING & OPEN INTEREST (Hyperliquid) =====================
FUNDING_HAUT = 50.0    # % annualisé : au-dessus = trop de positions longues
FUNDING_BAS = -20.0    # % annualisé : en dessous = trop de positions courtes
OI_SEUIL = 8.0         # % de variation de l'open interest en 1 h
SYMS_HL = ["BTC", "ETH", "SOL", "XRP", "BNB"]

def lire_hyperliquid():
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                 data=json.dumps({"type": "metaAndAssetCtxs"}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        meta, ctxs = json.load(r)
    res = {}
    for info, ctx in zip(meta["universe"], ctxs):
        if info["name"] in SYMS_HL:
            prix = float(ctx.get("markPx") or 0)
            res[info["name"]] = {"funding": float(ctx.get("funding") or 0) * 24 * 365 * 100,
                                 "oi": float(ctx.get("openInterest") or 0) * prix}
    return res

def fmt_usd(x):
    return qte_fr(x) + "$"

def fmt_pct0(x):
    return f"{x:+.0f}".replace("-", "−") + " %"

def msg_funding(sym, f):
    if f >= 0:
        return grosse(f"🚨 <b>ALERTE FUNDING {sym}</b> 🚨", f"Funding : <b>{fmt_pct0(f)}</b> annualisé",
                      "Trop de positions longues · risque de purge à la baisse")
    return grosse(f"🚨 <b>ALERTE FUNDING {sym}</b> 🚨", f"Funding : <b>{fmt_pct0(f)}</b> annualisé",
                  "Trop de positions courtes · risque de short squeeze")

def msg_oi(sym, var, oi):
    expl = "Les positions à effet de levier s'accumulent" if var > 0 else "Les positions se ferment (liquidations ou prises de profits)"
    return grosse(f"🚨 <b>ALERTE OPEN INTEREST {sym}</b> 🚨",
                  f"{'▲' if var > 0 else '▼'} <b>{fmt_pct(var)}</b> en 1 h · <b>{fmt_usd(oi)}</b>", expl)

def verifier_derives(etat, alertes, premier, maintenant):
    if maintenant - etat.get("hl_ts", 0) < 300:
        return
    etat["hl_ts"] = maintenant
    try:
        donnees = lire_hyperliquid()
    except Exception as e:
        print("⚠️ Hyperliquid :", e)
        return
    zones = etat.setdefault("funding_zone", {})
    hist = etat.setdefault("oi_hist", {})
    for sym, d in donnees.items():
        f = d["funding"]
        zone = "haut" if f >= FUNDING_HAUT else "bas" if f <= FUNDING_BAS else "normal"
        if not premier and zone != "normal" and zone != zones.get(sym, "normal"):
            alertes.append(msg_funding(sym, f))
        zones[sym] = zone
        h = [p for p in hist.get(sym, []) if maintenant - p[0] <= 3 * 3600]
        h.append([maintenant, d["oi"]])
        hist[sym] = h
        ancien = next((p for p in h if 3300 <= maintenant - p[0] <= 4500), None)
        if ancien and ancien[1] > 0 and not premier:
            var = (d["oi"] - ancien[1]) / ancien[1] * 100
            if abs(var) >= OI_SEUIL and peut(etat, f"{sym}:oi", maintenant):
                alertes.append(msg_oi(sym, var, d["oi"]))

def passage(token, mode_test=False):
    etat = charger_etat()
    for k in ("niveaux", "ath", "bande24", "derniere"):
        etat.setdefault(k, {})
    premier = not etat.get("init")
    maintenant = time.time()
    auj = datetime.now(TZ)
    alertes = []

    marche = get(f"{CG}/coins/markets?vs_currency=usd&ids={','.join(CRYPTOS)}&price_change_percentage=1h,24h")
    for c in marche:
        if c["id"] not in CRYPTOS:
            continue
        sym, pas = CRYPTOS[c["id"]]
        prix = c["current_price"]
        h1 = c.get("price_change_percentage_1h_in_currency") or 0
        h24 = c.get("price_change_percentage_24h_in_currency") or 0
        ligne = f"Prix : <b>{fmt_prix(prix)}</b> · 24 h : <b>{fmt_pct(h24)}</b>"
        tag = f"#{sym}"

        niveau = math.floor(prix / pas + 1e-9)
        ancien = etat["niveaux"].get(sym)
        etat["niveaux"][sym] = niveau
        ath_connu = max(etat["ath"].get(sym, 0), c.get("ath") or 0)
        bande = int(abs(h24) // SEUILS.get(sym, (SEUIL_1H, PAS_24H))[1]) * (1 if h24 >= 0 else -1)

        if premier:
            etat["ath"][sym] = ath_connu
            etat["bande24"][sym] = bande
            continue

        # 1. Mouvement brutal sur 1 h
        if abs(h1) >= SEUILS.get(sym, (SEUIL_1H, PAS_24H))[0] and peut(etat, f"{sym}:1h", maintenant):
            alertes.append(grosse(f"🚨 <b>ALERTE {sym}</b> 🚨",
                                  f"{'▲ Hausse' if h1 > 0 else '▼ Chute'} de <b>{fmt_abs(h1)}</b> en 1 h", ligne))

        # 2. Paliers de 5 % sur 24 h
        ancienne = etat["bande24"].get(sym, 0)
        if bande != 0 and (bande * ancienne <= 0 or abs(bande) > abs(ancienne)):
            alertes.append(petite(f"<u>{sym}</u> : {'▲ hausse' if h24 > 0 else '▼ baisse'} de {fmt_abs(h24)} sur 24 h · Prix : <b>{fmt_prix(prix)}</b>"))
        etat["bande24"][sym] = bande

        # 3. Niveau rond franchi
        if ancien is not None and niveau != ancien:
            if niveau > ancien:
                seuil, txt, emoji = niveau * pas, "▲ repasse au-dessus de", "🟢"
            else:
                seuil, txt, emoji = (niveau + 1) * pas, "▼ passe sous", "🔴"
            if peut(etat, f"{sym}:niveau:{round(seuil, 4)}", maintenant):
                alertes.append(petite(f"<u>{sym}</u> : {txt} {fmt_prix(seuil)} · Prix : <b>{fmt_prix(prix)}</b>"))

        # 4. Nouveau record historique
        if prix > ath_connu > 0:
            if peut(etat, f"{sym}:ath", maintenant):
                alertes.append(grosse(f"⚡ <b>NOUVEL ATH {sym}</b> ⚡", "Nouveau plus haut historique", f"Prix : <b>{fmt_prix(prix)}</b>"))
            ath_connu = prix
        etat["ath"][sym] = ath_connu

    # 5. Fear & Greed (vérifié toutes les 30 min)
    if premier or mode_test or maintenant - etat.get("fg_ts", 0) >= 1800:
        try:
            fg = get("https://api.alternative.me/fng/?limit=1")["data"][0]
            classe = fg["value_classification"]
            ancienne = etat.get("fg")
            if not premier and ancienne and classe != ancienne:
                if classe in ("Extreme Fear", "Extreme Greed"):
                    alertes.append(grosse("🚨 <b>ALERTE SENTIMENT</b> 🚨",
                                          f"Fear & Greed : {fg['value']} — <b>{FG_FR[classe]}</b>",
                                          "Le sentiment du marché crypto entre en zone extrême."))
                else:
                    alertes.append(petite(f"<u>Fear & Greed</u> : passe en <b>{FG_FR[classe]}</b> ({fg['value']}) · avant : {FG_FR.get(ancienne, ancienne)}"))
            etat.update({"fg": classe, "fg_val": fg["value"], "fg_ts": maintenant})
        except Exception as e:
            print("⚠️ Fear & Greed :", e)

    # 5 bis. Flux ETF
    verifier_etf(etat, alertes, premier, maintenant)

    # 5 ter. Baleines
    verifier_baleines(etat, alertes, premier, maintenant)

    # 5 quater. Funding & open interest
    verifier_derives(etat, alertes, premier, maintenant)

    # 6. Résumé du matin
    jour = auj.strftime("%Y-%m-%d")
    if premier and auj.hour >= HEURE_RESUME:
        etat["resume"] = jour
    if mode_test or (not premier and auj.hour >= HEURE_RESUME and etat.get("resume") != jour):
        alertes.append(resume(marche, etat, auj))
        if not mode_test:
            etat["resume"] = jour

    if premier:
        print("Initialisation : état du marché enregistré, aucune alerte envoyée.")
    etat["init"] = True
    if not alertes and not premier:
        print(time.strftime("%H:%M:%S"), "— rien à signaler")
    for texte in alertes:
        envoyer(token, texte)
    sauver_etat(etat)

if __name__ == "__main__":
    token = lire_token()
    if "--test" in sys.argv:
        passage(token, mode_test=True)
    elif "--cycle" in sys.argv:
        fin = time.time() + int(os.environ.get("CYCLE_SECONDS", "270"))
        while True:
            try:
                passage(token)
            except Exception as e:
                print("⚠️ Erreur :", e)
            if time.time() + 60 > fin:
                break
            time.sleep(60)
    elif "--boucle" in sys.argv:
        print("Bot Alerts lancé en continu (Ctrl+C pour arrêter).")
        while True:
            try:
                passage(token)
            except Exception as e:
                print("⚠️ Erreur, nouvel essai dans 60 s :", e)
            time.sleep(60)
    else:
        passage(token)
