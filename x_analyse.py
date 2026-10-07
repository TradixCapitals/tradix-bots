#!/usr/bin/env python3
"""Tweet d'analyse en brouillon X à la sortie des newsletters NFP, CPI et FOMC.

Les newsletters (dépôt newsletter-macro) appellent publier(données) avec leurs chiffres, leur verdict et leur
biais Dollar / Or. Le brouillon arrive dans le canal privé « Tradix - Brouillons X », comme les autres.

Format :
    📊 ANALYSE | Emploi US · septembre

    NFP : +254K (prévu +150K)
    Taux de chômage : 4,1 % (prévu 4,2 %)

    👉 L'emploi américain surprend clairement à la hausse
    Biais : Dollar ▲ · Or ▼

    #NFP #Or
    (phrase vers les canaux Telegram)

Usage :
    python3 x_analyse.py --demo     faux NFP, faux CPI et fausse Fed en brouillons, sans notification
"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x_drafts  # noqa: E402

PHRASES = [
    "📲 Tous les chiffres en direct et en français sur Telegram : lien en bio",
    "🔔 Ne ratez plus une publication : nos canaux Telegram sont en bio",
    "⚡ Les chiffres tombent d'abord sur Telegram : lien en bio",
    "➡️ Le live des annonces macro, gratuit sur Telegram : lien en bio",
]
FLECHES = {"haussier": "▲", "baissier": "▼", "neutre": "="}
NOMS_COURTS = {
    "Taux directeur (fourchette cible)": "Taux Fed",
    "Inflation PCE (sur un an)": "PCE (1 an)",
    "Taux de chômage": "Chômage",
    "CPI core mensuel": "CPI core (m/m)",
    "CPI mensuel": "CPI (m/m)",
    "CPI annuel": "CPI (1 an)",
}


def propre(x):
    """'4,1%' -> '4,1 %' ; enlève les espaces en trop."""
    return re.sub(r"(\d)%", r"\1 %", str(x)).strip() if x is not None else x


def composer(donnees, phrase=""):
    """donnees : sujet, lignes [(nom, valeur, prévu ou None)], verdict, biais {'Dollar': 'haussier', 'Or': ...}."""
    titre = f"📊 ANALYSE | {donnees['sujet']}"
    lignes = []
    for nom, val, prevu in donnees["lignes"]:
        nom = NOMS_COURTS.get(nom, nom)
        lignes.append(f"{nom} : {propre(val)}" + (f" (prévu {propre(prevu)})" if prevu else ""))
    biais = " · ".join(f"{n} {FLECHES.get(b, b)}" for n, b in donnees.get("biais", {}).items())
    fin = [f"👉 {donnees['verdict']}"] + ([f"Biais : {biais}"] if biais else [])

    def assembler(ls, avec_prevu=True, avec_phrase=True):
        ls = ls if avec_prevu else [re.sub(r" \(prévu [^)]*\)$", "", l) for l in ls]
        texte = titre + "\n\n" + "\n".join(ls) + "\n\n" + "\n".join(fin)
        return texte + x_drafts.pied_de(texte, phrase if avec_phrase else "")

    # Trop long : on retire d'abord la dernière ligne de chiffres, puis les prévisions, jamais la phrase d'appel
    essai = list(lignes)
    while len(essai) > 2 and x_drafts.poids(assembler(essai)) > x_drafts.LIMITE:
        essai.pop()
    if x_drafts.poids(assembler(essai)) <= x_drafts.LIMITE:
        return assembler(essai)
    if x_drafts.poids(assembler(essai, False)) <= x_drafts.LIMITE:
        return assembler(essai, False)
    return assembler(essai, False, False)


def phrase_du_jour(d=None):
    d = d or date.today()
    return PHRASES[d.toordinal() % len(PHRASES)]


def publier(donnees, source="Newsletter", silencieux=False):
    """Envoie le brouillon. Ne bloque jamais la newsletter si ça échoue."""
    try:
        if not (x_drafts.TOKEN and x_drafts.CHAT_ID):
            print("Brouillon X d'analyse : token ou canal manquant, rien envoyé.")
            return False
        ok = x_drafts.envoyer_brouillon(composer(donnees, phrase_du_jour()), source, silencieux)
        print("Brouillon X d'analyse envoyé." if ok else "Brouillon X d'analyse refusé.")
        return ok
    except Exception as e:  # noqa: BLE001
        print("Brouillon X d'analyse impossible :", e)
        return False


DEMO = [
    ("NFP · DÉMO", {
        "sujet": "Emploi US · septembre",
        "lignes": [("NFP", "+254K", "+150K"), ("Taux de chômage", "4,1%", "4,2%"), ("Salaire horaire", "+0,4%", "+0,3%")],
        "verdict": "L'emploi américain surprend clairement à la hausse",
        "biais": {"Dollar": "haussier", "Or": "baissier"},
    }),
    ("CPI · DÉMO", {
        "sujet": "Inflation US · septembre",
        "lignes": [("CPI core mensuel", "+0,2%", "+0,3%"), ("CPI annuel", "2,8%", "2,9%"), ("CPI mensuel", "+0,2%", "+0,3%")],
        "verdict": "L'inflation américaine surprend plutôt à la baisse",
        "biais": {"Dollar": "baissier", "Or": "haussier"},
    }),
    ("FOMC · DÉMO", {
        "sujet": "Fed · 28 octobre",
        "lignes": [("Taux directeur (fourchette cible)", "3,75% - 4,00%", None),
                   ("Inflation PCE (sur un an)", "2,7%", None), ("Taux de chômage", "4,3%", None)],
        "verdict": "La Fed baisse ses taux de 25 points de base, comme attendu",
        "biais": {"Dollar": "baissier", "Or": "haussier"},
    }),
]


if __name__ == "__main__":
    if "--demo" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    x_drafts.CHAT_ID = x_drafts.CHAT_ID or "-1003875078448"
    x_drafts.TOKEN = x_drafts.TOKEN or x_drafts.token_local()
    n = sum(publier(d, src, silencieux=True) for src, d in DEMO)
    print(f"{n}/{len(DEMO)} analyses de démo envoyées en brouillons.")
