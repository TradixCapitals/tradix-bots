#!/usr/bin/env python3
"""Visuel animé (GIF) pour les brouillons X des données chiffrées (style Tradix).

À partir du brouillon « 🇺🇸 MACRO | Sujet / Publié : … / Prévu : … · Précédent : … », dessine une carte animée :
grille qui défile, courbe qui se dessine, chiffre qui défile, verdict et biais Dollar / Or.
Uniquement Pillow (pas de navigateur), polices dans x/fonts (licence OFL).

Usage :
    python3 x_visuel.py --demo      fabrique demo.gif dans le dossier courant
"""
import io
import math
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "x", "fonts")
W, H = 1000, 563           # 16:9, affiché en entier par X
S = W / 1200               # échelle par rapport à la maquette 1200 px
FPS, DUREE = 15, 6
BG, GRILLE, ENCRE, GRIS = (236, 236, 236), (220, 220, 220), (17, 18, 20), (75, 79, 88)
VERT, ROUGE, NEUTRE, COURBE = (21, 128, 61), (180, 35, 24), (75, 79, 88), (196, 201, 210)
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]

# Indicateurs où un chiffre plus HAUT est une MAUVAISE nouvelle pour l'économie (vert = baisse)
INVERSES = ["chômage", "chomage", "inscriptions", "jobless", "unemployment", "licenciements", "faillites",
            "déficit", "deficit", "stocks de pétrole"]
# Inflation : plus haut = rouge, mais dollar en hausse (Fed plus dure)
INFLATION = ["inflation", "cpi", "pce", "ppi", "ipc", "prix", "hicp", "ipch", "salaire", "salaires"]


def police(nom, taille):
    return ImageFont.truetype(os.path.join(FONTS, nom), max(8, round(taille * S)))


def nombre(txt):
    m = re.search(r"[-+−]?\s*\d[\d\s.,]*", txt or "")
    if not m:
        return None
    t = m.group(0).replace("−", "-").replace(" ", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def analyser(texte, marche="US"):
    """Texte du tweet -> données de la carte, ou None si ce n'est pas une donnée chiffrée."""
    m_pub = re.search(r"Publié\s*:\s*([^\n▲▼=]+)", texte)
    m_prev = re.search(r"Prévu\s*:\s*([^·\n]+)", texte)
    if not (m_pub and m_prev):
        return None
    m_prec = re.search(r"Précédent\s*:\s*([^\n]+)", texte)
    entete = texte.split("\n", 1)[0]
    sujet = entete.split("|", 1)[1].strip() if "|" in entete else entete
    pub, prev = m_pub.group(1).strip(), m_prev.group(1).strip()
    prec = re.sub(r"\s*\(révisé[^)]*\)", "", m_prec.group(1)).strip() if m_prec else ""
    a, f = nombre(pub), nombre(prev)
    if a is None or f is None:
        return None
    bas = sujet.lower()
    m = (marche or "US").upper()
    banque = {"US": "la Fed", "EUR": "la BCE"}.get(m, "la banque centrale")
    devise = {"US": "Dollar", "EUR": "Euro"}.get(m)

    def biais_txt(devise_haut):
        if not devise:
            return ""
        if m == "US":
            return "Dollar ▲ · Or ▼" if devise_haut else "Dollar ▼ · Or ▲"
        return f"{devise} {'▲' if devise_haut else '▼'}"

    inverse = any(k in bas for k in INVERSES)
    inflation = any(k in bas for k in INFLATION)
    ecart = a - f
    rel = abs(ecart) / max(abs(f), 1e-9) if f else abs(ecart)
    if rel < 0.01 or abs(ecart) < 1e-9:
        return dict(sujet=sujet, pub=pub, prev=prev, prec=prec, valeur=a, fleche="=", coul=NEUTRE,
                    verdict="En ligne avec les attentes", biais=(f"{devise} =" + (" · Or =" if m == "US" else "")) if devise else "")
    nuance = "Légèrement " if rel < 0.05 else ("Nettement " if rel >= 0.15 else "")
    haut = ecart > 0
    if inflation:
        bon = not haut
        verdict = f"{nuance}{'plus forte' if haut else 'plus faible'} que prévu : " + \
                  (f"pression sur {banque}" if haut else f"bonne nouvelle pour {banque}")
        dollar_haut = haut
    elif inverse:
        bon = not haut
        verdict = f"{nuance}{'plus' if haut else 'moins'} que prévu : " + \
                  ("l'emploi se tend" if haut else "l'emploi reste solide")
        dollar_haut = not haut
    else:
        bon = haut
        verdict = f"{nuance}{'meilleur' if haut else 'moins bon'} que prévu"
        dollar_haut = haut
    verdict = verdict[0].upper() + verdict[1:]
    return dict(sujet=sujet, pub=pub, prev=prev, prec=prec, valeur=a, fleche="▲" if haut else "▼",
                coul=VERT if bon else ROUGE, verdict=verdict,
                biais=biais_txt(dollar_haut))


# ------------------------------------------------------------------ dessin
def logo(d, x, y, k):
    """Bougies + courbe Tradix (repère 116 x 96, échelle k)."""
    def P(px, py):
        return x + px * k, y + py * k
    lw = max(2, round(5 * k))
    for cx, top, bot, ry, rh, plein in ((20, 40, 90, 52, 26, True), (46, 46, 94, 58, 26, False),
                                        (72, 36, 88, 46, 28, True), (98, 22, 76, 32, 30, False)):
        d.line([P(cx, top), P(cx, bot)], fill=ENCRE, width=lw)
        d.rectangle([P(cx - 8, ry), P(cx + 8, ry + rh)], fill=ENCRE if plein else BG, outline=ENCRE, width=lw)
    d.line([P(4, 30), P(26, 20), P(50, 32), P(100, 6)], fill=ENCRE, width=lw, joint="curve")
    d.line([P(88, 4), P(102, 5), P(98, 18)], fill=ENCRE, width=lw, joint="curve")


def couche(taille):
    return Image.new("RGBA", taille, (0, 0, 0, 0))


def pastille(texte, f, pad_x, pad_y, rayon, fond, encre, contour=None):
    l, t, r, b = f.getbbox(texte)
    w, h = r - l + 2 * pad_x, b - t + 2 * pad_y
    im = couche((w + 2, h + 2))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w, h], rayon, fill=fond, outline=contour, width=1 if contour else 0)
    d.text((pad_x - l, pad_y - t), texte, font=f, fill=encre)
    return im


def texte_riche(morceaux, h):
    """[(texte, police, couleur), ...] sur une ligne -> image RGBA."""
    largeur = sum(round(f.getlength(t)) for t, f, _ in morceaux) + 4
    im = couche((largeur, h))
    d = ImageDraw.Draw(im)
    x = 0
    for t, f, c in morceaux:
        d.text((x, h * 0.78), t, font=f, fill=c, anchor="ls")
        x += f.getlength(t)
    return im


def fleche(sens, taille, couleur):
    im = couche((taille, taille))
    d = ImageDraw.Draw(im)
    if sens == "▼":
        d.polygon([(0, taille * 0.15), (taille, taille * 0.15), (taille / 2, taille * 0.95)], fill=couleur)
    elif sens == "▲":
        d.polygon([(0, taille * 0.85), (taille, taille * 0.85), (taille / 2, taille * 0.05)], fill=couleur)
    else:
        d.rectangle([taille * 0.1, taille * 0.35, taille * 0.9, taille * 0.45], fill=couleur)
        d.rectangle([taille * 0.1, taille * 0.6, taille * 0.9, taille * 0.7], fill=couleur)
    return im


def ease(t):
    t = min(1, max(0, t))
    return 1 - (1 - t) ** 3


def fabriquer(info, source="US", quand=None):
    """Renvoie le GIF animé (bytes)."""
    quand = quand or datetime.now(ZoneInfo("Europe/Paris"))
    f_brand = police("Poppins-Bold.ttf", 26)
    f_tag = police("Inter-Bold.otf", 19)
    f_titre = police("Inter-ExtraBold.otf", 46)
    f_date = police("Inter-Medium.otf", 24)
    f_big = police("Inter-ExtraBold.otf", 150 if len(info["pub"]) <= 6 else 118)
    f_pill = police("Inter-Medium.otf", 26)
    f_pillb = police("Inter-ExtraBold.otf", 26)
    f_ver = police("Inter-Bold.otf", 27)

    # Éléments fixes, dessinés une fois
    entete = couche((W, H))
    d = ImageDraw.Draw(entete)
    logo(d, 60 * S, 40 * S, 0.45 * S)
    d.text((60 * S + 64 * S, 66 * S), "T R A D I X", font=f_brand, fill=ENCRE, anchor="lm")
    tag = pastille(f"MACRO · {source.upper()}", f_tag, round(18 * S), round(11 * S), round(40 * S), ENCRE, (255, 255, 255))
    entete.alpha_composite(tag, (round(W - 60 * S - tag.width), round(46 * S)))

    titre = texte_riche([(info["sujet"], f_titre, ENCRE)], round(62 * S))
    if titre.width > W - 120 * S:  # sujet trop long : on réduit
        f_titre = police("Inter-ExtraBold.otf", 46 * (W - 120 * S) / titre.width)
        titre = texte_riche([(info["sujet"], f_titre, ENCRE)], round(62 * S))
    date = texte_riche([(f"{JOURS[quand.weekday()]} {quand.day} {MOIS[quand.month - 1]} · {quand:%H:%M}", f_date, GRIS)],
                       round(34 * S))
    pills = couche((W, round(70 * S)))
    x = 0
    for lab, val in (("Prévu ", info["prev"]), ("Précédent ", info["prec"])):
        if not val:
            continue
        t = texte_riche([(lab, f_pill, ENCRE), (val, f_pillb, ENCRE)], round(40 * S))
        p = couche((t.width + round(48 * S), round(62 * S)))
        ImageDraw.Draw(p).rounded_rectangle([0, 0, p.width - 1, p.height - 1], round(18 * S), fill=(255, 255, 255),
                                            outline=(220, 220, 220))
        p.alpha_composite(t, (round(24 * S), round(11 * S)))
        pills.alpha_composite(p, (x, 0))
        x += p.width + round(16 * S)
    verdict = texte_riche([(info["verdict"], f_ver, info["coul"])], round(40 * S))
    biais = texte_riche([(info["biais"], f_ver, ENCRE)], round(40 * S))
    arr = fleche(info["fleche"], round(62 * S), info["coul"])

    # Courbe de fond (sur-échantillonnée pour un trait lisse)
    pts = [(560, 520), (620, 500), (660, 515), (720, 470), (770, 480), (820, 430), (870, 445), (920, 390),
           (970, 405), (1020, 350), (1070, 365), (1140, 300)]
    pts = [(px * S, py * S) for px, py in pts]
    longs = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(longs)

    def courbe(prog):
        k = 2
        im = couche((W * k, H * k))
        dd = ImageDraw.Draw(im)
        reste, chemin = total * prog, [pts[0]]
        for i, L in enumerate(longs):
            if reste <= 0:
                break
            a, b = pts[i], pts[i + 1]
            u = min(1, reste / L)
            chemin.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
            reste -= L
        if len(chemin) > 1:
            dd.line([(px * k, py * k) for px, py in chemin], fill=COURBE, width=round(4 * S * k), joint="curve")
        return im.resize((W, H), Image.LANCZOS)

    def apparition(im, xy, base, t, debut):
        p = ease((t - debut) / 0.6)
        if p <= 0:
            return
        im2 = im.copy()
        if p < 1:
            alpha = im2.getchannel("A").point(lambda v: int(v * p))
            im2.putalpha(alpha)
        base.alpha_composite(im2, (round(xy[0]), round(xy[1] + 18 * S * (1 - p))))

    elements = [(titre, (60 * S, 128 * S), 0.1), (date, (60 * S, 190 * S), 0.25), (pills, (60 * S, 420 * S), 0.7),
                (verdict, (60 * S, H - 96 * S - verdict.height + 10 * S), 1.0),
                (biais, (W - 60 * S - biais.width, H - 96 * S - biais.height + 10 * S), 1.0)]
    courbes = {}
    images = []
    n = FPS * DUREE
    for i in range(n):
        t = i / FPS
        im = Image.new("RGBA", (W, H), BG + (255,))
        dd = ImageDraw.Draw(im)
        dec = (t / DUREE) * 60 * S  # la grille défile
        pas = 60 * S
        xg = -pas + dec % pas
        while xg < W:
            dd.line([(xg, 0), (xg, H)], fill=GRILLE, width=1)
            xg += pas
        yg = -pas + dec % pas
        while yg < H:
            dd.line([(0, yg), (W, yg)], fill=GRILLE, width=1)
            yg += pas
        prog = round(ease(min(1, t / (DUREE * 0.6))) * 40) / 40
        if prog not in courbes:
            courbes[prog] = courbe(prog)
        im.alpha_composite(courbes[prog])
        r = (7 + 6 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 1.2))) * S
        c = info["coul"]
        dd = ImageDraw.Draw(im)
        if prog >= 1:
            cx, cy = pts[-1]
            dd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c + (int(255 * (1 - (r / S - 7) / 12)),))
        im.alpha_composite(entete)
        for el, xy, debut in elements:
            apparition(el, xy, im, t, debut)
        # chiffre principal qui défile
        p = ease((t - 0.4) / 0.6)
        if p > 0:
            if t < 1.5:
                v = info["valeur"] * min(1, max(0, (t - 0.4) / 1.1)) ** 0.5
                dec_txt = 0 if float(info["valeur"]).is_integer() else 1
                txt = re.sub(r"[-+]?\d[\d\s.,]*", (f"{v:.{dec_txt}f}").replace(".", ","), info["pub"], count=1)
            else:
                txt = info["pub"]
            big = texte_riche([(txt, f_big, ENCRE)], round(170 * S))
            alpha = big.getchannel("A").point(lambda q: int(q * p))
            big.putalpha(alpha)
            yb = round(250 * S + 18 * S * (1 - p))
            im.alpha_composite(big, (round(60 * S), yb))
            bob = math.sin(t * 2 * math.pi / 1.6) * 8 * S * (1 if info["fleche"] == "▼" else -1)
            a2 = arr.copy()
            a2.putalpha(a2.getchannel("A").point(lambda q: int(q * p)))
            im.alpha_composite(a2, (round(60 * S + big.width + 18 * S), round(yb + 75 * S + bob)))
        images.append(im.convert("RGB"))

    # La 1re image du GIF doit être complète (X l'utilise comme aperçu)
    debut = int(FPS * 2.5)
    images = images[debut:] + images[:debut]
    palette = images[0].quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    out = io.BytesIO()
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:], duration=round(1000 / FPS),
                   loop=0, optimize=False, disposal=1)
    return out.getvalue()


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        txt = ("🇺🇸 MACRO | Inscriptions au chômage\n\nPublié : 197K ▼\nPrévu : 200K · Précédent : 199K\n\n#Emploi")
        data = fabriquer(analyser(txt))
        open("demo.gif", "wb").write(data)
        print(f"demo.gif : {len(data) / 1e6:.1f} Mo")
    else:
        print(__doc__)
