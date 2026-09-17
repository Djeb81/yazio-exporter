#!/usr/bin/env python3
"""Build a self-contained handoff page embedding the dataset + CSVs for copying."""

import html
import json
import os
from pathlib import Path

D = Path(os.environ.get("YAZIO_EXPORT_DIR", Path.home() / "yazio-export")).expanduser()
OUT = D / "handoff.html"

data = json.loads((D / "yazio-dataset.json").read_text(encoding="utf-8"))
rd = data["_readme"]
m = data["metrics"]

SECTIONS = [
    (
        "yazio-dataset.json",
        D / "yazio-dataset.json",
        "JSON",
        "Tout le jeu de données : profil nettoyé, métriques, tables et les sept mises en garde. C'est le seul fichier "
        "nécessaire si le projet lit du JSON.",
    ),
    (
        "daily.csv",
        D / "csv/daily.csv",
        "CSV",
        "Une ligne par jour. Repas éclatés en colonnes, drapeaux partial / below_tracking_threshold / steps_suspect "
        "conservés.",
    ),
    (
        "sessions.csv",
        D / "csv/sessions.csv",
        "CSV",
        "Une ligne par séance, avec l'heure de début. Plusieurs séances possibles le même jour.",
    ),
    (
        "weigh_ins.csv",
        D / "csv/weigh_ins.csv",
        "CSV",
        "Pesées réelles uniquement. À utiliser à la place de weight_carried_kg pour toute analyse de poids.",
    ),
    (
        "foods.csv",
        D / "csv/foods.csv",
        "CSV",
        "Produits agrégés sur tout l'historique, triés par fréquence puis calories.",
    ),
    (
        "micronutrients.csv",
        D / "csv/micronutrients.csv",
        "CSV",
        "Format long. Valeurs brutes de l'API, dont l'unité par nutriment n'est pas déclarée.",
    ),
]


def fmt_size(n):
    return f"{n / 1024:.1f} Ko" if n >= 1024 else f"{n} o"


stats = [
    ("Période", f"{data['daily'][0]['date']} → {data['daily'][-1]['date']}"),
    ("Jours", str(len(data["daily"]))),
    ("Séances", str(len(data["sessions"]))),
    ("Pesées réelles", str(len(data["weigh_ins"]))),
    ("Produits", str(len(data["foods"]))),
    ("Généré le", rd["generated_at"][:16].replace("T", " ")),
]

CSS = """
:root{
  --ground:#FBFBF9; --surface:#FFFFFF; --sunk:#F3F4EF;
  --ink:#1C1F1B; --muted:#5F665C; --line:#DCDFD7; --line-strong:#C3C8BA;
  --accent:#4A6B3D; --accent-soft:#EDF2E8; --flag:#9A6224; --flag-soft:#FBF3E6;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#141613; --surface:#1C1F1B; --sunk:#191C17;
    --ink:#E6E8E2; --muted:#9BA396; --line:#32362E; --line-strong:#454B40;
    --accent:#8FB57C; --accent-soft:#232A1E; --flag:#D3A063; --flag-soft:#2A2114;
  }
}
:root[data-theme="dark"]{
  --ground:#141613; --surface:#1C1F1B; --sunk:#191C17;
  --ink:#E6E8E2; --muted:#9BA396; --line:#32362E; --line-strong:#454B40;
  --accent:#8FB57C; --accent-soft:#232A1E; --flag:#D3A063; --flag-soft:#2A2114;
}
*{box-sizing:border-box}
body{
  margin:0; padding-block:2.5rem 4rem; padding-left:1.25rem; padding-right:1.25rem;
  background:var(--ground); color:var(--ink);
  font:400 16px/1.6 "IBM Plex Sans","Segoe UI",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:70rem; margin:0 auto; display:flex; flex-direction:column; gap:2.5rem}
.prose{max-width:68ch}
h1,h2,h3{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif; font-weight:600; text-wrap:balance; margin:0}
h1{font-size:clamp(1.75rem,4vw,2.4rem); letter-spacing:-.01em; line-height:1.15}
h2{font-size:1.3rem; letter-spacing:.005em}
.eyebrow{
  font-family:"IBM Plex Sans Condensed",sans-serif; font-size:.72rem; font-weight:600;
  text-transform:uppercase; letter-spacing:.14em; color:var(--accent); margin:0 0 .5rem;
}
p{margin:0 0 .85rem} p:last-child{margin-bottom:0}
.lede{color:var(--muted); font-size:1.02rem}
code{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.88em; background:var(--sunk); padding:.1em .35em;
 border-radius:3px}

/* stats: label/value pairs on a hairline grid, not cards */
.stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px; background:var(--line);
 border:1px solid var(--line)}
.stat{background:var(--surface); padding:.7rem .9rem; display:flex; flex-direction:column; gap:.15rem}
.stat dt{font-family:"IBM Plex Sans Condensed",sans-serif; font-size:.68rem; text-transform:uppercase;
 letter-spacing:.12em; color:var(--muted)}
.stat dd{margin:0; font-family:"IBM Plex Mono",monospace; font-size:.9rem; font-variant-numeric:tabular-nums}

/* caveats: the one place amber is spent */
.caveats{border-left:3px solid var(--flag); background:var(--flag-soft); padding:1.1rem 1.25rem}
.caveats h2{font-size:1.05rem; color:var(--flag); margin-bottom:.6rem}
.caveats ol{margin:0; padding-left:1.15rem; display:flex; flex-direction:column; gap:.55rem}
.caveats li{font-size:.93rem; line-height:1.55}
.caveats strong{font-family:"IBM Plex Sans Condensed",sans-serif; letter-spacing:.02em}

.ds{display:flex; flex-direction:column; gap:.65rem; border-top:1px solid var(--line-strong); padding-top:1.1rem}
.ds-head{display:flex; flex-wrap:wrap; align-items:baseline; gap:.5rem .75rem}
.ds-name{font-family:"IBM Plex Mono",monospace; font-size:1.02rem; font-weight:500}
.kind{font-family:"IBM Plex Sans Condensed",sans-serif; font-size:.65rem; font-weight:600; text-transform:uppercase;
  letter-spacing:.1em; color:var(--accent); background:var(--accent-soft); padding:.15rem .45rem; border-radius:2px}
.meta{font-family:"IBM Plex Mono",monospace; font-size:.78rem; color:var(--muted); font-variant-numeric:tabular-nums}
.ds-desc{font-size:.92rem; color:var(--muted); max-width:68ch; margin:0}
.btn{
  margin-left:auto; font-family:"IBM Plex Sans Condensed",sans-serif; font-size:.8rem; font-weight:600;
  letter-spacing:.04em; color:var(--surface); background:var(--accent); border:1px solid var(--accent);
  padding:.4rem .85rem; border-radius:3px; cursor:pointer; white-space:nowrap;
}
.btn:hover{filter:brightness(1.08)}
.btn:focus-visible{outline:2px solid var(--ink); outline-offset:2px}
.btn[data-state="ok"]{background:var(--surface); color:var(--accent)}
.btn[data-state="manual"]{background:var(--flag-soft); color:var(--flag); border-color:var(--flag)}
pre{
  margin:0; background:var(--sunk); border:1px solid var(--line);
  padding:.85rem 1rem; max-height:16rem; overflow:auto;
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.79rem; line-height:1.55;
  white-space:pre; tab-size:2;
}
footer{border-top:1px solid var(--line-strong); padding-top:1.1rem; color:var(--muted); font-size:.87rem}
footer p{max-width:68ch}
@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
"""

JS = """
document.querySelectorAll('.btn').forEach(function(btn){
  btn.addEventListener('click', function(){
    var pre = document.getElementById(btn.dataset.target);
    var text = pre.textContent;
    var done = function(label, state){
      btn.textContent = label; btn.dataset.state = state;
      setTimeout(function(){ btn.textContent = 'Copier'; btn.removeAttribute('data-state'); }, 4000);
    };
    var manual = function(){
      var r = document.createRange(); r.selectNodeContents(pre);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      done('S\\u00e9lectionn\\u00e9, faites Ctrl+C', 'manual');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function(){ done('Copi\\u00e9', 'ok'); }, manual);
    } else { manual(); }
  });
});
"""

parts = []
parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
parts.append("<title>Données Yazio pour Cowork</title>")
parts.append(
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
)
parts.append(
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&"
    'family=IBM+Plex+Sans+Condensed:wght@600&display=swap">'
)
parts.append("<style>" + CSS + "</style>")
parts.append('<div class="wrap">')

parts.append('<header class="prose">')
parts.append('<p class="eyebrow">Transfert de données</p>')
parts.append("<h1>Données Yazio pour Cowork</h1>")
parts.append(
    '<p class="lede">Les cartes de fichier ne se téléchargent pas chez vous, donc tout est ici en clair. '
    "Le bouton Copier met le contenu dans le presse-papiers ; s’il est bloqué, il sélectionne le bloc pour un "
    "Ctrl+C.</p>"
)
parts.append("</header>")

parts.append('<dl class="stats">')
for label, val in stats:
    parts.append(f'<div class="stat"><dt>{html.escape(label)}</dt><dd>{html.escape(val)}</dd></div>')
parts.append("</dl>")

parts.append('<section class="caveats">')
parts.append("<h2>À lire avant d’exploiter les chiffres</h2><ol>")
for c in rd["caveats"]:
    head, _, rest = c.partition(": ")
    parts.append(f"<li><strong>{html.escape(head)}</strong> — {html.escape(rest or c)}</li>")
parts.append("</ol></section>")

parts.append(
    '<section class="prose"><h2>Fichiers</h2><p class="lede">Six blocs, indépendants. '
    "Le JSON contient déjà tout ; les CSV sont là si le projet préfère du tabulaire.</p></section>"
)

for i, (name, path, kind, desc) in enumerate(SECTIONS):
    raw = path.read_text(encoding="utf-8")
    lines = raw.count("\n")
    rows = f"{lines - 1} lignes" if kind == "CSV" else f"{lines} lignes"
    pid = f"d{i}"
    parts.append('<section class="ds">')
    parts.append('<div class="ds-head">')
    parts.append(f'<span class="ds-name">{html.escape(name)}</span>')
    parts.append(f'<span class="kind">{kind}</span>')
    parts.append(f'<span class="meta">{rows} · {fmt_size(len(raw.encode()))}</span>')
    parts.append(f'<button class="btn" type="button" data-target="{pid}">Copier</button>')
    parts.append("</div>")
    parts.append(f'<p class="ds-desc">{html.escape(desc)}</p>')
    parts.append(f'<pre id="{pid}" tabindex="0">{html.escape(raw)}</pre>')
    parts.append("</section>")

parts.append("<footer>")
parts.append(
    "<p>Source : export <code>yazio-exporter</code> (fork local), dossier <code>$YAZIO_EXPORT_DIR</code>. "
    "Regénération après un <code>yazio-exporter sync</code> : "
    "<code>python3 tools/build_dataset.py</code> puis <code>python3 tools/build_handoff.py</code>.</p>"
)
parts.append(f"<p>{html.escape(rd['privacy'])}</p>")
parts.append("</footer></div>")
parts.append("<script>" + JS + "</script>")

OUT.write_text("\n".join(parts), encoding="utf-8")
OUT.chmod(0o600)
print(OUT, len(OUT.read_bytes()), "bytes")
