#!/usr/bin/env python3
"""Gera a página de documentação do Caixa Factory a partir dos .md."""
import json, pathlib, re, sys
import markdown

BASE = pathlib.Path(__file__).resolve().parent
DOCS = [
    ("README.md",          "Visão geral",      "Por onde começar, princípios e infraestrutura"),
    ("01-dominio.md",      "Domínio",          "Glossário, regras de negócio e armadilhas reais"),
    ("02-modelo-dados.md", "Modelo de dados",  "DDL PostgreSQL, triggers e views"),
    ("03-formulas.md",     "Fórmulas",         "Todo o cálculo, conferido nos dados reais"),
    ("04-api.md",          "API",              "Endpoints REST, payloads e erros"),
    ("05-telas.md",        "Telas",            "Comportamento da interface"),
    ("06-robo.md",         "Robôs",            "Ingestão, conciliação e alerta de caixa parado"),
    ("07-migracao.md",     "Migração",         "Carga dos dados que já existem"),
    ("08-deploy.md",       "Deploy",           "VPS Hostinger, domínio Locaweb, HTTPS e backup"),
]

def esc_script(s: str) -> str:
    return s.replace("</script", "<\\/script").replace("</style", "<\\/style")

MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "attr_list"])

def para_html(texto: str) -> str:
    MD.reset()
    html = MD.convert(texto)
    # o h1 do arquivo vira o cabecalho do documento; remove do corpo
    html = re.sub(r"^\s*<h1[^>]*>.*?</h1>\s*", "", html, count=1, flags=re.S)
    # tabela ganha contêiner que rola sozinho
    html = html.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    return html

docs = []
for arq, titulo, sub in DOCS:
    texto = (BASE / arq).read_text(encoding="utf-8")
    docs.append({"arq": arq, "titulo": titulo, "sub": sub, "html": para_html(texto)})

seed = (BASE / "seed" / "estado-2026-10-19.json").read_text(encoding="utf-8")

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --bg:#EEF0F3; --surface:#FFFFFF; --surface-2:#F6F7F9;
  --line:#DCE0E6; --line-2:#C6CCD5;
  --ink:#11161D; --ink-2:#48515E; --ink-3:#79838F;
  --accent:#14508C; --accent-soft:#E3EDF7;
  --ok:#136A4B; --ok-soft:#DFEFE7;
  --warn:#8A5A00; --warn-soft:#FAEDD2;
  --bad:#9C2A21; --bad-soft:#F9E3E0;
  --band:#101821; --band-ink:#EDF1F6; --band-ink-2:#94A1B1; --band-line:#26313F;
  --code-bg:#F2F4F7; --code-ink:#1C2733;
  --shadow:0 1px 2px rgba(16,24,34,.05),0 10px 26px rgba(16,24,34,.06);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  color-scheme:dark;
  --bg:#0B0F15; --surface:#141A22; --surface-2:#1A212B;
  --line:#26303C; --line-2:#36414F;
  --ink:#E7ECF3; --ink-2:#A4AFBD; --ink-3:#7B8694;
  --accent:#77ACE8; --accent-soft:#16273A;
  --ok:#54C296; --ok-soft:#11271F;
  --warn:#DFAC42; --warn-soft:#2A2110;
  --bad:#EF8577; --bad-soft:#2E1714;
  --band:#141A22; --band-ink:#E7ECF3; --band-ink-2:#8F9BAA; --band-line:#26303C;
  --code-bg:#10161E; --code-ink:#C8D4E2;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 26px rgba(0,0,0,.35);
}}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0B0F15; --surface:#141A22; --surface-2:#1A212B;
  --line:#26303C; --line-2:#36414F;
  --ink:#E7ECF3; --ink-2:#A4AFBD; --ink-3:#7B8694;
  --accent:#77ACE8; --accent-soft:#16273A;
  --ok:#54C296; --ok-soft:#11271F;
  --warn:#DFAC42; --warn-soft:#2A2110;
  --bad:#EF8577; --bad-soft:#2E1714;
  --band:#141A22; --band-ink:#E7ECF3; --band-ink-2:#8F9BAA; --band-line:#26303C;
  --code-bg:#10161E; --code-ink:#C8D4E2;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 26px rgba(0,0,0,.35);
}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}

.band{background:var(--band);border-bottom:1px solid var(--band-line)}
.band-in{max-width:1180px;margin:0 auto;padding:15px 22px;display:flex;flex-wrap:wrap;
  gap:14px;align-items:center;justify-content:space-between}
.brand{display:flex;gap:12px;align-items:center;min-width:0}
.mark{width:38px;height:38px;flex:0 0 38px;border-radius:8px;display:grid;place-items:center;
  background:linear-gradient(160deg,#1D5FA3,#0E3560);color:#fff;
  font-family:Archivo,sans-serif;font-weight:700;font-size:13px}
.brand h1{margin:0;color:var(--band-ink);font-family:Archivo,sans-serif;font-size:18px;font-weight:700}
.brand p{margin:0;color:var(--band-ink-2);font-size:12.5px}
.selo{font-family:Archivo,sans-serif;font-size:11.5px;font-weight:600;letter-spacing:.04em;
  color:var(--band-ink-2);border:1px solid var(--band-line);border-radius:99px;padding:5px 11px}

.layout{max-width:1180px;margin:0 auto;padding:22px;display:grid;
  grid-template-columns:238px minmax(0,1fr);gap:22px;align-items:start}
nav{position:sticky;top:22px;background:var(--surface);border:1px solid var(--line);
  border-radius:10px;box-shadow:var(--shadow);overflow:hidden}
nav ol{list-style:none;margin:0;padding:6px}
nav a{display:block;padding:8px 11px;border-radius:7px;text-decoration:none;color:var(--ink-2);
  font-size:13.5px;line-height:1.35}
nav a .n{font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--ink-3);
  margin-right:7px;font-weight:600}
nav a:hover{background:var(--surface-2);color:var(--ink)}
nav a.sel{background:var(--accent-soft);color:var(--accent);font-weight:600}
nav a.sel .n{color:var(--accent)}
nav a:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.nav-sel{display:none;width:100%;padding:10px;font:inherit;font-family:Archivo,sans-serif;
  font-weight:600;background:var(--surface);color:var(--ink);
  border:1px solid var(--line-2);border-radius:9px}

main{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  box-shadow:var(--shadow);padding:30px 34px 40px;min-width:0}
.doc-head{border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:26px}
.doc-head .eyebrow{font-family:Archivo,sans-serif;font-size:11px;font-weight:600;
  letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);margin:0 0 5px}
.doc-head p{margin:4px 0 0;color:var(--ink-3);font-size:13.5px}

article{max-width:76ch}
article h1{font-family:Archivo,sans-serif;font-size:25px;font-weight:700;letter-spacing:-.015em;
  margin:0;text-wrap:balance}
article h2{font-family:Archivo,sans-serif;font-size:19px;font-weight:600;letter-spacing:-.01em;
  margin:36px 0 12px;padding-top:12px;border-top:1px solid var(--line);text-wrap:balance}
article h2:first-of-type{border-top:0;padding-top:0;margin-top:26px}
article h3{font-family:Archivo,sans-serif;font-size:15.5px;font-weight:600;margin:26px 0 9px}
article h4{font-family:Archivo,sans-serif;font-size:14px;font-weight:600;margin:20px 0 7px;color:var(--ink-2)}
article p{margin:0 0 13px}
article ul,article ol{margin:0 0 13px;padding-left:22px}
article li{margin:4px 0}
article li>p{margin:0 0 6px}
article a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:2px}
article strong{font-weight:600}
article hr{border:0;border-top:1px solid var(--line);margin:30px 0}

code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.88em;
  background:var(--code-bg);color:var(--code-ink);padding:2px 5px;border-radius:4px}
pre{background:var(--code-bg);border:1px solid var(--line);border-radius:9px;
  padding:14px 16px;overflow-x:auto;margin:0 0 16px}
pre code{background:none;padding:0;font-size:12.6px;line-height:1.6;color:var(--code-ink)}

.tw{overflow-x:auto;margin:0 0 18px;border:1px solid var(--line);border-radius:9px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font-family:Archivo,sans-serif;font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink-3);text-align:left;padding:10px 13px;
  background:var(--surface-2);border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 13px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
td code{font-size:.85em}

blockquote{margin:0 0 16px;padding:12px 15px;background:var(--warn-soft);
  border:1px solid var(--warn);border-radius:9px;color:var(--ink)}
blockquote p{margin:0 0 7px}
blockquote p:last-child{margin:0}

.rodape{max-width:1180px;margin:0 auto;padding:0 22px 50px;color:var(--ink-3);font-size:12.5px}

@media (max-width:860px){
  .layout{grid-template-columns:1fr;padding:16px}
  nav{position:static;background:none;border:0;box-shadow:none;overflow:visible}
  nav ol{display:none}
  .nav-sel{display:block}
  main{padding:22px 18px 30px}
  article h1{font-size:21px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media print{
  .band,nav,.rodape{display:none}
  main{border:0;box-shadow:none;padding:0}
  .doc:not(.ativo){display:block!important}
}
"""

JS = """
const DOCS = JSON.parse(document.getElementById('docs').textContent);

const nav  = document.getElementById('lista');
const sel  = document.getElementById('nav-sel');
const main = document.getElementById('conteudo');

function slug(arq){ return arq.replace(/\\.md$/, ''); }

function render(i){
  const d = DOCS[i];
  main.innerHTML =
      '<div class="doc-head"><p class="eyebrow">' + String(i).padStart(2,'0')
    + ' &middot; Caixa Factory</p><h1></h1><p></p></div>'
    + '<article>' + d.html + '</article>';
  main.querySelector('.doc-head h1').textContent = d.titulo;
  main.querySelector('.doc-head p:last-of-type').textContent = d.sub;

  main.querySelectorAll('article a[href$=".md"], article a[href*=".md#"]').forEach(function(a){
    const alvo = a.getAttribute('href').split('#')[0];
    const j = DOCS.findIndex(function(x){ return x.arq === alvo; });
    if (j >= 0) a.setAttribute('href', '#' + slug(DOCS[j].arq));
  });

  nav.querySelectorAll('a').forEach(function(a, k){
    a.classList.toggle('sel', k === i);
    if (k === i) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  sel.value = String(i);
  window.scrollTo({ top: 0 });
}

DOCS.forEach(function(d, i){
  const li = document.createElement('li');
  const a  = document.createElement('a');
  a.href = '#' + slug(d.arq);
  a.innerHTML = '<span class="n">' + String(i).padStart(2,'0') + '</span>';
  a.appendChild(document.createTextNode(d.titulo));
  li.appendChild(a); nav.appendChild(li);

  const op = document.createElement('option');
  op.value = String(i);
  op.textContent = String(i).padStart(2,'0') + ' \\u00b7 ' + d.titulo;
  sel.appendChild(op);
});

sel.addEventListener('change', function(){ location.hash = slug(DOCS[Number(sel.value)].arq); });

function doHash(){
  const h = location.hash.replace('#','');
  let i = DOCS.findIndex(function(d){ return slug(d.arq) === h; });
  if (i < 0) i = 0;
  render(i);
}
window.addEventListener('hashchange', doHash);
doHash();
"""


html = f"""<title>Caixa Factory — documentação</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;family=IBM+Plex+Mono:wght@400;500;600&amp;display=swap">
<style>{CSS}</style>

<header class="band"><div class="band-in">
  <div class="brand">
    <div class="mark">CF</div>
    <div>
      <h1>Caixa Factory</h1>
      <p>Especificação técnica para implementação</p>
    </div>
  </div>
  <span class="selo">v1 · 16/11/2026</span>
</div></header>

<div class="layout">
  <nav aria-label="Documentos">
    <select class="nav-sel" id="nav-sel" aria-label="Escolher documento"></select>
    <ol id="lista"></ol>
  </nav>
  <main id="conteudo"></main>
</div>

<p class="rodape">Gerado a partir dos arquivos .md do repositório. A fonte da
verdade são os arquivos em <code>MACHADO-FACTORY/CAIXA-FACTORY/docs/</code>.</p>

<script id="docs" type="application/json">{esc_script(json.dumps(docs, ensure_ascii=False))}</script>
<script>{esc_script(JS)}</script>
"""

saida = BASE.parent / "caixa-factory-docs.html"
saida.write_text(html, encoding="utf-8")
print("gerado:", saida, len(html), "bytes")
