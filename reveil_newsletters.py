"""Réveille les workflows de newsletters (dépôt privé TradixCapitals/newsletter-macro) aux heures de publication.

Pourquoi : GitHub retarde ou saute souvent les déclenchements planifiés des dépôts privés. Ce dépôt (public, minutes
illimitées) tourne toutes les ~5 minutes : il lit le calendrier économique gratuit et lance les newsletters dans la
fenêtre [10 min avant la publication ; 90 min après] (les chiffres viennent directement du BLS, à l'heure de sortie). Hors fenêtre : rien.
Les newsletters savent déjà ne rien faire si la publication est déjà traitée (état + anti-doublon Brevo).
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REPO = "TradixCapitals/newsletter-macro"
# titre exact dans le calendrier -> workflow à lancer
CIBLES = {
    "CPI m/m": "newsletter-cpi.yml",
    "Non-Farm Employment Change": "newsletter.yml",
    "FOMC Statement": "newsletter-fomc.yml",
    "Federal Funds Rate": "newsletter-fomc.yml",
}
AVANT = timedelta(minutes=10)
APRES = timedelta(minutes=90)


def a_lancer(feed, now):
    """Retourne la liste (sans doublon) des workflows à lancer maintenant."""
    out = []
    for e in feed:
        wf = CIBLES.get(e.get("title", ""))
        if e.get("country") != "USD" or not wf or wf in out:
            continue
        try:
            dt = datetime.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        if dt - AVANT <= now <= dt + APRES:
            out.append(wf)
    return out


def main():
    if not os.getenv("GH_TOKEN"):
        print("Pas de jeton NEWSLETTER_TOKEN : réveil des newsletters ignoré.")
        return
    try:
        req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0"})
        feed = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as exc:  # noqa: BLE001  (calendrier indisponible : le planning de secours des newsletters reste actif)
        print("Calendrier indisponible, rien à réveiller :", exc)
        return
    now = datetime.now(timezone.utc)
    cibles = a_lancer(feed, now)
    if not cibles:
        print("Aucune publication dans la fenêtre : rien à réveiller.")
        return
    for wf in cibles:
        if os.getenv("DRY"):
            print("[DRY] gh workflow run", wf)
            continue
        r = subprocess.run(["gh", "workflow", "run", wf, "-R", REPO, "--ref", "main"],
                           capture_output=True, text=True, timeout=60)
        print(f"Réveil {wf} :", "ok" if r.returncode == 0 else f"échec ({r.stderr.strip()[:200]})")


if __name__ == "__main__":
    main()
