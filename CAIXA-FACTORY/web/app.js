/* Caixa Factory — a tela (docs/05-telas.md).
 *
 * É a página do Caixa Machado com o estado embutido trocado pela API: todo
 * número vem do servidor (as views do banco são a fonte das fórmulas) e toda
 * gravação passa pelas validações dele. Dinheiro chega como string decimal e é
 * tratado em centavos inteiros; nunca como float.
 */
(function () {
  "use strict";

  /* ============ util ============ */
  var moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  function centavos(s) {                       // "1234.56" -> 123456 (sem float)
    if (s == null || s === "") return 0;
    var t = String(s), neg = t.charAt(0) === "-";
    if (neg) t = t.slice(1);
    var p = t.split("."), c = parseInt(p[0] || "0", 10) * 100 + parseInt(((p[1] || "") + "00").slice(0, 2), 10);
    return neg ? -c : c;
  }
  function deCentavos(c) {                     // 123456 -> "1234.56"
    var neg = c < 0; c = Math.abs(c);
    var s = Math.floor(c / 100) + "." + String(100 + (c % 100)).slice(1);
    return neg ? "-" + s : s;
  }
  function R(s) { return moeda.format(centavos(s) / 100); }            // exibição
  function Rc(c) { return moeda.format(c / 100); }
  function pctF(f, casas) { return (isFinite(f) ? f * 100 : 0).toFixed(casas == null ? 2 : casas).replace(".", ",") + "%"; }
  function pct(s, casas) { return pctF(Number(s || 0), casas); }      // "0.041667" -> "4,17%" (só exibição)
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c];
    });
  }
  function hoje() {
    try { return new Date().toLocaleDateString("sv", { timeZone: "America/Sao_Paulo" }); }
    catch (e) { return new Date().toISOString().slice(0, 10); }
  }
  function dbr(d) { if (!d) return "—"; var p = String(d).slice(0, 10).split("-"); return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : d; }
  function dcurto(d) { if (!d) return "—"; var p = String(d).split("-"); return p.length === 3 ? p[2] + "/" + p[1] : d; }
  function maisDias(iso, n) {
    var p = String(iso || hoje()).split("-");
    var dt = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n));
    return dt.toISOString().slice(0, 10);
  }
  /* Entrada de valor: aceita 1.234,56 · 1234,56 · 1234.56. Devolve "1234.56",
     "" (vazio) ou null (inválido). */
  function entrada(v) {
    var s = String(v == null ? "" : v).trim().replace(/R\$/g, "").replace(/\s/g, "");
    if (!s) return "";
    if (s.indexOf(",") > -1) s = s.replace(/\./g, "").replace(",", ".");
    if (!/^\d{1,12}(\.\d{1,2})?$/.test(s)) return null;
    return deCentavos(centavos(s));
  }
  function moedaTxt(s) { return s ? deCentavos(centavos(s)).replace(".", ",") : ""; }
  var MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  var MESES_L = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  function rotuloMes(ym) { return MESES_L[+ym.slice(5, 7) - 1] + " de " + ym.slice(0, 4); }
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2) + "-" + Math.random().toString(36).slice(2);
  }

  /* ============ API ============ */
  var CHAVE = "caixa-factory-sessao";
  var sessao = null;
  try { sessao = JSON.parse(localStorage.getItem(CHAVE) || "null"); } catch (e) { sessao = null; }
  if (sessao && sessao.expira_em && new Date(sessao.expira_em) < new Date()) sessao = null;

  function guardarSessao(s) {
    sessao = s;
    try { s ? localStorage.setItem(CHAVE, JSON.stringify(s)) : localStorage.removeItem(CHAVE); } catch (e) {}
  }

  function api(metodo, caminho, corpo, opts) {
    opts = opts || {};
    var h = { "Accept": "application/json" };
    if (sessao) h["Authorization"] = "Bearer " + sessao.token;
    if (opts.idem) h["Idempotency-Key"] = opts.idem;
    var init = { method: metodo, headers: h };
    if (corpo instanceof FormData) init.body = corpo;
    else if (corpo !== undefined) { h["Content-Type"] = "application/json"; init.body = JSON.stringify(corpo); }
    return fetch("/api/v1" + caminho, init).then(function (r) {
      if (r.status === 401 && caminho.indexOf("/auth/") !== 0) { guardarSessao(null); telaEntrar("Sua sessão expirou. Entre de novo."); }
      if (opts.blob) return r.ok ? r.blob() : r.json().then(function (j) { throw erroDe(j, r.status); });
      if (r.status === 204) return null;
      return r.json().then(function (j) { if (!r.ok) throw erroDe(j, r.status); return j; },
                          function () { if (!r.ok) throw { status: r.status, mensagem: "O servidor não respondeu direito (" + r.status + ")." }; return null; });
    }, function () { throw { rede: true, mensagem: "Sem conexão com o servidor. Confira a internet e tente de novo." }; });
  }
  function erroDe(j, status) {
    var e = (j && j.erro) || {};
    return { status: status, codigo: e.codigo, mensagem: e.mensagem || "Erro " + status, detalhe: e.detalhe };
  }

  /* ============ estado ============ */
  var d = {};                     // tudo que veio do servidor
  var filtro = { status: "todas", q: "" };
  var mesSel = null;
  var salvamento = { tipo: "ok", texto: "Tudo salvo" };
  var app = document.getElementById("app");
  var modalRoot = document.createElement("div");
  document.body.appendChild(modalRoot);

  function leitura() { return !d.eu || d.eu.papel === "leitura"; }

  function carregar() {
    return Promise.all([
      api("GET", "/auth/eu"), api("GET", "/resumo"), api("GET", "/resultado-mensal"),
      api("GET", "/agenda?dias=3650"), api("GET", "/operacoes?por_pagina=200"), api("GET", "/movimentos"),
      api("GET", "/fornecedores?inativos=true"), api("GET", "/robo/rascunhos")
    ]).then(function (r) {
      d = { eu: r[0], resumo: r[1], meses: r[2].meses, agenda: r[3], ops: r[4].itens, movs: r[5].itens,
            forns: r[6].itens, rascunhos: r[7].itens };
    });
  }

  function status(tipo, texto) {
    salvamento = { tipo: tipo, texto: texto };
    var el = document.getElementById("status-chip");
    if (el) { el.className = "status s-" + tipo; el.textContent = texto; }
  }

  /* Grava e recarrega tudo. Erro de regra (422/409) volta para o formulário;
     erro de rede marca "Falha ao salvar". */
  function gravar(promessa) {
    status("busy", "Salvando…");
    return promessa.then(function (res) {
      return carregar().then(function () { status("ok", "Tudo salvo"); rota(); return res; });
    }, function (e) {
      status(e.rede || (e.status >= 500) ? "bad" : "ok", e.rede || (e.status >= 500) ? "Falha ao salvar" : "Tudo salvo");
      throw e;
    });
  }

  /* ============ rotas ============ */
  function rota() {
    if (!sessao) return telaEntrar();
    var h = location.hash.replace(/^#\/?/, "");
    if (h === "fornecedores") return telaFornecedores();
    if (h === "historico") return telaHistorico();
    return telaPainel();
  }
  window.addEventListener("hashchange", function () { fecharModal(); rota(); });

  function faixa(atual) {
    var acoes = leitura() || atual !== "painel" ? "" :
      '<button class="btn btn-ghost" data-act="enviar-docs">Enviar documentos</button>'
      + '<button class="btn btn-ghost" data-act="mov" data-tipo="aporte">Aporte</button>'
      + '<button class="btn btn-ghost" data-act="mov" data-tipo="retirada">Retirada</button>'
      + '<button class="btn btn-primary" data-act="nova-op">Nova operação</button>';
    function link(id, href, rot) {
      return '<a href="' + href + '"' + (atual === id ? ' aria-current="page"' : "") + '>' + rot + '</a>';
    }
    return '<header class="band"><div class="band-in">'
      + '<div class="brand"><div class="brand-mark">CF</div><div>'
      + '<h1>Caixa Factory</h1>'
      + '<p>Capital próprio aplicado nas compras da Machado Embalagens</p></div></div>'
      + '<nav class="nav" aria-label="Telas">' + link("painel", "#/", "Painel") + link("fornecedores", "#/fornecedores", "Fornecedores")
      + link("historico", "#/historico", "Histórico") + '<a href="#" data-act="sair">Sair</a></nav>'
      + '<div class="band-actions">'
      + '<span class="status s-' + salvamento.tipo + '" id="status-chip" role="status">' + esc(salvamento.texto) + '</span>'
      + acoes + '</div></div></header>';
  }

  /* ============ login ============ */
  function telaEntrar(msg) {
    fecharModal();
    app.innerHTML = '<div class="entrar"><form id="f-entrar" novalidate>'
      + '<div class="brand"><div class="brand-mark">CF</div><div><h1>Caixa Factory</h1><p>Entre para ver o caixa</p></div></div>'
      + (msg ? '<div class="erro" role="alert">' + esc(msg) + '</div>' : "")
      + '<div class="campo"><label for="e-email">E-mail</label><input type="email" id="e-email" autocomplete="username" required></div>'
      + '<div class="campo"><label for="e-senha">Senha</label><input type="password" id="e-senha" autocomplete="current-password" required></div>'
      + '<button class="btn btn-primary" type="submit">Entrar</button></form></div>';
    var f = document.getElementById("f-entrar");
    document.getElementById("e-email").focus();
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var bt = f.querySelector("button"); bt.disabled = true;
      api("POST", "/auth/entrar", { email: document.getElementById("e-email").value, senha: document.getElementById("e-senha").value })
        .then(function (s) { guardarSessao({ token: s.token, expira_em: s.expira_em }); return carregar(); })
        .then(rota, function (e) { telaEntrar(e.mensagem); });
    });
  }

  /* ============ painel ============ */
  function telaPainel() {
    var c = d.resumo;
    var cx = centavos(c.caixa), ap = centavos(c.aplicado), cap = centavos(c.capital);
    var pCaixa = cap > 0 ? Math.max(0, Math.min(100, cx / cap * 100)) : (cx > 0 ? 100 : 0);
    var pAplic = cap > 0 ? Math.max(0, Math.min(100, ap / cap * 100)) : 0;
    var rentReal = taxaRealizada();

    app.innerHTML = faixa("painel")
      + '<div class="wrap">'
      + '<section class="kpis">'
      + '<article class="kpi lead"><p class="eyebrow">Caixa disponível</p>'
      + '<p class="num ' + (cx < 0 ? "neg" : "") + '">' + R(c.caixa) + '</p>'
      + '<p class="sub">livre para novas compras</p>'
      + '<div class="barra" aria-hidden="true"><i class="f-caixa" style="width:' + pCaixa + '%"></i><i class="f-aplic" style="width:' + pAplic + '%"></i></div>'
      + '<div class="legenda">'
      + '<span><i style="background:#1D5FA3"></i>Caixa ' + R(c.caixa) + '</span>'
      + '<span><i style="background:var(--warn)"></i>Na rua ' + R(c.aplicado) + '</span>'
      + '<span>Capital total <b>' + R(c.capital) + '</b></span>'
      + '</div></article>'
      + '<article class="kpi"><p class="eyebrow">A receber da empresa</p>'
      + '<p class="num">' + R(c.a_receber) + '</p>'
      + '<p class="sub">' + c.duplicatas_abertas + ' ' + (c.duplicatas_abertas === 1 ? "parcela em aberto" : "parcelas em aberto")
      + (c.operacoes_abertas ? ' · ' + c.operacoes_abertas + (c.operacoes_abertas === 1 ? " operação" : " operações") : "") + '</p></article>'
      + '<article class="kpi"><p class="eyebrow">Lucro realizado</p>'
      + '<p class="num pos">' + R(c.lucro_realizado) + '</p>'
      + '<p class="sub">' + (rentReal > 0 ? "média de " + pctF(rentReal, 1) + " sobre o valor pago" : "nada recebido ainda") + '</p></article>'
      + '<article class="kpi"><p class="eyebrow">Lucro a receber</p>'
      + '<p class="num">' + R(c.lucro_a_receber) + '</p>'
      + '<p class="sub">desconto embutido no que ainda está na rua</p></article>'
      + '</section>'
      + rentabHTML() + mesHTML() + conferirHTML() + agendaHTML()
      + '<section class="card"><div class="card-head">'
      + '<h2>Operações<span class="conta" id="conta-ops"></span></h2>'
      + '<div class="tools">'
      + '<div class="seg" role="group" aria-label="Filtrar operações">'
      + ["todas", "em aberto", "recebidas"].map(function (f) {
          return '<button data-act="filtro" data-f="' + f + '" aria-pressed="' + (filtro.status === f) + '">'
            + f.charAt(0).toUpperCase() + f.slice(1) + '</button>';
        }).join("")
      + '</div>'
      + '<input type="search" id="busca" class="busca" placeholder="Fornecedor ou NF" value="' + esc(filtro.q) + '" aria-label="Buscar operações">'
      + '<button class="btn btn-quiet btn-sm" data-act="exp" data-arq="operacoes.csv">Exportar CSV</button>'
      + '</div></div>'
      + '<div class="tw"><table class="t-ops"><thead><tr>'
      + '<th scope="col">Compra</th><th scope="col">Fornecedor</th><th scope="col" class="r">Valor cheio</th><th scope="col" class="r">Paguei</th>'
      + '<th scope="col" class="r">Lucro</th><th scope="col">Retorno em duplicatas</th><th scope="col"><span class="sr">Ações</span></th>'
      + '</tr></thead><tbody id="ops-body"></tbody></table></div></section>'
      + '<section class="card"><div class="card-head">'
      + '<h2>Aportes e retiradas</h2>'
      + '<div class="tools"><button class="btn btn-quiet btn-sm" data-act="exp" data-arq="movimentos.csv">Exportar CSV</button></div>'
      + '</div><div class="tw"><table><thead><tr>'
      + '<th scope="col">Data</th><th scope="col">Tipo</th><th scope="col" class="r">Valor</th><th scope="col">Observação</th><th scope="col"></th>'
      + '</tr></thead><tbody id="mov-body"></tbody></table></div></section>'
      + notaHTML()
      + '</div>';
    renderOps();
    renderMovs();
  }

  /* "média de X% sobre o valor pago" do lucro já realizado */
  function taxaRealizada() {
    var lucro = 0, custo = 0;
    d.ops.forEach(function (o) {
      var rec = centavos(o.recebido), face = centavos(o.valor_cheio), pg = centavos(o.valor_pago);
      if (rec <= 0 || face <= 0) return;
      var cr = pg * rec / face;
      custo += cr; lucro += rec - cr;
    });
    return custo > 0 ? lucro / custo : 0;
  }

  function rentabHTML() {
    var r = d.resumo.rentabilidade;
    if (!d.ops.length || !r.prazo_medio_dias) return "";
    var dias = Math.round(Number(r.prazo_medio_dias));
    var lucroTotal = d.ops.reduce(function (s, o) { return s + centavos(o.lucro); }, 0);
    return '<section class="card"><div class="card-head"><h2>Rentabilidade do dinheiro'
      + '<span class="conta">média de ' + d.ops.length + (d.ops.length === 1 ? " operação" : " operações") + '</span></h2></div>'
      + '<div class="stats">'
      + '<div class="stat"><p class="eyebrow">Retorno sobre o que você paga</p>'
      + '<p class="num big">' + pct(r.taxa_mes) + ' <small>ao mês</small></p>'
      + '<p class="sub">' + pct(r.retorno) + ' em ' + dias + ' dias · equivale a ' + pct(r.taxa_ano, 1) + ' ao ano</p></div>'
      + '<div class="stat"><p class="eyebrow">Lucro por mês</p>'
      + '<p class="num big pos">' + R(r.lucro_mes_reais) + '</p>'
      + '<p class="sub">' + Rc(lucroTotal) + ' no total, fechando o mês em 30 dias</p></div>'
      + '<div class="stat"><p class="eyebrow">Capital em uso</p>'
      + '<p class="num big">' + pct(r.ocupacao, 1) + '</p>'
      + '<p class="sub">o restante fica parado no caixa, sem render</p></div>'
      + '<div class="stat destaque"><p class="eyebrow">Rendimento do caixa inteiro</p>'
      + '<p class="num big">' + pct(r.rendimento_caixa_inteiro) + ' <small>ao mês</small></p>'
      + '<p class="sub">taxa das operações aplicada só sobre o que está girando</p></div>'
      + '</div></section>';
  }

  function mesHTML() {
    var meses = d.meses;
    if (!meses.length) return "";
    var lista = meses.map(function (m) { return m.mes; });
    if (!mesSel || lista.indexOf(mesSel) < 0) mesSel = lista.indexOf(hoje().slice(0, 7)) >= 0 ? hoje().slice(0, 7) : lista[lista.length - 1];
    var i = lista.indexOf(mesSel), r = meses[i];
    var pico = Math.max.apply(null, meses.map(function (m) { return centavos(m.lucro); }).concat([1]));
    var aberto = r.estado !== "fechado";
    return '<section class="card"><div class="card-head">'
      + '<h2>Resultado por mês'
      + (aberto ? '<span class="chip c-parc" style="margin-left:8px">' + (r.estado === "projecao" ? "projeção" : "mês em curso") + '</span>' : "")
      + '<span class="conta">apropriado dia a dia, conforme o dinheiro fica na rua</span></h2>'
      + '<div class="tools">'
      + '<button class="btn btn-quiet btn-sm" data-act="mes-nav" data-d="-1"' + (i <= 0 ? " disabled" : "") + ' aria-label="Mês anterior">‹</button>'
      + '<select id="mes-sel" aria-label="Escolher o mês">'
      + lista.map(function (m) { return '<option value="' + m + '"' + (m === mesSel ? " selected" : "") + '>' + rotuloMes(m) + '</option>'; }).join("")
      + '</select>'
      + '<button class="btn btn-quiet btn-sm" data-act="mes-nav" data-d="1"' + (i >= lista.length - 1 ? " disabled" : "") + ' aria-label="Próximo mês">›</button>'
      + '</div></div>'
      + '<div class="barras" role="group" aria-label="Lucro por mês">'
      + meses.map(function (m) {
          var h = Math.max(2, Math.round(centavos(m.lucro) / pico * 100));
          return '<button type="button" class="col' + (m.mes === mesSel ? " sel" : "") + '" data-act="mes" data-m="' + m.mes + '"'
            + ' aria-pressed="' + (m.mes === mesSel) + '" aria-label="' + rotuloMes(m.mes) + ': ' + R(m.lucro) + '">'
            + '<span class="valor">' + R(m.lucro) + '</span>'
            + '<span class="trilho"><i style="height:' + h + '%"></i></span>'
            + '<span class="rot">' + MESES[+m.mes.slice(5, 7) - 1] + '</span></button>';
        }).join("")
      + '</div>'
      + '<div class="stats">'
      + '<div class="stat"><p class="eyebrow">Lucro do mês</p><p class="num big pos">' + R(r.lucro) + '</p>'
      + '<p class="sub">' + pct(r.taxa_mes) + ' ao mês sobre o dinheiro aplicado</p></div>'
      + '<div class="stat"><p class="eyebrow">Aplicado no mês</p><p class="num big">' + R(r.aplicado_medio) + '</p>'
      + '<p class="sub">média diária · ' + pct(r.ocupacao, 1) + ' do capital</p></div>'
      + '<div class="stat"><p class="eyebrow">Ficou parado</p><p class="num big">' + R(r.parado_medio) + '</p>'
      + '<p class="sub">média diária de ' + r.dias + ' dias, sem render nada</p></div>'
      + '<div class="stat destaque"><p class="eyebrow">Deixou de ganhar</p><p class="num big perdeu">' + R(r.custo_do_parado) + '</p>'
      + '<p class="sub">se o parado tivesse girado na taxa do mês</p></div>'
      + '</div>'
      + '<p class="mes-nota">Em ' + esc(rotuloMes(r.mes)) + ' o capital rendeu <b>' + pct(r.taxa_sobre_total) + ' ao mês</b> '
      + 'olhando o bolo inteiro, contra <b>' + pct(r.taxa_mes) + '</b> só sobre a parte que estava girando. '
      + 'O lucro de cada compra é distribuído pelos dias entre o pagamento ao fornecedor e o vencimento da duplicata, '
      + 'então um mês só recebe a fatia que correu dentro dele.'
      + (aberto ? ' <b>Este mês ainda não fechou</b> — os números contam as duplicatas já contratadas e mudam a cada compra nova.' : "")
      + '</p></section>';
  }

  /* ---- A conferir: rascunhos do robô (some inteiro quando a lista esvazia) ---- */
  function conferirHTML() {
    var lista = d.rascunhos;
    if (!lista.length) return "";
    return '<section class="card pend-card"><div class="card-head">'
      + '<h2>A conferir<span class="conta">' + lista.length + (lista.length === 1 ? " rascunho do robô" : " rascunhos do robô") + '</span></h2></div>'
      + lista.map(function (r) {
          var x = r.dados, p = r.previa, ro = leitura();
          var c1 = r.pendencias.filter(function (q) { return q.codigo === "C1"; })[0];
          var acoes = ro ? "" : '<div class="pend-acoes">'
            + (c1 ? '<button class="btn btn-quiet btn-sm" data-act="r-cheio" data-id="' + r.id + '" data-v="' + c1.soma_itens + '">Usar itens ' + R(c1.soma_itens) + '</button>'
                  + '<button class="btn btn-quiet btn-sm" data-act="r-cheio" data-id="' + r.id + '" data-v="' + c1.total_pedido + '">Usar total ' + R(c1.total_pedido) + '</button>' : "")
            + r.pendencias.filter(function (q) { return q.codigo === "ambiguo"; }).map(function (q) {
                return '<button class="btn btn-quiet btn-sm" data-act="r-juntar" data-id="' + r.id + '" data-com="' + q.rascunho_id + '">Juntar com o rascunho ' + q.rascunho_id + '</button>';
              }).join("")
            + '<button class="btn btn-quiet btn-sm" data-act="r-corrigir" data-id="' + r.id + '">Corrigir e aprovar</button>'
            + (r.pode_aprovar ? '<button class="btn btn-primary btn-sm" data-act="r-aprovar" data-id="' + r.id + '">Aprovar</button>' : "")
            + '<button class="btn btn-danger btn-sm" data-act="r-descartar" data-id="' + r.id + '">Descartar</button></div>';
          return '<div class="pend">'
            + '<div class="pend-top"><span class="forn">' + esc(r.fornecedor ? r.fornecedor.nome : "Fornecedor a identificar") + '</span>'
            + '<span class="doc">Rascunho ' + r.id + (x.numero_pedido ? ' · ' + esc(x.numero_pedido) : "") + (x.numero_nf ? ' · NFe ' + esc(x.numero_nf) : "")
            + (x.data_pagamento ? ' · PIX em ' + dbr(x.data_pagamento) : "") + '</span></div>'
            + '<div class="pend-linha">'
            + '<span><b class="eyebrow">Valor cheio</b><span class="num">' + (x.valor_cheio ? R(x.valor_cheio) : '<span class="falta">a informar</span>') + '</span></span>'
            + '<span><b class="eyebrow">Você pagou</b><span class="num">' + (x.valor_pago ? R(x.valor_pago) : '<span class="falta">a informar</span>') + '</span></span>'
            + (p ? '<span><b class="eyebrow">Lucro</b><span class="num certo">' + R(p.lucro) + '</span></span>'
                 + '<span><b class="eyebrow">Retorno</b><span class="num">' + pct(p.retorno) + ' · ' + pct(p.taxa_mes) + ' a.m.</span></span>' : "")
            + (x.duplicatas && x.duplicatas.length ? '<span><b class="eyebrow">Duplicatas</b><span class="num">'
                 + x.duplicatas.map(function (q) { return dcurto(q.vencimento) + " " + R(q.valor); }).join(" · ") + '</span></span>' : "")
            + '</div>'
            + (r.pendencias.length ? '<ul>' + r.pendencias.map(function (q) {
                return '<li' + (q.nivel === "erro" ? ' class="erro-p"' : "") + '>' + esc(q.mensagem) + '</li>'; }).join("") + '</ul>' : "")
            + (r.fornecedor && r.fornecedor.observacoes ? '<p class="pend-nota">' + esc(r.fornecedor.observacoes) + '</p>' : "")
            + docsHTML(r.documentos) + acoes + '</div>';
        }).join("")
      + '</section>';
  }

  function docsHTML(docs) {
    if (!docs || !docs.length) return "";
    return '<div class="docs">' + docs.map(function (x) {
      var rot = x.tipo === "pedido_compra" ? "pedido" : x.tipo === "comprovante_pix" ? "PIX" : x.tipo === "nota_fiscal" ? "NF" : "arquivo";
      return '<button type="button" class="doclink" data-act="doc" data-id="' + x.id + '" title="' + esc(x.nome_arquivo) + '">' + rot + '</button>';
    }).join("") + '</div>';
  }

  function agendaHTML() {
    var todas = d.agenda.duplicatas, lista = todas.slice(0, 6);
    if (!lista.length) return "";
    return '<section class="card"><div class="card-head"><h2>Próximos retornos'
      + '<span class="conta">' + todas.length + (todas.length === 1 ? " duplicata em aberto" : " duplicatas em aberto") + ' · ' + R(d.agenda.total) + '</span></h2></div>'
      + '<div class="agenda">'
      + lista.map(function (it) {
          return '<div class="ag-item">'
            + '<span class="ag-data" style="' + (it.atrasada ? "color:var(--bad)" : "") + '">' + dbr(it.vencimento) + '</span>'
            + '<span class="ag-quem">' + esc(it.fornecedor) + ' · ' + esc(it.numero_pedido) + ' · ' + it.sequencia + 'ª de ' + it.de + '</span>'
            + (it.atrasada ? '<span class="chip c-late">Atrasada</span>' : "")
            + '<span class="ag-val">' + R(it.valor) + '</span></div>';
        }).join("")
      + '</div></section>';
  }

  function chipEstado(o) {
    if (o.estado === "encerrada") return '<span class="chip c-ok">Encerrada</span>';
    if (o.estado === "parcial") return '<span class="chip c-parc">Parcial</span>';
    if (o.estado === "atrasada") return '<span class="chip c-late">Atrasada</span>';
    return '<span class="chip c-pend">Em aberto</span>';
  }

  function parcelasHTML(o) {
    var n = o.duplicatas.length;
    return '<div class="parc">' + o.duplicatas.map(function (p) {
      var cls = p.recebida_em ? "paga" : (p.atrasada ? "atrasada" : "aberta");
      var rot = p.recebida_em ? ("recebida " + dcurto(p.recebida_em)) : dbr(p.vencimento);
      var aria = o.fornecedor.nome + ", " + p.sequencia + "ª de " + n + ", "
        + (p.recebida_em ? "recebida em " + dbr(p.recebida_em) : "vence " + dbr(p.vencimento)) + ", " + R(p.valor);
      var attrs = leitura() ? " disabled" : ' data-act="parcela" data-op="' + o.id + '" data-id="' + p.id + '"';
      return '<button type="button" class="pchip ' + cls + '"' + attrs + ' aria-label="' + esc(aria) + '">'
        + '<span class="pn">' + p.sequencia + '/' + n + '</span><span>' + rot + '</span>'
        + '<span class="pv">' + R(p.valor) + '</span></button>';
    }).join("") + '</div>';
  }

  function renderOps() {
    var body = document.getElementById("ops-body");
    if (!body) return;
    var q = filtro.q.trim().toLowerCase();
    var lista = d.ops.filter(function (o) {
      if (filtro.status === "em aberto" && o.estado === "encerrada") return false;
      if (filtro.status === "recebidas" && o.estado !== "encerrada") return false;
      if (q) {
        var alvo = (o.fornecedor.nome + " " + o.numero_pedido + " " + (o.numero_nf || "") + " " + (o.observacoes || "")).toLowerCase();
        if (alvo.indexOf(q) < 0) return false;
      }
      return true;
    });
    var conta = document.getElementById("conta-ops");
    if (conta) conta.textContent = lista.length ? lista.length + (lista.length === 1 ? " registro" : " registros") : "";
    if (!lista.length) {
      body.innerHTML = '<tr><td colspan="7"><div class="vazio"><strong>'
        + (d.ops.length ? "Nenhuma operação neste filtro" : "Nenhuma operação registrada") + '</strong>'
        + (d.ops.length ? "Ajuste o filtro ou a busca." : "Clique em Nova operação para lançar a primeira compra com desconto.")
        + '</div></td></tr>';
      return;
    }
    body.innerHTML = lista.map(function (o) {
      var lucro = centavos(o.lucro);
      var doc = o.numero_pedido + (o.numero_nf ? " · NFe " + o.numero_nf : "");
      var bts = leitura() ? "" :
        '<button class="btn btn-quiet btn-sm" data-act="editar" data-id="' + o.id + '">Editar</button>'
        + '<button class="btn btn-danger btn-sm" data-act="excluir-op" data-id="' + o.id + '">' + (centavos(o.recebido) > 0 ? "Estornar" : "Excluir") + '</button>';
      return '<tr>'
        + '<td class="num" style="font-weight:500">' + dbr(o.data_pagamento) + '<div style="margin-top:6px">' + chipEstado(o) + '</div></td>'
        + '<td><div class="forn">' + esc(o.fornecedor.nome) + '</div><div class="doc">' + esc(doc) + '</div>'
        + (o.observacoes ? '<div class="doc">' + esc(o.observacoes) + '</div>' : "")
        + (o.origem === "robo" ? '<div class="doc">lançada pelo robô</div>' : "")
        + docsHTML(o.documentos) + '</td>'
        + '<td class="r"><span class="num">' + R(o.valor_cheio) + '</span></td>'
        + '<td class="r"><span class="num">' + R(o.valor_pago) + '</span></td>'
        + '<td class="r"><span class="num ' + (lucro < 0 ? "prejuizo" : "lucro") + '">' + R(o.lucro) + '</span>'
        + (o.lucro_mes_reais ? '<div class="mes' + (centavos(o.lucro_mes_reais) < 0 ? " neg" : "") + '">' + R(o.lucro_mes_reais) + ' <span>por mês</span></div>' : "")
        + '<div class="pct">' + pct(o.retorno) + ' sobre o que paguei' + (o.taxa_mes ? ' · ' + pct(o.taxa_mes) + ' a.m.' : "")
        + '<br><span style="opacity:.75">desconto de ' + pct(o.desconto) + ' no valor cheio</span></div></td>'
        + '<td>' + parcelasHTML(o) + '</td>'
        + '<td><div class="acoes">' + bts + '</div></td></tr>';
    }).join("");
  }

  function renderMovs() {
    var body = document.getElementById("mov-body");
    if (!body) return;
    if (!d.movs.length) {
      body.innerHTML = '<tr><td colspan="5"><div class="vazio"><strong>Nenhum aporte registrado</strong>Use Aporte para adicionar capital ao caixa.</div></td></tr>';
      return;
    }
    body.innerHTML = d.movs.map(function (m) {
      var ret = m.tipo === "retirada";
      return '<tr><td class="num" style="font-weight:500">' + dbr(m.data) + '</td>'
        + '<td><span class="chip ' + (ret ? "c-late" : "c-ok") + '">' + (ret ? "Retirada" : "Aporte") + '</span></td>'
        + '<td class="r"><span class="num">' + (ret ? "− " : "+ ") + R(m.valor) + '</span></td>'
        + '<td style="color:var(--ink-2)">' + esc(m.observacoes || "—") + '</td>'
        + '<td><div class="acoes">' + (leitura() ? "" : '<button class="btn btn-danger btn-sm" data-act="excluir-mov" data-id="' + m.id + '">Excluir</button>')
        + '</div></td></tr>';
    }).join("");
  }

  function notaHTML() {
    return '<p class="nota"><b>Como as contas são feitas.</b> Cada operação guarda o que você pagou à vista ao fornecedor '
      + 'e as <b>duplicatas</b> que a Machado te devolve. A diferença entre o total das duplicatas e o que você pagou é o seu lucro, '
      + 'reconhecido parcela a parcela conforme o dinheiro volta: cada duplicata devolve um pedaço do custo e um pedaço do lucro. '
      + '<b>Atenção aos dois percentuais:</b> o desconto do fornecedor é calculado sobre o valor cheio, mas o seu retorno é sobre o que '
      + 'saiu do seu bolso, que é menor — por isso um desconto de 3,00% rende 3,09% para você. Todas as taxas do sistema usam o retorno sobre o valor pago. '
      + 'Clique numa duplicata em aberto para marcar como recebida. O caixa disponível é: aportes − retiradas − tudo o que você já pagou '
      + '+ tudo o que já voltou. <b>A rentabilidade ao mês</b> converte o desconto para 30 dias usando o prazo médio das duplicatas, '
      + 'em juros compostos. O rendimento do caixa inteiro desconta a parte que está parada, porque dinheiro parado não rende. '
      + 'Os números vêm do servidor do Caixa Factory; tudo o que você grava fica registrado no histórico.</p>';
  }

  /* ============ fornecedores ============ */
  function telaFornecedores() {
    var linhas = d.forns.map(function (f) {
      return '<tr><td><div class="forn">' + esc(f.nome) + '</div>' + (f.ativo ? "" : '<span class="chip c-late">Inativo</span>') + '</td>'
        + '<td class="num" style="font-weight:500">' + esc(f.cnpj ? f.cnpj.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5") : "—") + '</td>'
        + '<td>' + esc(f.chave_pix || "—") + '</td>'
        + '<td class="r"><span class="num">' + (f.desconto_padrao ? pct(f.desconto_padrao) : "—") + '</span></td>'
        + '<td>' + esc(f.prazo_padrao || "—") + '</td>'
        + '<td style="color:var(--ink-2);max-width:40ch">' + esc(f.observacoes || "") + '</td>'
        + '<td><div class="acoes">' + (leitura() ? "" : '<button class="btn btn-quiet btn-sm" data-act="editar-forn" data-id="' + f.id + '">Editar</button>') + '</div></td></tr>';
    }).join("");
    app.innerHTML = faixa("fornecedores") + '<div class="wrap"><section class="card"><div class="card-head">'
      + '<h2>Fornecedores<span class="conta">' + d.forns.length + '</span></h2>'
      + '<div class="tools">' + (leitura() ? "" : '<button class="btn btn-quiet btn-sm" data-act="novo-forn">Novo fornecedor</button>') + '</div></div>'
      + '<div class="tw"><table><thead><tr><th scope="col">Nome</th><th scope="col">CNPJ</th><th scope="col">Chave PIX</th>'
      + '<th scope="col" class="r">Desconto padrão</th><th scope="col">Prazo</th><th scope="col">Observações (aparecem no lançamento)</th><th scope="col"></th></tr></thead>'
      + '<tbody>' + (linhas || '<tr><td colspan="7"><div class="vazio"><strong>Nenhum fornecedor</strong>Cadastre o primeiro em Novo fornecedor.</div></td></tr>') + '</tbody></table></div></section>'
      + '<p class="nota">O desconto padrão é só sugestão: a taxa do fornecedor muda sem aviso, e o valor que vale é sempre o dos documentos (A-05). '
      + 'As observações aparecem como aviso quando você lança uma compra desse fornecedor — é o lugar de anotar armadilhas como “lança o desconto na própria nota”.</p></div>';
  }

  /* ============ histórico ============ */
  var NOMES = { operacao: "Operação", duplicata: "Duplicata", movimento_caixa: "Movimento", fornecedor: "Fornecedor",
                documento: "Documento", usuario: "Usuário", rascunho: "Rascunho" };
  var hist = { itens: [], fim: false };
  function telaHistorico() {
    app.innerHTML = faixa("historico") + '<div class="wrap"><section class="card"><div class="card-head"><h2>Histórico'
      + '<span class="conta">tudo o que foi gravado, por quem e quando</span></h2></div>'
      + '<div class="tw"><table><thead><tr><th scope="col">Quando</th><th scope="col">Quem</th><th scope="col">O quê</th><th scope="col">Ação</th><th scope="col">Mudou</th></tr></thead>'
      + '<tbody id="hist-body"><tr><td colspan="5"><p class="carregando">Carregando…</p></td></tr></tbody></table></div>'
      + '<div class="mais" id="hist-mais" hidden><button class="btn btn-quiet btn-sm" data-act="hist-mais">Carregar mais</button></div></section></div>';
    hist = { itens: [], fim: false };
    maisHistorico();
  }
  function maisHistorico() {
    var ult = hist.itens.length ? hist.itens[hist.itens.length - 1].id : null;
    api("GET", "/eventos?limite=100" + (ult ? "&antes_de=" + ult : "")).then(function (r) {
      hist.itens = hist.itens.concat(r.itens);
      hist.fim = r.itens.length < 100;
      var body = document.getElementById("hist-body");
      if (!body) return;
      body.innerHTML = hist.itens.length ? hist.itens.map(function (e) {
        var em = new Date(e.em);
        return '<tr><td class="num" style="font-weight:500;white-space:nowrap">' + em.toLocaleDateString("pt-BR") + ' ' + em.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) + '</td>'
          + '<td>' + esc(e.usuario || "sistema") + '</td>'
          + '<td>' + esc((NOMES[e.entidade] || e.entidade) + " " + e.entidade_id) + '</td>'
          + '<td><span class="chip ' + ({ criou: "c-ok", excluiu: "c-late", estornou: "c-late", desfez: "c-pend", recebeu: "c-ok" }[e.acao] || "c-parc") + '">' + esc(e.acao) + '</span></td>'
          + '<td>' + diffHTML(e) + '</td></tr>';
      }).join("") : '<tr><td colspan="5"><div class="vazio"><strong>Nada registrado ainda</strong></div></td></tr>';
      document.getElementById("hist-mais").hidden = hist.fim;
    }, function (e) { var b = document.getElementById("hist-body"); if (b) b.innerHTML = '<tr><td colspan="5"><div class="erro">' + esc(e.mensagem) + '</div></td></tr>'; });
  }
  function diffHTML(e) {
    var ign = { atualizado_em: 1, criado_em: 1, id: 1 };
    var a = e.antes || {}, b = e.depois || {}, linhas = [];
    if (e.antes && e.depois) {
      Object.keys(b).forEach(function (k) {
        if (ign[k] || JSON.stringify(a[k]) === JSON.stringify(b[k])) return;
        linhas.push('<span>' + esc(k) + ': <code>' + esc(curto(a[k])) + '</code> → <code>' + esc(curto(b[k])) + '</code></span>');
      });
    } else {
      var x = e.depois || e.antes || {};
      ["numero_pedido", "nome", "tipo", "valor", "valor_pago", "valor_cheio", "vencimento", "data"].forEach(function (k) {
        if (x[k] != null) linhas.push('<span>' + esc(k) + ': <code>' + esc(curto(x[k])) + '</code></span>');
      });
    }
    return '<div class="diff">' + (linhas.slice(0, 6).join("") || "—") + '</div>';
  }
  function curto(v) { var s = v == null ? "vazio" : typeof v === "object" ? JSON.stringify(v) : String(v); return s.length > 60 ? s.slice(0, 57) + "…" : s; }

  /* ============ modais ============ */
  function fecharModal() { modalRoot.innerHTML = ""; modalRoot._salvar = null; }

  function abrirModal(titulo, corpo, rotulo, aoSalvar, perigo) {
    modalRoot.innerHTML =
      '<div class="overlay" data-overlay><div class="modal" role="dialog" aria-modal="true" aria-label="' + esc(titulo) + '">'
      + '<div class="modal-head"><h3>' + esc(titulo) + '</h3>'
      + '<button class="x" data-act="fechar" aria-label="Fechar">✕</button></div>'
      + '<div class="modal-body">' + corpo + '</div>'
      + '<div class="modal-foot"><button class="btn btn-ghost" data-act="fechar">Cancelar</button>'
      + '<button class="btn ' + (perigo ? "btn-danger" : "btn-primary") + '" data-act="confirmar">' + esc(rotulo) + '</button></div>'
      + '</div></div>';
    modalRoot._salvar = aoSalvar;
    var f = modalRoot.querySelector("input:not([disabled]),select,textarea");
    (f || modalRoot.querySelector("[data-act=confirmar]")).focus();
  }

  function erroModal(msg) {
    var body = modalRoot.querySelector(".modal-body");
    if (!body) return;
    var e = body.querySelector(".erro");
    if (!e) { e = document.createElement("div"); e.className = "erro"; e.setAttribute("role", "alert"); body.insertBefore(e, body.firstChild); }
    e.textContent = msg;
    body.scrollTop = 0;
  }

  /* trava o botão enquanto grava; erro volta para o formulário */
  function enviarModal(promessa) {
    var bt = modalRoot.querySelector("[data-act=confirmar]");
    if (bt) bt.disabled = true;
    return gravar(promessa).then(function (r) { fecharModal(); return r; }, function (e) {
      if (bt) bt.disabled = false;
      erroModal(e.mensagem);
    });
  }

  function val(id) { var el = document.getElementById(id); return el ? el.value : ""; }
  function campoData(id, rot, v) {
    return '<div class="campo"><label for="' + id + '">' + rot + '</label><input type="date" id="' + id + '" value="' + esc(v || "") + '"></div>';
  }
  function campoTexto(id, rot, v, ph, dica) {
    return '<div class="campo"><label for="' + id + '">' + rot + '</label>'
      + '<input type="text" id="' + id + '" value="' + esc(v || "") + '" placeholder="' + esc(ph || "") + '">'
      + (dica ? '<span class="dica">' + dica + '</span>' : "") + '</div>';
  }
  function campoValor(id, rot, v, dica) {
    return '<div class="campo"><label for="' + id + '">' + rot + '</label>'
      + '<input type="text" inputmode="decimal" id="' + id + '" value="' + esc(moedaTxt(v)) + '" placeholder="0,00">'
      + (dica ? '<span class="dica">' + dica + '</span>' : "") + '</div>';
  }
  function campoForn(id, atual) {
    var ativos = d.forns.filter(function (f) { return f.ativo || f.id === atual; });
    return '<div class="campo"><label for="' + id + '">Fornecedor</label><select id="' + id + '">'
      + '<option value="">Escolha…</option>'
      + ativos.map(function (f) { return '<option value="' + f.id + '"' + (f.id === atual ? " selected" : "") + '>' + esc(f.nome) + '</option>'; }).join("")
      + '</select><span class="dica">Falta algum? Cadastre em <a href="#/fornecedores">Fornecedores</a>.</span></div>';
  }

  /* ---- operação: nova, editar, ou corrigir rascunho do robô ---- */
  function modalOperacao(op, rasc) {
    var novo = !op;
    var base = op ? {
      fornecedor_id: op.fornecedor.id, numero_pedido: op.numero_pedido, numero_nf: op.numero_nf, data_pedido: op.data_pedido,
      data_pagamento: op.data_pagamento, valor_pago: op.valor_pago, valor_cheio: op.valor_cheio, observacoes: op.observacoes,
      duplicatas: op.duplicatas
    } : rasc ? rasc.dados : { data_pagamento: hoje(), duplicatas: null };
    var pz = (base.duplicatas && base.duplicatas.length)
      ? base.duplicatas.map(function (p) { return { id: p.id || null, v: p.valor, d: p.vencimento, r: p.recebida_em || "" }; })
      : [{ v: "", d: maisDias(hoje(), 30), r: "" }, { v: "", d: maisDias(hoje(), 40), r: "" }];
    var idem = uuid();          // a mesma chave em cada tentativa deste formulário

    var corpo =
      '<div class="grid2">' + campoData("f-data", "Data do PIX", base.data_pagamento) + campoForn("f-forn", base.fornecedor_id) + '</div>'
      + '<div id="f-aviso-forn"></div>'
      + '<div class="grid2">'
      + campoValor("f-cheio", "Valor cheio (R$)", base.valor_cheio, "total das duplicatas da Machado")
      + campoValor("f-pago", "Você pagou (R$)", base.valor_pago, "PIX à vista ao fornecedor") + '</div>'
      + '<div class="previa"><span class="rot">Seu lucro nesta operação</span><span class="val" id="f-previa">R$ 0,00</span></div>'
      + '<div class="bloco"><div class="bloco-top"><h4>Duplicatas — como a Machado te devolve</h4>'
      + '<div style="display:flex;gap:6px">'
      + '<button type="button" class="btn btn-quiet btn-sm" data-p-act="dividir">Dividir valor cheio</button>'
      + '<button type="button" class="btn btn-quiet btn-sm" data-p-act="add">+ duplicata</button></div></div>'
      + '<div id="parc-edit"></div><div class="soma" id="parc-soma"></div></div>'
      + '<div class="grid2">' + campoTexto("f-ped", "Pedido", base.numero_pedido, "Ex.: PC 03282-4/26")
      + campoTexto("f-nf", "NF", base.numero_nf, "Ex.: 12893") + '</div>'
      + '<div class="grid2">' + campoData("f-dped", "Data do pedido (opcional)", base.data_pedido)
      + campoTexto("f-obs", "Observações", base.observacoes, "opcional") + '</div>';

    var titulo = novo ? (rasc ? "Corrigir e aprovar o rascunho " + rasc.id : "Nova operação") : "Editar operação";
    var rotulo = novo ? (rasc ? "Aprovar e lançar" : "Lançar operação") : "Salvar alterações";
    abrirModal(titulo, corpo, rotulo, function () {
      lerParcelas();
      var forn = Number(val("f-forn")) || null, pago = entrada(val("f-pago")), cheioIn = entrada(val("f-cheio"));
      if (!forn) return erroModal("Informe o fornecedor.");
      if (!pago || centavos(pago) <= 0) return erroModal("Informe quanto você pagou ao fornecedor.");
      if (!pz.length) return erroModal("Cadastre pelo menos uma duplicata de retorno.");
      if (pz.some(function (p) { return !p.v || centavos(p.v) <= 0; })) return erroModal("Toda duplicata precisa de um valor.");
      if (pz.some(function (p) { return !p.d; })) return erroModal("Toda duplicata precisa de uma data de vencimento.");
      var soma = pz.reduce(function (s, p) { return s + centavos(p.v); }, 0);
      if (soma < centavos(pago)) return erroModal("As duplicatas somam " + Rc(soma) + ", menos do que você pagou (" + R(pago) + "). Nesse caso não há lucro.");
      if (cheioIn === null) return erroModal("Valor cheio inválido: use 1.234,56 ou 1234,56.");
      var cheio = cheioIn || deCentavos(soma);
      if (centavos(cheio) !== soma) return erroModal("As duplicatas somam " + Rc(soma) + " e o valor cheio é " + R(cheio) + ". Ajuste as duplicatas ou use Dividir valor cheio.");
      if (!val("f-ped").trim()) return erroModal("Informe o número do pedido (ex.: PC 03282-4/26).");
      var disp = centavos(d.resumo.caixa) + (op ? centavos(op.valor_pago) : 0);
      if ((novo || centavos(pago) > centavos(op.valor_pago)) && centavos(pago) > disp)
        return erroModal("Caixa insuficiente: você tem " + Rc(Math.max(0, disp)) + " livre. Registre um aporte antes de lançar esta compra.");
      var dados = {
        fornecedor_id: forn, numero_pedido: val("f-ped").trim(), numero_nf: val("f-nf").trim() || null,
        data_pedido: val("f-dped") || null, data_pagamento: val("f-data") || hoje(), valor_pago: pago, valor_cheio: cheio,
        observacoes: val("f-obs").trim() || null,
        duplicatas: pz.map(function (p) { var x = { valor: p.v, vencimento: p.d }; if (p.id) x.id = p.id; return x; })
      };
      if (rasc) {
        dados.duplicatas = dados.duplicatas.map(function (x) { return { valor: x.valor, vencimento: x.vencimento }; });
        return enviarModal(api("POST", "/robo/rascunhos/" + rasc.id + "/aprovar", dados, { idem: idem }));
      }
      if (novo) return enviarModal(api("POST", "/operacoes", dados, { idem: idem }));
      enviarModal(api("PATCH", "/operacoes/" + op.id, dados)).then(function (r) {
        if (r && r.avisos && r.avisos.length) abrirModal("Alteração salva", '<p class="nota-sec">' + r.avisos.map(esc).join("<br>") + '</p>', "Entendi", fecharModal);
      });
    });

    var editArea = document.getElementById("parc-edit");
    function lerParcelas() {
      Array.prototype.forEach.call(editArea.querySelectorAll("input"), function (el) {
        var i = Number(el.getAttribute("data-i"));
        if (!pz[i]) return;
        if (el.getAttribute("data-p") === "v") { var e = entrada(el.value); pz[i].v = e === null ? "" : e; }
        else pz[i].d = el.value;
      });
    }
    function renderParcelas() {
      editArea.innerHTML = pz.map(function (p, i) {
        var trava = p.r ? " disabled" : "";
        return '<div class="prow"><span class="pn" title="' + (p.r ? "recebida em " + dbr(p.r) : "") + '">' + (i + 1) + 'ª' + (p.r ? " ✓" : "") + '</span>'
          + '<input type="date" data-p="d" data-i="' + i + '" value="' + esc(p.d || "") + '" aria-label="Vencimento da ' + (i + 1) + 'ª duplicata">'
          + '<input type="text" inputmode="decimal" data-p="v" data-i="' + i + '" value="' + esc(moedaTxt(p.v)) + '" placeholder="0,00"' + trava
          + ' aria-label="Valor da ' + (i + 1) + 'ª duplicata' + (p.r ? ", já recebida" : "") + '">'
          + (pz.length > 1 && !p.r ? '<button type="button" class="x" data-p-act="rm" data-i="' + i + '" aria-label="Remover a ' + (i + 1) + 'ª duplicata">✕</button>' : '<span></span>')
          + '</div>';
      }).join("")
        + (pz.some(function (p) { return p.r; }) ? '<p class="dica">✓ = já recebida: o valor não muda; para mudar, desfaça o recebimento antes.</p>' : "");
      atualizaSoma();
    }
    function atualizaSoma() {
      var el = document.getElementById("parc-soma");
      var soma = pz.reduce(function (s, p) { return s + centavos(p.v); }, 0);
      var cheio = entrada(val("f-cheio"));
      var bate = !cheio || centavos(cheio) === soma;
      el.className = "soma" + (bate ? "" : " errado");
      el.innerHTML = '<span>Soma das duplicatas</span><b>' + Rc(soma) + (bate ? "" : " · valor cheio informado: " + R(cheio)) + '</b>';
      previa(soma);
    }
    function previa(soma) {
      var el = document.getElementById("f-previa"), pg = centavos(entrada(val("f-pago")) || "");
      var face = soma || centavos(entrada(val("f-cheio")) || "");
      if (pg <= 0 || face <= 0) { el.textContent = "R$ 0,00"; return; }
      el.innerHTML = Rc(face - pg) + "  ·  " + pctF((face - pg) / pg) + " sobre o que você paga"
        + '<span style="font-family:inherit;opacity:.7"> (desconto de ' + pctF((face - pg) / face) + ')</span>';
    }
    function avisoForn() {
      var f = d.forns.filter(function (x) { return x.id === Number(val("f-forn")); })[0];
      document.getElementById("f-aviso-forn").innerHTML = f && f.observacoes ? '<div class="aviso-forn"><b>' + esc(f.nome) + ':</b> ' + esc(f.observacoes) + '</div>' : "";
    }
    function dividir() {          // RN-01: partes iguais, a última absorve o arredondamento
      var cheio = entrada(val("f-cheio"));
      if (!cheio) return erroModal("Informe o valor cheio para dividir entre as duplicatas.");
      var livres = pz.filter(function (p) { return !p.r; });
      var resto = centavos(cheio) - pz.filter(function (p) { return p.r; }).reduce(function (s, p) { return s + centavos(p.v); }, 0);
      if (!livres.length || resto <= 0) return erroModal("Não há duplicata em aberto para dividir esse valor.");
      if (!pz.some(function (p) { return p.v; }) && pz.length === 2 && !op) {    // nascem em +30 e +40 da compra
        pz[0].d = maisDias(val("f-data") || hoje(), 30); pz[1].d = maisDias(val("f-data") || hoje(), 40);
      }
      var parte = Math.floor(resto / livres.length), acc = 0;
      livres.forEach(function (p, i) { var v = i === livres.length - 1 ? resto - acc : parte; p.v = deCentavos(v); acc += v; });
      renderParcelas();
    }
    var body = modalRoot.querySelector(".modal-body");
    body.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-p-act]") : null;
      if (!b) return;
      var a = b.getAttribute("data-p-act");
      lerParcelas();
      if (a === "add") { var ult = pz.length ? pz[pz.length - 1].d : val("f-data"); pz.push({ v: "", d: maisDias(ult || hoje(), 10), r: "" }); renderParcelas(); }
      if (a === "rm") { pz.splice(Number(b.getAttribute("data-i")), 1); renderParcelas(); }
      if (a === "dividir") dividir();
    });
    body.addEventListener("input", function (ev) {
      var t = ev.target;
      if (t.id === "f-cheio" || t.id === "f-pago") { atualizaSoma(); return; }
      if (t.hasAttribute && t.hasAttribute("data-p")) { lerParcelas(); atualizaSoma(); }
    });
    body.addEventListener("change", function (ev) { if (ev.target.id === "f-forn") avisoForn(); });
    renderParcelas();
    avisoForn();
  }

  /* ---- receber / desfazer uma duplicata ---- */
  function modalParcela(o, p) {
    var n = o.duplicatas.length;
    if (p.recebida_em) {
      return abrirModal("Desfazer recebimento",
        '<p style="font-size:13.5px;color:var(--ink-2);margin:0">A ' + p.sequencia + 'ª duplicata de <b>' + R(p.valor) + '</b> ('
        + esc(o.fornecedor.nome) + ') está marcada como recebida em ' + dbr(p.recebida_em) + '. Desfazer tira esse valor do caixa e o lucro realizado diminui.</p>',
        "Desfazer", function () { enviarModal(api("DELETE", "/duplicatas/" + p.id + "/receber")); }, true);
    }
    var idem = uuid();
    abrirModal("Registrar recebimento",
      '<p style="font-size:13.5px;color:var(--ink-2);margin:0">A Machado pagou a <b>' + p.sequencia + 'ª de ' + n + '</b> duplicatas da compra em <b>'
      + esc(o.fornecedor.nome) + '</b> (' + esc(o.numero_pedido) + '). Os <b>' + R(p.valor) + '</b> voltam para o caixa.</p>'
      + campoData("f-data", "Data do recebimento", p.vencimento <= hoje() ? p.vencimento : hoje()),
      "Confirmar recebimento", function () {
        enviarModal(api("POST", "/duplicatas/" + p.id + "/receber", { data: val("f-data") || hoje() }, { idem: idem }));
      });
  }

  function modalMovimento(tipo) {
    var ret = tipo === "retirada", idem = uuid();
    abrirModal(ret ? "Retirada do caixa" : "Aporte de capital",
      '<div class="grid2">' + campoData("f-data", "Data", hoje()) + campoValor("f-valor", (ret ? "Valor a retirar" : "Valor do aporte") + " (R$)", "") + '</div>'
      + campoTexto("f-obs", "Observação", "", ret ? "Ex.: retirada de lucro" : "Ex.: aporte extra para compra grande"),
      ret ? "Registrar retirada" : "Registrar aporte", function () {
        var v = entrada(val("f-valor"));
        if (!v || centavos(v) <= 0) return erroModal("Informe um valor válido, como 1.234,56.");
        if (ret && centavos(v) > centavos(d.resumo.caixa)) return erroModal("Você tem " + R(d.resumo.caixa) + " disponível em caixa. O dinheiro aplicado em duplicatas só pode sair depois que voltar.");
        enviarModal(api("POST", "/movimentos", { tipo: tipo, data: val("f-data") || hoje(), valor: v, observacoes: val("f-obs").trim() || null }, { idem: idem }));
      });
  }

  function modalFornecedor(f) {
    var novo = !f;
    f = f || { ativo: true };
    var desc = f.desconto_padrao ? (Number(f.desconto_padrao) * 100).toFixed(2).replace(".", ",") : "";
    abrirModal(novo ? "Novo fornecedor" : "Editar fornecedor",
      campoTexto("g-nome", "Nome", f.nome, "Ex.: SB Indústria e Comércio de Papel")
      + '<div class="grid2">' + campoTexto("g-cnpj", "CNPJ", f.cnpj, "00.000.000/0000-00") + campoTexto("g-pix", "Chave PIX", f.chave_pix, "opcional") + '</div>'
      + '<div class="grid2">' + campoTexto("g-desc", "Desconto padrão (%)", desc, "Ex.: 4,00", "só sugestão de preenchimento")
      + campoTexto("g-prazo", "Prazo padrão", f.prazo_padrao, "Ex.: 30/40") + '</div>'
      + '<div class="campo"><label for="g-obs">Observações</label><textarea id="g-obs" rows="3" placeholder="Armadilhas deste fornecedor: aparecem no lançamento">' + esc(f.observacoes || "") + '</textarea></div>'
      + (novo ? "" : '<label class="campo" style="flex-direction:row;gap:8px;align-items:center"><input type="checkbox" id="g-ativo"' + (f.ativo ? " checked" : "") + '> Ativo</label>'),
      novo ? "Cadastrar" : "Salvar", function () {
        var nome = val("g-nome").trim(); if (!nome) return erroModal("Informe o nome do fornecedor.");
        var p = entrada(val("g-desc"));
        if (p === null || (p && centavos(p) >= 10000)) return erroModal("Desconto padrão: use um percentual como 4,00.");
        var dados = { nome: nome, cnpj: val("g-cnpj").trim() || null, chave_pix: val("g-pix").trim() || null,
          desconto_padrao: p ? "0." + String(10000 + centavos(p)).slice(1) : null,          // 4,00% -> "0.0400"
          prazo_padrao: val("g-prazo").trim() || null, observacoes: val("g-obs").trim() || null };
        if (!novo) dados.ativo = document.getElementById("g-ativo").checked;
        enviarModal(novo ? api("POST", "/fornecedores", dados) : api("PATCH", "/fornecedores/" + f.id, dados));
      });
  }

  function modalConfirmar(titulo, texto, rotulo, fazer, comMotivo) {
    abrirModal(titulo, '<p style="font-size:13.5px;color:var(--ink-2);margin:0">' + texto + '</p>'
      + (comMotivo ? '<div class="campo"><label for="f-motivo">Motivo</label><input type="text" id="f-motivo" placeholder="Ex.: pedido cancelado pelo fornecedor"></div>' : ""),
      rotulo, function () {
        var m = comMotivo ? val("f-motivo").trim() : null;
        if (comMotivo === "obrigatorio" && (!m || m.length < 3)) return erroModal("Diga o motivo: ele fica no histórico.");
        enviarModal(fazer(m));
      }, true);
  }

  function modalEnviarDocs() {
    abrirModal("Enviar documentos",
      '<p style="font-size:13.5px;color:var(--ink-2);margin:0">Mande a tela do pedido de compra e o comprovante do PIX (foto ou PDF). '
      + 'O robô lê, junta os dois e monta um rascunho em <b>A conferir</b>. Nada é lançado sem a sua aprovação.</p>'
      + '<div class="envio"><input type="file" id="f-arqs" multiple accept="image/jpeg,image/png,image/webp,application/pdf" aria-label="Arquivos"></div>'
      + '<div id="f-res" class="nota-sec"></div>',
      "Enviar", function () {
        var arqs = document.getElementById("f-arqs").files;
        if (!arqs.length) return erroModal("Escolha pelo menos um arquivo.");
        var fd = new FormData();
        Array.prototype.forEach.call(arqs, function (a) { fd.append("arquivos", a); });
        var bt = modalRoot.querySelector("[data-act=confirmar]"); bt.disabled = true; bt.textContent = "Lendo…";
        gravar(api("POST", "/robo/ingestao", fd)).then(function (r) {
          var falhas = r.resultados.filter(function (x) { return !x.ok; });
          if (!falhas.length) return fecharModal();
          abrirModal("Alguns arquivos não entraram", '<ul class="nota-sec">' + falhas.map(function (x) {
            return '<li><b>' + esc(x.arquivo) + ':</b> ' + esc(x.erro.mensagem) + '</li>'; }).join("") + '</ul>', "Entendi", fecharModal);
        }, function (e) { bt.disabled = false; bt.textContent = "Enviar"; erroModal(e.mensagem); });
      });
  }

  /* abre o arquivo com o token (link simples não leva o Authorization) */
  function abrirDoc(id) {
    var janela = window.open("", "_blank");
    api("GET", "/documentos/" + id + "/arquivo", undefined, { blob: true }).then(function (b) {
      var url = URL.createObjectURL(b);
      if (janela) janela.location = url; else location.href = url;
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
    }, function (e) { if (janela) janela.close(); abrirModal("Documento", '<div class="erro">' + esc(e.mensagem) + '</div>', "Fechar", fecharModal); });
  }

  function exportar(arq) {
    api("GET", "/exportar/" + arq, undefined, { blob: true }).then(function (b) {
      var a = document.createElement("a"), url = URL.createObjectURL(b);
      a.href = url; a.download = "caixa-factory-" + arq; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
    }, function (e) { status("bad", "Falha ao exportar"); abrirModal("Exportar", '<div class="erro">' + esc(e.mensagem) + '</div>', "Fechar", fecharModal); });
  }

  /* ============ eventos ============ */
  function acharOp(id) { return d.ops.filter(function (o) { return o.id === Number(id); })[0]; }
  function acharRasc(id) { return d.rascunhos.filter(function (r) { return r.id === Number(id); })[0]; }

  document.addEventListener("click", function (ev) {
    var alvo = ev.target.closest ? ev.target.closest("[data-act]") : null;
    if (!alvo) {
      if (ev.target.hasAttribute && ev.target.hasAttribute("data-overlay")) fecharModal();
      return;
    }
    var act = alvo.getAttribute("data-act"), id = alvo.getAttribute("data-id");
    if (act === "sair") {
      ev.preventDefault();
      api("POST", "/auth/sair").then(null, function () {}).then(function () { guardarSessao(null); telaEntrar(); });
      return;
    }
    if (act === "nova-op") return modalOperacao(null);
    if (act === "editar") { var o = acharOp(id); if (o) modalOperacao(o); return; }
    if (act === "parcela") {
      var op = acharOp(alvo.getAttribute("data-op"));
      var p = op && op.duplicatas.filter(function (x) { return x.id === Number(id); })[0];
      if (p) modalParcela(op, p);
      return;
    }
    if (act === "excluir-op") {
      var o4 = acharOp(id);
      if (!o4) return;
      if (centavos(o4.recebido) > 0) {
        return modalConfirmar("Estornar operação", "A compra " + esc(o4.numero_pedido) + " (" + esc(o4.fornecedor.nome) + ") já tem duplicata recebida. "
          + "O estorno tira a operação de todos os cálculos — o caixa volta a não ter o PIX nem os recebimentos dela — mas ela fica no histórico.",
          "Estornar", function (m) { return api("POST", "/operacoes/" + o4.id + "/estorno", { motivo: m }); }, "obrigatorio");
      }
      return modalConfirmar("Excluir operação", "A compra " + esc(o4.numero_pedido) + " (" + esc(o4.fornecedor.nome) + ") em " + dbr(o4.data_pagamento)
        + " sai dos cálculos e o " + R(o4.valor_pago) + " volta para o caixa. Ela continua no histórico.",
        "Excluir", function (m) { return api("DELETE", "/operacoes/" + o4.id + (m ? "?motivo=" + encodeURIComponent(m) : "")); }, true);
    }
    if (act === "excluir-mov") {
      var m = d.movs.filter(function (x) { return x.id === Number(id); })[0];
      if (m) modalConfirmar("Excluir lançamento", (m.tipo === "retirada" ? "A retirada" : "O aporte") + " de " + R(m.valor) + " de " + dbr(m.data) + " será removido do caixa.",
        "Excluir", function () { return api("DELETE", "/movimentos/" + m.id); });
      return;
    }
    if (act === "mov") return modalMovimento(alvo.getAttribute("data-tipo"));
    if (act === "enviar-docs") return modalEnviarDocs();
    if (act === "doc") return abrirDoc(id);
    if (act === "exp") return exportar(alvo.getAttribute("data-arq"));
    if (act === "r-aprovar") {
      var ra = acharRasc(id);
      if (ra) modalConfirmar("Aprovar rascunho " + ra.id, "Lança a compra " + esc(ra.dados.numero_pedido || "") + ": você pagou " + R(ra.dados.valor_pago)
        + " e a Machado devolve " + R(ra.dados.valor_cheio) + (ra.previa ? " — lucro de " + R(ra.previa.lucro) : "") + ".",
        "Aprovar e lançar", function () { return api("POST", "/robo/rascunhos/" + ra.id + "/aprovar", undefined, { idem: uuid() }); });
      return;
    }
    if (act === "r-corrigir") { var rc = acharRasc(id); if (rc) modalOperacao(null, rc); return; }
    if (act === "r-cheio") { gravar(api("PATCH", "/robo/rascunhos/" + id, { valor_cheio: alvo.getAttribute("data-v") })).then(null, alerta); return; }
    if (act === "r-juntar") { gravar(api("POST", "/robo/rascunhos/" + id + "/juntar", { com: Number(alvo.getAttribute("data-com")) })).then(null, alerta); return; }
    if (act === "r-descartar") {
      modalConfirmar("Descartar rascunho " + id, "O rascunho sai da lista e nada é lançado. Os documentos continuam guardados.", "Descartar",
        function (mo) { return api("POST", "/robo/rascunhos/" + id + "/descartar", { motivo: mo || null }); }, true);
      return;
    }
    if (act === "novo-forn") return modalFornecedor(null);
    if (act === "editar-forn") { var f = d.forns.filter(function (x) { return x.id === Number(id); })[0]; if (f) modalFornecedor(f); return; }
    if (act === "hist-mais") return maisHistorico();
    if (act === "filtro") { filtro.status = alvo.getAttribute("data-f"); telaPainel(); return; }
    if (act === "mes") { mesSel = alvo.getAttribute("data-m"); telaPainel(); return; }
    if (act === "mes-nav") {
      var lista = d.meses.map(function (x) { return x.mes; }), j = lista.indexOf(mesSel) + Number(alvo.getAttribute("data-d"));
      if (j >= 0 && j < lista.length) { mesSel = lista[j]; telaPainel(); }
      return;
    }
    if (act === "fechar") return fecharModal();
    if (act === "confirmar") { if (modalRoot._salvar) modalRoot._salvar(); }
  });

  function alerta(e) { abrirModal("Não deu", '<div class="erro">' + esc(e.mensagem) + '</div>', "Fechar", fecharModal); }

  document.addEventListener("input", function (ev) {
    if (ev.target && ev.target.id === "busca") { filtro.q = ev.target.value; renderOps(); return; }   // sem perder o foco
    if (ev.target && ev.target.id === "mes-sel") { mesSel = ev.target.value; telaPainel(); }
  });

  document.addEventListener("keydown", function (ev) {
    if (!modalRoot.firstChild) return;
    if (ev.key === "Escape") fecharModal();
    if (ev.key === "Enter" && ev.target.tagName === "INPUT" && ev.target.type !== "file" && ev.target.type !== "checkbox") {
      ev.preventDefault();
      if (modalRoot._salvar) modalRoot._salvar();
    }
  });

  /* ============ início ============ */
  if (!sessao) telaEntrar();
  else carregar().then(rota, function (e) { if (sessao) app.innerHTML = '<div class="wrap"><div class="erro">' + esc(e.mensagem) + '</div></div>'; });
})();
