#!/usr/bin/env python3
"""Agenda économique en brouillon X : annonces du jour (chaque matin) et de la semaine (dimanche soir).

Source gratuite : calendrier hebdomadaire ForexFactory (JSON public).
Les brouillons arrivent dans le canal privé « Tradix - Brouillons X », comme les autres (voir x_drafts.py).

Usage :
    python3 x_agenda.py --jour      agenda des annonces US importantes du jour
    python3 x_agenda.py --semaine   grands rendez-vous de la semaine
    python3 x_agenda.py --test      les deux, sans notification (pour vérifier le rendu)
    python3 x_agenda.py --demo      faux agenda (semaine fictive), sans notification
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_drafts  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
FLUX = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
DRAPEAUX = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CNY": "🇨🇳", "CHF": "🇨🇭",
            "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿"}

# Titres ForexFactory -> français (le début du titre suffit). L'ordre compte : le plus précis d'abord.
TRADUCTIONS = [
    ("Non-Farm Employment Change", "Emplois non agricoles (NFP)"),
    ("ADP Non-Farm Employment Change", "Emplois privés ADP"),
    ("Unemployment Rate", "Taux de chômage"),
    ("Unemployment Claims", "Inscriptions au chômage"),
    ("Average Hourly Earnings", "Salaire horaire moyen"),
    ("JOLTS Job Openings", "Offres d'emploi JOLTS"),
    ("Core CPI", "Inflation CPI core"),
    ("CPI", "Inflation CPI"),
    ("Core PPI", "Prix à la production core (PPI)"),
    ("PPI", "Prix à la production (PPI)"),
    ("Core PCE Price Index", "Inflation PCE core"),
    ("PCE Price Index", "Inflation PCE"),
    ("Advance GDP", "PIB (1re estimation)"),
    ("Prelim GDP", "PIB (2e estimation)"),
    ("Final GDP", "PIB (estimation finale)"),
    ("GDP", "PIB"),
    ("Federal Funds Rate", "Décision de taux de la Fed"),
    ("FOMC Statement", "Communiqué du FOMC"),
    ("FOMC Press Conference", "Conférence de presse de la Fed"),
    ("FOMC Meeting Minutes", "Minutes du FOMC"),
    ("FOMC Economic Projections", "Projections économiques de la Fed"),
    ("Fed Chair Powell Speaks", "Discours de Powell"),
    ("Core Retail Sales", "Ventes au détail core"),
    ("Retail Sales", "Ventes au détail"),
    ("ISM Manufacturing PMI", "ISM manufacturier"),
    ("ISM Services PMI", "ISM des services"),
    ("Flash Manufacturing PMI", "PMI manufacturier (flash)"),
    ("Flash Services PMI", "PMI des services (flash)"),
    ("Prelim UoM Consumer Sentiment", "Confiance des consommateurs (Michigan)"),
    ("Revised UoM Consumer Sentiment", "Confiance des consommateurs (Michigan, finale)"),
    ("Prelim UoM Inflation Expectations", "Anticipations d'inflation (Michigan)"),
    ("CB Consumer Confidence", "Confiance des consommateurs (Conference Board)"),
    ("Core Durable Goods Orders", "Commandes de biens durables core"),
    ("Durable Goods Orders", "Commandes de biens durables"),
    ("Empire State Manufacturing Index", "Indice manufacturier Empire State"),
    ("Philly Fed Manufacturing Index", "Indice manufacturier Philly Fed"),
    ("Building Permits", "Permis de construire"),
    ("Housing Starts", "Mises en chantier"),
    ("Existing Home Sales", "Ventes de logements anciens"),
    ("New Home Sales", "Ventes de logements neufs"),
    ("Pending Home Sales", "Promesses de ventes de logements"),
    ("Trade Balance", "Balance commerciale"),
    ("Crude Oil Inventories", "Stocks de pétrole (EIA)"),
    ("Industrial Production", "Production industrielle"),
    ("Main Refinancing Rate", "Décision de taux de la BCE"),
    ("Monetary Policy Statement", "Communiqué de politique monétaire"),
    ("ECB Press Conference", "Conférence de presse de la BCE"),
    ("Official Bank Rate", "Décision de taux de la BoE"),
    ("BOJ Policy Rate", "Décision de taux de la BoJ"),
    ("Treasury Currency Report", "Rapport du Trésor sur les devises"),
    ("President Trump Speaks", "Discours de Trump"),
    ("Bank Holiday", "Jour férié"),
]


# Agenda de la semaine : nom court et priorité (plus petit = plus important), repérés par mot-clé du titre
COURTS = [
    ("Federal Funds Rate", "Décision Fed", 1), ("FOMC Press Conference", "Décision Fed", 1),
    ("FOMC Statement", "Décision Fed", 1), ("Non-Farm Employment Change", "NFP", 1),
    ("CPI", "CPI", 1), ("Fed Chair Powell", "Powell", 2), ("PCE Price Index", "PCE", 2),
    ("FOMC Meeting Minutes", "Minutes FOMC", 2), ("GDP", "PIB", 2), ("Retail Sales", "Ventes au détail", 3),
    ("PPI", "PPI", 3), ("ISM Services", "ISM services", 3), ("ISM Manufacturing", "ISM manuf.", 3),
    ("Main Refinancing Rate", "BCE", 1), ("Official Bank Rate", "BoE", 2), ("BOJ Policy Rate", "BoJ", 2),
    ("JOLTS", "JOLTS", 4), ("ADP", "ADP", 4), ("UoM", "Michigan", 4), ("CB Consumer Confidence", "Confiance", 4),
    ("Unemployment Claims", "Chômage hebdo", 5), ("Unemployment Rate", "NFP", 1), ("Average Hourly", "NFP", 1),
]


def court(titre):
    for cle, nom, prio in COURTS:
        if cle in titre:
            return nom, prio
    return traduire(titre), 4


def chiffre(x):
    return x.replace(".", ",").replace("%", " %") if x else x


def traduire(titre):
    for en, fr in TRADUCTIONS:
        if titre.startswith(en):
            reste = titre[len(en):].strip()
            reste = {"m/m": "(mensuel)", "y/y": "(annuel)", "q/q": "(trimestriel)"}.get(reste, reste)
            return f"{fr} {reste}".strip()
    if titre.startswith("FOMC Member") or titre.endswith("Speaks"):
        nom = titre.replace("FOMC Member", "").replace("Speaks", "").strip()
        return f"Discours de {nom} (Fed)" if titre.startswith("FOMC") else f"Discours de {nom}"
    return titre


def lire_calendrier():
    req = urllib.request.Request(FLUX, headers={"User-Agent": "Mozilla/5.0 (TradixAgenda/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        evts = json.load(r)
    for e in evts:
        e["quand"] = datetime.fromisoformat(e["date"]).astimezone(PARIS)
    return evts


def date_fr(d):
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


PHRASES_AGENDA = [
    "🔔 Toutes ces annonces en direct et en français sur Telegram : lien en bio",
    "📲 Suivez chaque publication en temps réel sur nos canaux Telegram (lien en bio)",
    "⚡ Les chiffres tombent d'abord sur Telegram : lien en bio",
    "➡️ Le live de ces annonces, gratuit sur Telegram : lien en bio",
]


def phrase_du_jour(d):
    """Phrase d'appel vers les canaux, toujours présente sur l'agenda, différente d'un jour à l'autre."""
    return PHRASES_AGENDA[d.toordinal() % len(PHRASES_AGENDA)]


def agenda_jour(evts, jour):
    """Annonces US à fort impact du jour (+ impact moyen s'il y a de la place)."""
    du_jour = [e for e in evts if e["quand"].date() == jour and e.get("country") == "USD"
               and e.get("impact") in ("High", "Medium") and "Holiday" not in e.get("title", "")]
    du_jour.sort(key=lambda e: (e["quand"], e.get("impact") != "High"))
    if not any(e["impact"] == "High" for e in du_jour):
        return None
    lignes = []
    for e in du_jour:
        heure = e["quand"].strftime("%H:%M")
        marque = "🔴" if e["impact"] == "High" else "🟠"
        ligne = f"{marque} {heure} · {traduire(e['title'])}"
        if e.get("forecast"):
            ligne += f" · prévu {chiffre(e['forecast'])}"
        lignes.append(ligne)
    titre = f"🗓 AGENDA | {date_fr(jour)}"
    return titre, lignes


def agenda_semaine(evts, depuis=None):
    """Rendez-vous à fort impact de la semaine, regroupés par jour : US + décisions des grandes banques centrales."""
    depuis = depuis or datetime.now(PARIS).date()
    gardes = []
    for e in evts:
        t = e.get("title", "")
        banque = any(k in t for k in ("Main Refinancing Rate", "Official Bank Rate", "BOJ Policy Rate"))
        if e.get("impact") == "High" and (e.get("country") == "USD" or banque) and "Holiday" not in t \
                and e["quand"].date() >= depuis:
            gardes.append(e)
    if not gardes:
        return None
    gardes.sort(key=lambda e: e["quand"])
    jours = {}  # date -> liste ordonnée de (priorité, texte)
    for e in gardes:
        nom, prio = court(e["title"])
        drapeau = "" if e.get("country") == "USD" else DRAPEAUX.get(e.get("country"), "") + " "
        texte = f"{drapeau}{nom}"
        liste = jours.setdefault(e["quand"].date(), [])
        if all(t != texte for _, t in liste):
            liste.append((prio, texte))
    lundi = min(jours) - timedelta(days=min(jours).weekday())
    return f"🗓 AGENDA | Semaine du {lundi.day} {MOIS[lundi.month - 1]}", jours


def lignes_semaine(jours, prio_max):
    lignes = []
    for d in sorted(jours):
        items = [t for p, t in jours[d] if p <= prio_max]
        if items:
            lignes.append(f"{JOURS[d.weekday()][:3]}. {d.day} · " + " · ".join(items))
    return lignes


def envoyer(bloc, source, silencieux, phrase):
    if not bloc:
        print("Rien d'important à annoncer : pas de brouillon.")
        return True
    titre, contenu = bloc

    def composer(lignes):
        texte = titre + "\n\n" + "\n".join(lignes)
        return texte + x_drafts.pied_de(texte, phrase)

    if isinstance(contenu, dict):  # semaine : on retire d'abord les rendez-vous les moins importants
        prio = 5
        while prio > 1 and x_drafts.poids(composer(lignes_semaine(contenu, prio))) > x_drafts.LIMITE:
            prio -= 1
        lignes = lignes_semaine(contenu, prio)
    else:
        lignes = list(contenu)
        while len(lignes) > 1 and x_drafts.poids(composer(lignes)) > x_drafts.LIMITE:
            orange = [i for i, l in enumerate(lignes) if l.startswith("🟠")]
            lignes.pop(orange[-1] if orange else -1)
    return x_drafts.envoyer_brouillon(composer(lignes), source, silencieux)


# Faux calendrier pour --demo (semaine fictive du lundi 12 octobre 2026)
DEMO = [
    ("ISM Services PMI", "USD", "2026-10-12T10:00:00-04:00", "High", "51.2"),
    ("Retail Sales m/m", "USD", "2026-10-13T08:30:00-04:00", "High", "0.4%"),
    ("JOLTS Job Openings", "USD", "2026-10-13T10:00:00-04:00", "High", "7.2M"),
    ("Fed Chair Powell Speaks", "USD", "2026-10-13T13:00:00-04:00", "High", ""),
    ("Unemployment Claims", "USD", "2026-10-15T08:30:00-04:00", "High", "225K"),
    ("Core CPI m/m", "USD", "2026-10-15T08:30:00-04:00", "High", "0.3%"),
    ("CPI y/y", "USD", "2026-10-15T08:30:00-04:00", "High", "2.9%"),
    ("FOMC Member Waller Speaks", "USD", "2026-10-15T11:00:00-04:00", "Medium", ""),
    ("Main Refinancing Rate", "EUR", "2026-10-15T08:15:00-04:00", "High", "2.15%"),
    ("FOMC Meeting Minutes", "USD", "2026-10-14T14:00:00-04:00", "High", ""),
    ("Non-Farm Employment Change", "USD", "2026-10-16T08:30:00-04:00", "High", "150K"),
    ("Unemployment Rate", "USD", "2026-10-16T08:30:00-04:00", "High", "4.3%"),
    ("Prelim UoM Consumer Sentiment", "USD", "2026-10-16T10:00:00-04:00", "High", "55.1"),
]


def demo():
    x_drafts.CHAT_ID = x_drafts.CHAT_ID or "-1003875078448"
    x_drafts.TOKEN = x_drafts.TOKEN or x_drafts.token_local()
    evts = [{"title": t, "country": c, "date": d, "impact": i, "forecast": f} for t, c, d, i, f in DEMO]
    for e in evts:
        e["quand"] = datetime.fromisoformat(e["date"]).astimezone(PARIS)
    jour = datetime(2026, 10, 15).date()
    ok = envoyer(agenda_jour(evts, jour), "Agenda du jour · DÉMO", True, phrase_du_jour(jour))
    ok &= envoyer(agenda_semaine(evts, jour - timedelta(days=3)), "Agenda de la semaine · DÉMO", True,
                  phrase_du_jour(jour + timedelta(days=1)))
    print("Faux agenda envoyé en brouillon." if ok else "Échec de l'envoi (voir ci-dessus).")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--demo":
        return demo()
    if arg not in ("--jour", "--semaine", "--test"):
        print(__doc__)
        return
    if arg == "--test":
        x_drafts.CHAT_ID = x_drafts.CHAT_ID or "-1003875078448"
        x_drafts.TOKEN = x_drafts.TOKEN or x_drafts.token_local()
    if not (x_drafts.TOKEN and x_drafts.CHAT_ID):
        sys.exit("Il manque le token ou le canal des brouillons.")
    evts = lire_calendrier()
    aujourd_hui = datetime.now(PARIS).date()
    ok = True
    if arg in ("--jour", "--test"):
        bloc = agenda_jour(evts, aujourd_hui)
        if arg == "--test" and not bloc:  # test : on prend le prochain jour qui a des annonces importantes
            for k in range(1, 7):
                bloc = agenda_jour(evts, aujourd_hui + timedelta(days=k))
                if bloc:
                    break
        ok &= envoyer(bloc, "Agenda du jour" + (" · TEST" if arg == "--test" else ""), arg == "--test",
                      phrase_du_jour(aujourd_hui))
    if arg in ("--semaine", "--test"):
        ok &= envoyer(agenda_semaine(evts, None if arg != "--test" else aujourd_hui - timedelta(days=7)), "Agenda de la semaine" + (" · TEST" if arg == "--test" else ""),
                      arg == "--test", phrase_du_jour(aujourd_hui + timedelta(days=1)))
    print("Agenda envoyé en brouillon." if ok else "Échec de l'envoi (voir ci-dessus).")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
