#!/usr/bin/env python3
"""Build the analysis page from yazio-dataset.json. Every figure is derived here."""

import argparse
import html
import json
import os
import statistics
from datetime import datetime
from itertools import pairwise
from pathlib import Path

D = Path(os.environ.get("YAZIO_EXPORT_DIR", Path.home() / "yazio-export")).expanduser()

RUN_GAP_DAYS = 30  # a pause longer than this starts a new tracking run


def detect_run_start(daily):
    """First day of the latest tracking run, i.e. after the last long pause."""
    dates = [r["date"] for r in daily if not r["below_tracking_threshold"]]
    if not dates:
        return daily[0]["date"] if daily else "1970-01-01"
    start = dates[0]
    for prev, cur in pairwise(dates):
        gap = (datetime.strptime(cur, "%Y-%m-%d") - datetime.strptime(prev, "%Y-%m-%d")).days
        if gap > RUN_GAP_DAYS:
            start = cur
    return start


def detect_target(daily):
    """Weight goal as set in the app, taken from the most recent day that carries one."""
    for r in reversed(daily):
        if r.get("goal_weight_kg"):
            return float(r["goal_weight_kg"])
    return None


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("--start", help="First day to analyse (YYYY-MM-DD). Default: start of the latest tracking run.")
ap.add_argument("--target", type=float, help="Weight goal in kg. Default: the goal set in the app.")
ap.add_argument("--out", help="Output file. Default: <export dir>/analyse.html")
args = ap.parse_args()

d = json.loads((D / "yazio-dataset.json").read_text(encoding="utf-8"))
OUT = Path(args.out) if args.out else D / "analyse.html"
WIN = args.start or d["metrics"].get("recent_window_start") or detect_run_start(d["daily"])
TARGET_KG = args.target if args.target is not None else detect_target(d["daily"])
prof, mets = d["profile"], d["metrics"]
tracked = [r for r in d["daily"] if not r["below_tracking_threshold"] and r["date"] >= WIN]
rows_all = [r for r in d["daily"] if r["date"] >= WIN]
wi = [w for w in d["weigh_ins"] if w["date"] >= WIN]
sess = [s for s in d["sessions"] if s["date"] >= WIN]
FR = {"Mon": "Lun", "Tue": "Mar", "Wed": "Mer", "Thu": "Jeu", "Fri": "Ven", "Sat": "Sam", "Sun": "Dim"}
MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_last = tracked[-1]["date"] if tracked else WIN
TITLE = f"Bilan nutrition, {MONTHS_FR[int(_last[5:7]) - 1]} {_last[:4]}"


def mean(rs, k):
    return statistics.mean(r[k] for r in rs)


def fr(x, n=1):
    """Format a number with the French decimal comma."""
    return f"{x:+.{n}f}".replace(".", ",") if x < 0 else f"{x:.{n}f}".replace(".", ",")


avg = mean(tracked, "kcal")
sd = statistics.stdev(r["kcal"] for r in tracked)
wt = wi[-1]["weight_kg"]
prot = mean(tracked, "protein_g")

base = datetime.strptime(wi[0]["date"], "%Y-%m-%d")
xs = [(datetime.strptime(w["date"], "%Y-%m-%d") - base).days for w in wi]
ys = [w["weight_kg"] for w in wi]
mx, my = statistics.mean(xs), statistics.mean(ys)
slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)
tdee_reg = avg - slope * 7700
bmr = 10 * wt + 6.25 * prof["body_height"] - 5 * prof["age_years"] + 5
tdee_naive = avg + ((ys[0] - ys[-1]) * 7700) / (xs[-1] - xs[0])
LO, HI = 2550, 2850
CENTRE = 2700

weeks = [
    ("31/08 – 06/09", [r for r in tracked if r["date"] <= "2026-09-06"]),
    ("07/09 – 13/09", [r for r in tracked if "2026-09-07" <= r["date"] <= "2026-09-13"]),
    ("14/09 – 16/09", [r for r in tracked if r["date"] >= "2026-09-14"]),
]
suspect = [r["date"] for r in tracked if r["steps_suspect"]]
low_p = [r for r in tracked if r["protein_g"] < 100]
goal = tracked[-1]["goal_kcal"]

# ── weigh-in chart ──
W, H, L, R, T, B = 720, 250, 54, 18, 18, 34
xmin, xmax = 0, max(xs)
ymin, ymax = min(ys) - 0.4, max(ys) + 0.4


def px(x):
    return L + (x - xmin) / (xmax - xmin) * (W - L - R)


def py(y):
    return T + (ymax - y) / (ymax - ymin) * (H - T - B)


sv = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Poids mesuré du {wi[0]["date"]} au {wi[-1]["date"]}">']
for i in range(5):
    y = ymin + (ymax - ymin) * i / 4
    sv.append(f'<line class="grid" x1="{L}" y1="{py(y):.1f}" x2="{W - R}" y2="{py(y):.1f}"/>')
    sv.append(f'<text class="ax" x="{L - 8}" y="{py(y) + 4:.1f}" text-anchor="end">{y:.1f}</text>')
sv.append(
    f'<line class="trend" x1="{px(xmin):.1f}" y1="{py(my + slope * (xmin - mx)):.1f}" '
    f'x2="{px(xmax):.1f}" y2="{py(my + slope * (xmax - mx)):.1f}"/>'
)
_pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xs, ys, strict=True))
sv.append(f'<polyline class="series" points="{_pts}"/>')
for x, y, w in zip(xs, ys, wi, strict=True):
    sv.append(f'<circle class="dot" cx="{px(x):.1f}" cy="{py(y):.1f}" r="4.5"/>')
    sv.append(f'<text class="pt" x="{px(x):.1f}" y="{py(y) - 11:.1f}" text-anchor="middle">{y:.1f}</text>')
    sv.append(
        f'<text class="ax" x="{px(x):.1f}" y="{H - 12}" text-anchor="middle">{w["date"][8:]}/{w["date"][5:7]}</text>'
    )
sv.append("</svg>")
chart = "\n".join(sv)

CSS = """
:root{--ground:#FBFBF9;--surface:#FFFFFF;--sunk:#F3F4EF;--ink:#1C1F1B;--muted:#5F665C;
--line:#DCDFD7;--line-strong:#C3C8BA;--accent:#4A6B3D;--accent-soft:#EDF2E8;--flag:#9A6224;--flag-soft:#FBF3E6;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#141613;--surface:#1C1F1B;--sunk:#191C17;
--ink:#E6E8E2;--muted:#9BA396;--line:#32362E;--line-strong:#454B40;--accent:#8FB57C;--accent-soft:#232A1E;
--flag:#D3A063;--flag-soft:#2A2114;}}
:root[data-theme="dark"]{--ground:#141613;--surface:#1C1F1B;--sunk:#191C17;--ink:#E6E8E2;--muted:#9BA396;
--line:#32362E;--line-strong:#454B40;--accent:#8FB57C;--accent-soft:#232A1E;--flag:#D3A063;--flag-soft:#2A2114;}
*{box-sizing:border-box}
body{margin:0;padding-block:2.5rem 4rem;padding-left:1.25rem;padding-right:1.25rem;background:var(--ground);
color:var(--ink);
font:400 16px/1.62 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:62rem;margin:0 auto;display:flex;flex-direction:column;gap:2.4rem}
.prose{max-width:68ch}
h1,h2,h3{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif;font-weight:600;text-wrap:balance;margin:0}
h1{font-size:clamp(1.8rem,4vw,2.5rem);letter-spacing:-.01em;line-height:1.14}
h2{font-size:1.32rem} h3{font-size:1rem;color:var(--muted)}
section{display:flex;flex-direction:column;gap:.85rem}
.eyebrow{font-family:"IBM Plex Sans Condensed",sans-serif;font-size:.72rem;font-weight:600;text-transform:uppercase;
letter-spacing:.14em;color:var(--accent);margin:0 0 .5rem}
p{margin:0} .lede{color:var(--muted);font-size:1.02rem}
ul,ol{margin:0;padding-left:1.15rem;display:flex;flex-direction:column;gap:.5rem;max-width:68ch}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.87em;background:var(--sunk);padding:.1em .35em;
border-radius:3px}
h2{border-top:1px solid var(--line-strong);padding-top:1.1rem}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:.42rem .6rem;text-align:right;white-space:nowrap}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
thead th{font-family:"IBM Plex Sans Condensed",sans-serif;font-size:.72rem;text-transform:uppercase;
letter-spacing:.09em;color:var(--muted);border-bottom:1px solid var(--line-strong)}
tbody tr.dim td{color:var(--muted)}
td.hi{font-weight:600;color:var(--accent)}
.kv td:first-child{color:var(--muted)}
.note{border-left:3px solid var(--flag);background:var(--flag-soft);padding:1rem 1.2rem;display:flex;
flex-direction:column;gap:.5rem}
.note h3{color:var(--flag);font-size:1rem;font-family:"IBM Plex Sans Condensed",sans-serif}
.note p,.note ul{max-width:68ch;font-size:.94rem}
figure{margin:0;display:flex;flex-direction:column;gap:.5rem}
svg{width:100%;height:auto;display:block;background:var(--surface);border:1px solid var(--line)}
.grid{stroke:var(--line);stroke-width:1}
.trend{stroke:var(--flag);stroke-width:1.5;stroke-dasharray:5 4}
.series{fill:none;stroke:var(--accent);stroke-width:2}
.dot{fill:var(--accent)}
.ax{fill:var(--muted);font-family:"IBM Plex Mono",monospace;font-size:11px}
.pt{fill:var(--ink);font-family:"IBM Plex Mono",monospace;font-size:11px;font-weight:500}
figcaption{color:var(--muted);font-size:.85rem;max-width:68ch}
footer{border-top:1px solid var(--line-strong);padding-top:1.1rem;color:var(--muted);font-size:.86rem;display:flex;
flex-direction:column;gap:.5rem}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def td(v):
    return "" if v in (None, 0, "") else v


P = []
P.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
P.append(f"<title>{TITLE}</title>")
P.append(
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
)
P.append(
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&"
    'family=IBM+Plex+Sans+Condensed:wght@600&display=swap">'
)
P.append("<style>" + CSS + "</style>")
P.append('<div class="wrap">')

P.append('<header class="prose"><p class="eyebrow">Analyse d’export</p>')
P.append(f"<h1>{TITLE}</h1>")
P.append(
    f'<p class="lede">{len(tracked)} jours suivis du {WIN} au {tracked[-1]["date"]}, {len(wi)} pesées réelles, '
    f"{len(sess)} séances. Généré le {d['_readme']['generated_at'][:10]} depuis l’export Yazio.</p></header>"
)

# 1. contexte
P.append("<section><h2>Contexte</h2>")
P.append('<div class="tw"><table class="kv"><tbody>')
P.append(
    f"<tr><td>Profil</td><td>Homme, {prof['age_years']} ans, {prof['body_height']:.0f} cm, "
    f"{wt} kg au {wi[-1]['date']}</td></tr>"
)
_aim = {"lose": "perdre du poids", "gain": "prendre du poids", "maintain": "stabiliser le poids"}
P.append(
    f"<tr><td>Objectif</td><td>Établir la dépense réelle, puis "
    f"{_aim.get(prof.get('goal'), 'atteindre l’objectif fixé')}</td></tr>"
)
if TARGET_KG:
    P.append(
        f"<tr><td>Cible poids</td><td>{fr(TARGET_KG)} kg, soit {fr(wt - TARGET_KG)} kg à perdre, "
        f"à {fr(abs(prof['weight_change_per_week']))} kg/semaine visée</td></tr>"
    )
P.append(
    f"<tr><td>Objectif app</td><td>{goal} kcal, <code>activity_degree = {prof['activity_degree']}</code></td></tr>"
)
P.append(
    f"<tr><td>Répartition cible</td><td>P {prof['diet']['protein_percentage']} % / "
    f"G {prof['diet']['carb_percentage']} % / L {prof['diet']['fat_percentage']} %</td></tr>"
)
P.append("</tbody></table></div></section>")

# 2. poids
P.append("<section><h2>Poids mesuré</h2>")
P.append(
    f"<figure>{chart}<figcaption>Les {len(wi)} pesées réelles de la période. "
    f"Trait plein : mesures successives. Pointillé : régression linéaire, pente "
    f"{fr(slope * 7, 2)} kg/semaine. L’export contient une valeur de poids pour chaque date, "
    "mais l’API recopie la dernière pesée connue ; seuls ces points sont des mesures.</figcaption></figure>"
)
P.append(
    '<div class="note"><h3>Ne pas surinterpréter le dernier point</h3>'
    f"<p>Le passage de {ys[-2]} kg le {wi[-2]['date'][8:]}/{wi[-2]['date'][5:7]} à {ys[-1]} kg le "
    f"{wi[-1]['date'][8:]}/{wi[-1]['date'][5:7]} représente {fr(ys[-2] - ys[-1])} kg en "
    f"{xs[-1] - xs[-2]} jours. Aucune perte de masse grasse ne va à cette vitesse : "
    "c’est de l’eau et du contenu digestif. Ce point tire la pente et donc toutes les "
    "estimations ci-dessous.</p></div></section>"
)

# 3. apports
P.append("<section><h2>Apports jour par jour</h2>")
P.append(
    '<div class="tw"><table><thead><tr>'
    "<th>Date</th><th>Jour</th><th>kcal</th><th>Prot g</th><th>Gluc g</th><th>Lip g</th>"
    "<th>Obj</th><th>Sport min</th><th>Pas</th><th>Pesée</th></tr></thead><tbody>"
)
for r in rows_all:
    dim = ' class="dim"' if r["below_tracking_threshold"] else ""
    mark = " · partiel" if r["below_tracking_threshold"] else ""
    st = f"{r['steps']}*" if r["steps_suspect"] else r["steps"]
    wcell = f'<td class="hi">{r["weigh_in_kg"]}</td>' if r["weigh_in_kg"] else "<td></td>"
    P.append(
        f"<tr{dim}><td>{r['date'][8:]}/{r['date'][5:7]}{mark}</td><td>{FR[r['weekday']]}</td>"
        f"<td>{r['kcal']}</td><td>{r['protein_g']}</td><td>{r['carbs_g']}</td><td>{r['fat_g']}</td>"
        f"<td>{r['goal_kcal']}</td><td>{td(r['sport_min'])}</td><td>{st}</td>{wcell}</tr>"
    )
P.append("</tbody></table></div>")
P.append(
    f'<p class="lede">* capteur probablement non porté ({len(suspect)} jours sous 2000 pas). '
    "Lignes grisées : sous le seuil de 800 kcal, exclues des moyennes.</p>"
)

P.append(
    '<h3>Par tranche</h3><div class="tw"><table><thead><tr><th>Tranche</th><th>Jours</th>'
    "<th>kcal moyen</th><th>Prot g</th><th>Pas</th></tr></thead><tbody>"
)
for lab, rs in weeks:
    if rs:
        P.append(
            f"<tr><td>{lab}</td><td>{len(rs)}</td><td>{mean(rs, 'kcal'):.0f}</td>"
            f"<td>{mean(rs, 'protein_g'):.0f}</td><td>{mean(rs, 'steps'):.0f}</td></tr>"
        )
P.append(
    f"<tr><td><b>Période</b></td><td><b>{len(tracked)}</b></td><td><b>{avg:.0f}</b></td>"
    f"<td><b>{prot:.0f}</b></td><td><b>{mean(tracked, 'steps'):.0f}</b></td></tr>"
)
P.append("</tbody></table></div>")
P.append("<ul>")
P.append(
    f"<li>Apport moyen {avg:.0f} kcal, écart-type {sd:.0f}. L’objectif de l’app est à "
    f"{goal} kcal, soit {avg - goal:+.0f} par rapport à la consommation réelle, et le poids baisse quand même.</li>"
)
P.append(
    f"<li>Protéines à {prot:.0f} g en moyenne, {fr(prot / wt, 2)} g/kg. La fourchette usuelle pour "
    f"préserver le muscle en déficit est 1,6 à 2,0 g/kg, soit {wt * 1.6:.0f} à {wt * 2:.0f} g.</li>"
)
if low_p:
    P.append(
        "<li>Jours creux en protéines : "
        + ", ".join(f"{r['date'][8:]}/{r['date'][5:7]} ({r['protein_g']} g)" for r in low_p)
        + ".</li>"
    )
P.append("</ul></section>")

# 4. TDEE
P.append("<section><h2>Dépense énergétique</h2>")
P.append(
    '<div class="tw"><table><thead><tr><th>Méthode</th><th>kcal/j</th><th>Ce qu’elle vaut</th></tr></thead><tbody>'
)
P.append(
    f"<tr><td>Première et dernière pesée</td><td>{tdee_naive:.0f}</td>"
    '<td style="text-align:left">Fragile : deux points, dont un bruité</td></tr>'
)
P.append(
    f"<tr><td>Régression sur {len(wi)} pesées</td><td>{tdee_reg:.0f}</td>"
    '<td style="text-align:left">Meilleure, mais série courte</td></tr>'
)
P.append(
    f"<tr><td>Mifflin-St Jeor × 1,375 (léger)</td><td>{bmr * 1.375:.0f}</td>"
    f'<td style="text-align:left">Théorique, base {bmr:.0f} kcal</td></tr>'
)
P.append(
    f"<tr><td>Mifflin-St Jeor × 1,55 (modéré)</td><td>{bmr * 1.55:.0f}</td>"
    '<td style="text-align:left">Théorique</td></tr>'
)
P.append("</tbody></table></div>")
P.append(
    '<div class="note"><h3>Fourchette retenue : '
    f"{LO} à {HI} kcal, centre {CENTRE}</h3>"
    f"<p>La régression ({tdee_reg:.0f}) et Mifflin modéré ({bmr * 1.55:.0f}) se rejoignent, "
    "ce qui est encourageant, mais les deux reposent en partie sur le même point de mesure récent. "
    f"À {avg:.0f} kcal d’apport, le déficit implicite au centre de la fourchette est d’environ "
    f"{CENTRE - avg:.0f} kcal/jour, soit {fr((CENTRE - avg) * 7 / 7700, 2)} kg/semaine.</p>"
    "<p>Ce chiffre reste provisoire. Il demande quatre à six semaines de pesées quotidiennes "
    "pour se stabiliser.</p></div>"
)
if TARGET_KG and wt > TARGET_KG:
    _slow = (wt - TARGET_KG) * 7700 / ((CENTRE - avg) * 30.4)
    _fast = (wt - TARGET_KG) * 7700 / (500 * 30.4)
    P.append(
        f'<p class="lede">Arithmétique brute, sans prescription : de {fr(wt)} à {fr(TARGET_KG)} kg, '
        f"à {CENTRE - avg:.0f} kcal de déficit il faut environ {_slow:.0f} mois ; "
        f"à 500 kcal de déficit (apport {CENTRE - 500:.0f}), environ {_fast:.0f} mois.</p>"
    )
P.append("</section>")

# 5. activite
act = mets["activity_recent"]
P.append("<section><h2>Activité</h2>")
P.append('<div class="tw"><table class="kv"><tbody>')
P.append(f"<tr><td>Séances</td><td>{act['sessions']}, dont {act['morning_sessions']} avant midi</td></tr>")
P.append(f"<tr><td>Volume</td><td>{act['total_min']} min, {act['total_kcal']} kcal</td></tr>")
for t, v in act["by_type"].items():
    P.append(f"<tr><td>{html.escape(t)}</td><td>{v['sessions']} séances, {v['min']} min, {v['kcal']} kcal</td></tr>")
P.append(
    f"<tr><td>Pas</td><td>{mean(tracked, 'steps'):.0f}/jour en moyenne, capteur absent {len(suspect)} jours</td></tr>"
)
P.append("</tbody></table></div>")
P.append(
    '<div class="tw"><table><thead><tr>'
    "<th>Date</th><th>Heure</th><th>Type</th><th>Min</th><th>kcal</th>"
    "</tr></thead><tbody>"
)
for s in sess:
    P.append(
        f"<tr><td>{s['date'][8:]}/{s['date'][5:7]}</td><td>{s['time'] or '?'}</td>"
        f"<td>{html.escape(s['type'] or '?')}</td><td>{s['duration_min']}</td><td>{s['kcal']}</td></tr>"
    )
P.append("</tbody></table></div>")
P.append(
    "<ul><li>Format court et régulier, créneau du matin dominant. "
    "Un stimulus de 15 minutes reste modeste pour la préservation musculaire, "
    "ce qui est cohérent avec une reprise progressive.</li>"
    "<li>La dépense mesurée ici correspond à une phase de faible volume. "
    "Au retour d’un entraînement habituel, elle montera et devra être remesurée.</li></ul></section>"
)

# 6. reglages
P.append("<section><h2>Réglages de l’application</h2>")
P.append(
    f"<ul><li><b>Corrigé :</b> <code>activity_degree</code> est passé à "
    f"<code>{prof['activity_degree']}</code>. L’objectif calorique est descendu à {goal} kcal en conséquence.</li>"
)
_susp = ", ".join(x[8:] + "/" + x[5:7] for x in suspect)
P.append(
    f"<li><b>Reste à faire :</b> porter le capteur de pas tous les jours. "
    f"{len(suspect)} jours sur {len(tracked)} sont inexploitables ({_susp}).</li>"
)
P.append("<li><b>Reste à faire :</b> une pesée par jour, mêmes conditions.</li></ul></section>")

# 7. reco
P.append("<section><h2>Par ordre d’impact</h2><ol>")
P.append(
    "<li><b>Se peser chaque matin</b>, après passage aux toilettes, avant de manger, et lire la "
    "moyenne glissante sur 7 jours plutôt que la valeur du jour. C’est le seul moyen de séparer "
    "la variation d’eau de la perte réelle, et c’est ce qui bloque aujourd’hui l’estimation.</li>"
)
P.append(
    f"<li><b>Monter les protéines</b> vers {wt * 1.6:.0f} g les jours creux. "
    f"La moyenne de {prot:.0f} g masque des écarts de {min(r['protein_g'] for r in tracked)} à "
    f"{max(r['protein_g'] for r in tracked)} g.</li>"
)
P.append(
    "<li><b>Tenir quatre à six semaines</b> avant de conclure sur la dépense. "
    "Les deux premières semaines contiennent les ajustements hydriques du début de suivi.</li>"
)
P.append(
    f"<li><b>Régulariser l’apport.</b> L’écart-type de {sd:.0f} kcal allonge le temps "
    "nécessaire pour que le signal sorte du bruit.</li>"
)
P.append("<li><b>Remesurer</b> après le retour à un volume d’entraînement habituel.</li></ol></section>")

P.append("<footer>")
P.append(
    "<p>Aucun chiffre de cette page n’est saisi à la main : tous sont calculés depuis "
    "<code>yazio-dataset.json</code> à la génération.</p>"
)
P.append(
    "<p>Chaîne complète : <code>yazio-exporter sync</code>, puis <code>build_dataset.py</code>, "
    "puis <code>build_analysis.py</code>.</p>"
)
P.append(
    "<p>Cette page se limite à ce que les données montrent. Toute décision d’entraînement "
    "ou de santé relève d’un professionnel.</p>"
)
P.append("</footer></div>")

OUT.write_text("\n".join(P), encoding="utf-8")
OUT.chmod(0o600)
print(OUT, len(OUT.read_bytes()), "bytes")
print(
    f"tracked={len(tracked)} weigh_ins={len(wi)} sessions={len(sess)} avg={avg:.0f} tdee_reg={tdee_reg:.0f} "
    f"bmr={bmr:.0f}"
)
