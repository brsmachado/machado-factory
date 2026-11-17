"""Rascunhos do robô (docs/06-robo.md, Robô 1).

Cada documento lido entra num rascunho. Pedido e comprovante chegam separados
(duas fotos), então um documento novo procura o rascunho pendente que está
esperando a outra metade e casa por valor, depois data, depois fornecedor
(A-04). Se sobrar ambiguidade, não escolhe: cria um rascunho próprio e lista os
candidatos para o dono juntar.

As conferências C1..C8 viram pendências. Nenhuma delas grava nada: o rascunho
só vira operação quando o dono aprova, e aí passa por todas as validações do
lançamento manual (operacoes.criar) — com origem = 'robo'.
"""
import re
import unicodedata
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from psycopg.types.json import Jsonb

from .. import fmt
from .. import operacoes as ops
from ..documentos import Arquivos, salvar
from ..erros import ErroAPI

TOL = Decimal("0.01")
CONFIANCA_MIN = 0.90
MOTIVO_JUNTADO = "Juntado ao rascunho {id}"

_PALAVRAS_VAZIAS = {"LTDA", "ME", "EPP", "EIRELI", "SA", "S", "A", "INDUSTRIA", "COMERCIO", "IND", "COM",
                    "DE", "DA", "DO", "DAS", "DOS", "E", "EM", "PAPEL", "PLASTICOS", "PLASTICO", "EMBALAGENS"}


# --- utilidades ------------------------------------------------------------

def _d(v) -> Optional[Decimal]:
    return Decimal(v) if v not in (None, "") else None


def _dt(v) -> Optional[date]:
    return date.fromisoformat(v) if v else None


def _palavras(nome: Optional[str]) -> list[str]:
    if not nome:
        return []
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().upper()
    return [p for p in re.split(r"[^A-Z0-9]+", s) if p and p not in _PALAVRAS_VAZIAS]


def _mesmo_fornecedor(nome_a, doc_a, nome_b, doc_b) -> Optional[bool]:
    """True/False quando dá para dizer; None quando falta informação."""
    da, db = re.sub(r"\D", "", doc_a or ""), re.sub(r"\D", "", doc_b or "")
    if len(da) == 14 and len(db) == 14:
        return da == db
    pa, pb = _palavras(nome_a), _palavras(nome_b)
    if not pa or not pb:
        return None
    return pa[0] in pb or pb[0] in pa


def dividir(valor: Decimal, n: int) -> list[Decimal]:
    """RN-01: partes iguais, a última absorve o arredondamento."""
    parte = (valor / n).quantize(TOL, rounding=ROUND_DOWN)
    return [parte] * (n - 1) + [valor - parte * (n - 1)]


def achar_fornecedor(cur, nome: Optional[str], cnpj: Optional[str]) -> Optional[int]:
    if cnpj:
        cur.execute("select id from fornecedor where cnpj = %s and ativo", (cnpj,))
        f = cur.fetchone()
        if f:
            return f["id"]
    if not nome:
        return None
    cur.execute("select id, nome, cnpj from fornecedor where ativo")
    achados = [f["id"] for f in cur.fetchall() if _mesmo_fornecedor(f["nome"], None, nome, None)]
    return achados[0] if len(achados) == 1 else None


# --- derivar dados e conferir ---------------------------------------------

CAMPOS_DADOS = ("fornecedor_id", "numero_pedido", "numero_nf", "data_pedido", "data_pagamento",
                "valor_pago", "valor_cheio", "duplicatas", "observacoes")


def derivar(cur, extraido: dict, correcoes: dict) -> dict:
    p = extraido.get("pedido") or {}
    c = extraido.get("comprovante") or {}
    dups = [d for d in p.get("duplicatas") or [] if d.get("valor") and d.get("vencimento")]
    # A-03: o valor cheio vem das duplicatas, não da quantidade pedida
    cheio = sum((Decimal(d["valor"]) for d in dups), Decimal(0)) if dups else _d(p.get("total_pedido"))
    obs = ["Lido pelo robô"]
    if p.get("condicao_pagamento"):
        obs.append(f"condição {p['condicao_pagamento']}")
    if c.get("id_transacao"):
        obs.append(f"PIX {c['id_transacao']}")
    dados = {
        "fornecedor_id": achar_fornecedor(cur, p.get("fornecedor_nome") or c.get("recebedor_nome"),
                                          p.get("fornecedor_cnpj")),
        "numero_pedido": p.get("numero_pedido"),
        "numero_nf": p.get("numero_nf"),
        "data_pedido": p.get("data_pedido"),
        "data_pagamento": c.get("data_pagamento"),     # RN-09: a data do PIX, não a do pedido
        "valor_pago": c.get("valor"),
        "valor_cheio": fmt.dinheiro(cheio) if cheio is not None else None,
        "duplicatas": [{"valor": d["valor"], "vencimento": d["vencimento"]} for d in dups],
        "observacoes": " · ".join(obs),
    }
    dados.update({k: v for k, v in correcoes.items() if k in CAMPOS_DADOS})
    return dados


def _pend(codigo: str, mensagem: str, nivel: str = "aviso", **extra) -> dict:
    return {"codigo": codigo, "nivel": nivel, "mensagem": mensagem, **extra}


def conferir(cur, dados: dict, extraido: dict, correcoes: dict) -> list[dict]:
    pend: list[dict] = []
    p, c = extraido.get("pedido"), extraido.get("comprovante")
    # a metade que falta pode ser digitada pelo dono (Corrigir e aprovar, na tela)
    if not p and not {"numero_pedido", "duplicatas"} <= correcoes.keys():
        pend.append(_pend("falta_pedido", "Falta o pedido de compra: mande a foto da tela do pedido", "erro"))
    if not c and not {"valor_pago", "data_pagamento"} <= correcoes.keys():
        pend.append(_pend("falta_comprovante", "Falta o comprovante do PIX: mande a foto ou o PDF", "erro"))
    for cand in extraido.get("_candidatos") or []:
        pend.append(_pend("ambiguo", f"Pode ser a outra metade do rascunho {cand}: se for, junte os dois",
                          "aviso", rascunho_id=cand))

    if not dados.get("fornecedor_id"):
        nome = (p or {}).get("fornecedor_nome") or (c or {}).get("recebedor_nome") or "(sem nome legível)"
        pend.append(_pend("fornecedor", f"Fornecedor não encontrado no cadastro: {nome}", "erro"))
    for campo, nome in (("numero_pedido", "número do pedido"), ("data_pagamento", "data do PIX"),
                        ("valor_pago", "valor pago"), ("valor_cheio", "valor cheio")):
        if (campo == "numero_pedido" and p or campo in ("data_pagamento", "valor_pago") and c
                or campo == "valor_cheio" and p) and not dados.get(campo):
            pend.append(_pend("ilegivel", f"Não consegui ler o {nome}", "erro", campo=campo))
    if p and not dados.get("duplicatas"):
        pend.append(_pend("ilegivel", "Não consegui ler as duplicatas", "erro", campo="duplicatas"))

    escolheu_cheio = "valor_cheio" in correcoes
    if p and not escolheu_cheio:
        itens = [i for i in p.get("itens") or [] if i.get("valor_total")]
        total = _d(p.get("total_pedido"))
        soma_itens = sum((Decimal(i["valor_total"]) for i in itens), Decimal(0)) if itens else None
        # C1 — a mais importante (A-01): quase custou R$ 398,00
        if soma_itens is not None and total is not None and abs(soma_itens - total) > TOL:
            pend.append(_pend(
                "C1",
                f"Os itens somam {fmt.brl(soma_itens)} mas o total do pedido saiu {fmt.brl(total)}. "
                "A SB lança o desconto na própria nota — o valor cheio correto costuma ser a soma dos "
                "itens. Confirme qual usar.",
                "erro", soma_itens=fmt.dinheiro(soma_itens), total_pedido=fmt.dinheiro(total)))
        # C2
        dups = [Decimal(d["valor"]) for d in p.get("duplicatas") or [] if d.get("valor")]
        if dups and total is not None and abs(sum(dups) - total) > TOL:
            pend.append(_pend("C2", f"As duplicatas somam {fmt.brl(sum(dups))} e o total do pedido é "
                                    f"{fmt.brl(total)}. Confirme o valor cheio."))
    # C3
    if p and c:
        igual = _mesmo_fornecedor(p.get("fornecedor_nome"), p.get("fornecedor_cnpj"),
                                  c.get("recebedor_nome"), c.get("recebedor_documento"))
        if igual is False:
            pend.append(_pend("C3", f"O PIX foi para {c.get('recebedor_nome') or '?'}, mas o pedido é de "
                                    f"{p.get('fornecedor_nome') or '?'}. Confira se é o comprovante certo."))

    pago, cheio = _d(dados.get("valor_pago")), _d(dados.get("valor_cheio"))
    pagamento = _dt(dados.get("data_pagamento"))
    # C4
    if pago is not None and cheio is not None and pago >= cheio:
        pend.append(_pend("C4", f"O valor pago ({fmt.brl(pago)}) não é menor que o valor cheio "
                                f"({fmt.brl(cheio)}): não há desconto. Confira os dois documentos.", "erro"))
    # C5 (A-02)
    if pagamento:
        for i, d in enumerate(dados.get("duplicatas") or [], 1):
            v = _dt(d["vencimento"])
            if v < pagamento or v > pagamento + timedelta(days=365):
                pend.append(_pend("C5", f"Duplicata {i}: vencimento {fmt.br_data(v)} fora da janela do "
                                        f"pagamento em {fmt.br_data(pagamento)} — quase sempre é o ano "
                                        "impresso errado (A-02). Corrija a data.", "erro", duplicata=i))
    # C6
    if pago and cheio and pago < cheio:
        retorno = (cheio - pago) / pago
        if not (Decimal("0.005") <= retorno <= Decimal("0.15")):
            pend.append(_pend("C6", f"Retorno de {fmt.br_decimal(retorno * 100)}% está fora do comum "
                                    "(0,5% a 15%). Confira os valores."))
    # C7
    if pago:
        cur.execute("select caixa.caixa_disponivel() as c")
        caixa = cur.fetchone()["c"]
        if pago > caixa:
            pend.append(_pend("C7", f"Falta aporte: o caixa tem {fmt.brl(max(caixa, Decimal(0)))} e o PIX foi "
                                    f"de {fmt.brl(pago)}. Registre o aporte antes de aprovar."))
    # C8
    if dados.get("numero_pedido"):
        cur.execute("select id from operacao where numero_pedido = %s and situacao <> 'estornada' "
                    "and (%s::bigint is null or fornecedor_id = %s)",
                    (dados["numero_pedido"], dados.get("fornecedor_id"), dados.get("fornecedor_id")))
        dup = cur.fetchone()
        if dup:
            pend.append(_pend("C8", f"O pedido {dados['numero_pedido']} já está lançado (operação "
                                    f"{dup['id']}): provável documento repetido.", "erro", operacao_id=dup["id"]))
    # confiança baixa e campos ilegíveis
    nomes = {"numero_pedido": "número do pedido", "total_pedido": "total do pedido",
             "duplicatas": "duplicatas", "valor_pago": "valor pago", "data_pagamento": "data do PIX"}
    for campo, conf in (extraido.get("_confianca") or {}).items():
        if conf is not None and conf < CONFIANCA_MIN and campo in nomes and campo not in correcoes:
            pend.append(_pend("confianca", f"Leitura duvidosa: {nomes[campo]}. Confira na imagem.", campo=campo))
    for campo in extraido.get("_ilegiveis") or []:
        raiz = campo.split(".")[0]
        if raiz in correcoes or (raiz == "total_pedido" and "valor_cheio" in correcoes):
            continue        # o dono já corrigiu
        pend.append(_pend("ilegivel", f"Não consegui ler: {campo}", campo=campo))
    return pend


def previa(dados: dict) -> Optional[dict]:
    """Quanto a operação vai render, para o dono decidir (mesmas fórmulas de 03-formulas §1)."""
    pago, cheio, pagamento = _d(dados.get("valor_pago")), _d(dados.get("valor_cheio")), _dt(dados.get("data_pagamento"))
    dups = dados.get("duplicatas") or []
    if not (pago and cheio and pagamento and dups) or pago > cheio:
        return None
    face = sum((Decimal(d["valor"]) for d in dups), Decimal(0))
    if not face:
        return None
    prazo = sum((Decimal(d["valor"]) * max((_dt(d["vencimento"]) - pagamento).days, 1) for d in dups),
                Decimal(0)) / face
    lucro = cheio - pago
    retorno = lucro / pago
    taxa_mes = (1 + retorno) ** (Decimal(30) / prazo) - 1 if prazo > 0 else Decimal(0)
    return {"lucro": fmt.dinheiro(lucro), "retorno": fmt.taxa(retorno), "desconto": fmt.taxa(lucro / cheio),
            "prazo_medio_dias": fmt.dias(prazo), "taxa_mes": fmt.taxa(taxa_mes),
            "lucro_mes_reais": fmt.dinheiro(pago * taxa_mes)}


# --- leitura ---------------------------------------------------------------

def _travar(cur, rid: int) -> dict:
    cur.execute("select * from rascunho where id = %s for update", (rid,))
    r = cur.fetchone()
    if not r:
        raise ErroAPI("nao_encontrado", f"Rascunho {rid} não existe")
    return r


def _pendente(r: dict) -> None:
    if r["estado"] != "pendente":
        raise ErroAPI("conflito", f"Rascunho {r['id']} já foi {r['estado']}")


def json_rascunho(cur, r: dict) -> dict:
    cur.execute("select id, tipo, nome_arquivo, data_doc from documento where rascunho_id = %s order by id", (r["id"],))
    docs = cur.fetchall()
    fornecedor = None
    if r["dados"].get("fornecedor_id"):
        cur.execute("select id, nome, observacoes from fornecedor where id = %s", (r["dados"]["fornecedor_id"],))
        fornecedor = cur.fetchone()
    pend = r["pendencias"]
    return {
        "id": r["id"], "estado": r["estado"], "operacao_id": r["operacao_id"],
        "dados": r["dados"],
        "fornecedor": {"id": fornecedor["id"], "nome": fornecedor["nome"],
                       "observacoes": fornecedor["observacoes"]} if fornecedor else None,
        "pendencias": pend,
        "pode_aprovar": r["estado"] == "pendente" and not any(x["nivel"] == "erro" for x in pend),
        "previa": previa(r["dados"]),
        "extraido": {k: v for k, v in r["extraido"].items() if not k.startswith("_")},
        "documentos": [{"id": d["id"], "tipo": d["tipo"], "nome_arquivo": d["nome_arquivo"],
                        "data_doc": fmt.data_iso(d["data_doc"])} for d in docs],
        "descarte_motivo": r["descarte_motivo"],
        "criado_em": r["criado_em"].isoformat(),
    }


def obter(cur, rid: int) -> dict:
    cur.execute("select * from rascunho where id = %s", (rid,))
    r = cur.fetchone()
    if not r:
        raise ErroAPI("nao_encontrado", f"Rascunho {rid} não existe")
    return json_rascunho(cur, r)


def listar(cur, estado: Optional[str] = "pendente") -> list[dict]:
    if estado:
        cur.execute("select * from rascunho where estado = %s order by id", (estado,))
    else:
        cur.execute("select * from rascunho order by id desc limit 200")
    return [json_rascunho(cur, r) for r in cur.fetchall()]


# --- escrita ---------------------------------------------------------------

def _gravar(cur, rid: int, extraido: dict, correcoes: dict) -> None:
    dados = derivar(cur, extraido, correcoes)
    pend = conferir(cur, dados, extraido, correcoes)
    cur.execute("update rascunho set extraido = %s, correcoes = %s, dados = %s, pendencias = %s, "
                "atualizado_em = now() where id = %s",
                (Jsonb(extraido), Jsonb(correcoes), Jsonb(dados), Jsonb(pend), rid))


def _compativel(pedido: dict, comprovante: dict) -> dict:
    """Notas de casamento entre um pedido e um comprovante (A-04)."""
    # O valor cheio pode estar em três lugares que nem sempre batem (A-01: a SB
    # imprime o total já com desconto, abaixo do próprio PIX). Para casar, vale
    # qualquer uma das leituras; quem decide qual é a certa é o C1, com o dono.
    dups = [Decimal(d["valor"]) for d in pedido.get("duplicatas") or [] if d.get("valor")]
    itens = [Decimal(i["valor_total"]) for i in pedido.get("itens") or [] if i.get("valor_total")]
    leituras = [v for v in (sum(dups) if dups else None, _d(pedido.get("total_pedido")),
                            sum(itens) if itens else None) if v]
    pago = _d(comprovante.get("valor"))
    dp, dc = _dt(pedido.get("data_pedido")), _dt(comprovante.get("data_pagamento"))
    return {
        # compatível = o PIX entre 85% e 100% do valor cheio
        "valor": None if not leituras or pago is None
        else min(leituras) * Decimal("0.85") <= pago <= max(leituras),
        "data": None if dp is None or dc is None else abs((dc - dp).days) <= 5,
        "fornecedor": _mesmo_fornecedor(pedido.get("fornecedor_nome"), pedido.get("fornecedor_cnpj"),
                                        comprovante.get("recebedor_nome"), comprovante.get("recebedor_documento")),
    }


def _casar(cur, tipo: str, lido: dict) -> tuple[Optional[int], list[int]]:
    """Rascunho pendente que espera a outra metade. (escolhido, candidatos_se_ambíguo)."""
    falta = "comprovante" if tipo == "comprovante_pix" else "pedido"
    tem = "pedido" if falta == "comprovante" else "comprovante"
    cur.execute(f"select id, extraido from rascunho where estado = 'pendente' "
                f"and extraido ? '{tem}' and not extraido ? '{falta}' order by id for update")
    cands = []
    for r in cur.fetchall():
        par = (r["extraido"][tem], lido) if tem == "pedido" else (lido, r["extraido"][tem])
        cands.append((r["id"], _compativel(*par)))
    if not cands:
        return None, []
    # 1. por valor  2. por data (±5 dias)  3. por fornecedor — sem chutar
    for criterio in ("valor", "data", "fornecedor"):
        if any(n[criterio] is False for _, n in cands):
            cands = [(i, n) for i, n in cands if n[criterio] is not False]
        decididos = [(i, n) for i, n in cands if n[criterio] is True]
        if len(decididos) == 1:
            return decididos[0][0], []
        if decididos:
            cands = decididos
    return (cands[0][0], []) if len(cands) == 1 and any(v for v in cands[0][1].values()) else \
        (None, [i for i, _ in cands])


def ja_recebido(cur, sha256: str) -> Optional[dict]:
    cur.execute("select id, rascunho_id, operacao_id, nome_arquivo from documento where sha256 = %s", (sha256,))
    return cur.fetchone()


def ingerir(cur, arqs: Arquivos, conteudo: bytes, lido: dict) -> dict:
    """Guarda o documento e põe no rascunho certo. Devolve {acao, documento_id, rascunho}."""
    tipo = lido["tipo_documento"]
    if tipo == "outro":
        novo, doc = salvar(cur, arqs, conteudo, "outro")
        return {"acao": "nao_reconhecido", "documento_id": doc["id"], "rascunho": None}

    metade = lido["pedido"] if tipo == "pedido_compra" else lido["comprovante"]
    chave = "pedido" if tipo == "pedido_compra" else "comprovante"
    data_doc = _dt(metade.get("data_pedido") if chave == "pedido" else metade.get("data_pagamento"))
    rid, candidatos = _casar(cur, tipo, metade)
    acao = "juntado" if rid else "criado"
    if rid is None:
        cur.execute("insert into rascunho default values returning id")
        rid = cur.fetchone()["id"]
    r = _travar(cur, rid)
    extraido = dict(r["extraido"])
    extraido[chave] = metade
    conf = dict(extraido.get("_confianca") or {})
    conf.update({k: v for k, v in lido.get("confianca", {}).items()
                 if k in (("numero_pedido", "total_pedido", "duplicatas") if chave == "pedido"
                          else ("valor_pago", "data_pagamento"))})
    extraido["_confianca"] = conf
    extraido["_ilegiveis"] = sorted(set(extraido.get("_ilegiveis") or []) | set(lido.get("ilegiveis") or []))
    if candidatos:
        extraido["_candidatos"] = candidatos

    numero = (extraido.get("pedido") or {}).get("numero_pedido")
    novo, doc = salvar(cur, arqs, conteudo, "pedido_compra" if chave == "pedido" else "comprovante_pix",
                       rascunho_id=rid, data_doc=data_doc, numero_pedido=numero)
    if not novo:
        raise ErroAPI("conflito", f"Este arquivo já foi recebido (documento {doc['id']})")
    _gravar(cur, rid, extraido, dict(r["correcoes"]))
    return {"acao": acao, "documento_id": doc["id"], "rascunho": obter(cur, rid)}


_RE_DINHEIRO = re.compile(r"^\d{1,12}(\.\d{1,2})?$")


def _validar_correcao(cur, campo: str, valor):
    if campo not in CAMPOS_DADOS:
        raise ErroAPI("validacao", f"Campo {campo} não pode ser corrigido", {"campo": campo})
    if valor is None:
        return None
    if campo in ("valor_pago", "valor_cheio"):
        if not isinstance(valor, str) or not _RE_DINHEIRO.match(valor):
            raise ErroAPI("validacao", f'{campo}: use texto com ponto decimal, ex.: "4107.84"', {"campo": campo})
        return fmt.dinheiro(Decimal(valor))
    if campo in ("data_pedido", "data_pagamento"):
        try:
            return date.fromisoformat(valor).isoformat()
        except (TypeError, ValueError):
            raise ErroAPI("validacao", f"{campo}: use AAAA-MM-DD", {"campo": campo}) from None
    if campo == "fornecedor_id":
        cur.execute("select id from fornecedor where id = %s and ativo", (valor,))
        if not cur.fetchone():
            raise ErroAPI("validacao", f"Fornecedor {valor} não existe ou está inativo", {"campo": campo})
        return int(valor)
    if campo == "duplicatas":
        if not isinstance(valor, list) or not valor:
            raise ErroAPI("validacao", "duplicatas: lista de {valor, vencimento}", {"campo": campo})
        return [{"valor": _validar_correcao(cur, "valor_cheio", d.get("valor")),
                 "vencimento": _validar_correcao(cur, "data_pagamento", d.get("vencimento"))} for d in valor]
    return str(valor).strip()[:2000] or None


def corrigir(cur, rid: int, mudancas: dict) -> dict:
    r = _travar(cur, rid)
    _pendente(r)
    corr = dict(r["correcoes"])
    for campo, valor in mudancas.items():
        corr[campo] = _validar_correcao(cur, campo, valor)
    # valor cheio novo sem duplicatas novas: redivide as duplicatas lidas (RN-01),
    # mantendo os vencimentos — é o caso da escolha no C1 (A-01)
    if "valor_cheio" in mudancas and "duplicatas" not in mudancas and corr.get("valor_cheio"):
        atuais = derivar(cur, r["extraido"], {k: v for k, v in corr.items() if k != "valor_cheio"})["duplicatas"]
        if atuais:
            partes = dividir(Decimal(corr["valor_cheio"]), len(atuais))
            corr["duplicatas"] = [{"valor": fmt.dinheiro(v), "vencimento": d["vencimento"]}
                                  for v, d in zip(partes, atuais)]
    if "duplicatas" in mudancas and "valor_cheio" not in mudancas and corr.get("duplicatas"):
        corr["valor_cheio"] = fmt.dinheiro(sum((Decimal(d["valor"]) for d in corr["duplicatas"]), Decimal(0)))
    _gravar(cur, rid, r["extraido"], corr)
    return obter(cur, rid)


def escolher_valor_cheio(cur, rid: int, opcao: str) -> dict:
    """Resposta ao C1: 'itens' (soma dos itens) ou 'total' (total impresso)."""
    r = _travar(cur, rid)
    _pendente(r)
    c1 = next((p for p in r["pendencias"] if p["codigo"] == "C1"), None)
    if not c1:
        raise ErroAPI("conflito", "Este rascunho não tem divergência entre itens e total")
    valor = c1["soma_itens"] if opcao == "itens" else c1["total_pedido"]
    return corrigir(cur, rid, {"valor_cheio": valor})


def aprovar(cur, arqs: Arquivos, rid: int, mudancas: Optional[dict] = None) -> dict:
    if mudancas:
        corrigir(cur, rid, mudancas)
    r = _travar(cur, rid)
    _pendente(r)
    erros = [p for p in r["pendencias"] if p["nivel"] == "erro"]
    if erros:
        raise ErroAPI("validacao", "Ainda há pendências a resolver: " + "; ".join(p["mensagem"] for p in erros),
                      {"pendencias": erros})
    cur.execute("select id from documento where rascunho_id = %s order by id", (rid,))
    doc_ids = [d["id"] for d in cur.fetchall()]
    d = r["dados"]
    faltam = [k for k in ("fornecedor_id", "numero_pedido", "data_pagamento", "valor_pago", "valor_cheio",
                          "duplicatas") if not d.get(k)]
    if faltam:
        raise ErroAPI("validacao", "Faltam dados para lançar: " + ", ".join(faltam), {"campos": faltam})
    nova = ops.OperacaoNova(
        fornecedor_id=d["fornecedor_id"], numero_pedido=d["numero_pedido"], numero_nf=d.get("numero_nf"),
        data_pedido=d.get("data_pedido"), data_pagamento=d["data_pagamento"], valor_pago=d["valor_pago"],
        valor_cheio=d["valor_cheio"], observacoes=d.get("observacoes"), duplicatas=d["duplicatas"],
        documento_ids=doc_ids)
    op_id = ops.criar(cur, arqs, nova, origem="robo")
    cur.execute("update rascunho set estado = 'aprovado', operacao_id = %s, decidido_em = now(), "
                "decidido_por = nullif(current_setting('caixa.usuario_id', true), '')::bigint, "
                "atualizado_em = now() where id = %s", (op_id, rid))
    return {"rascunho": obter(cur, rid), "operacao": ops.obter(cur, op_id)}


def descartar(cur, rid: int, motivo: str) -> dict:
    r = _travar(cur, rid)
    _pendente(r)
    cur.execute("update rascunho set estado = 'descartado', descarte_motivo = %s, decidido_em = now(), "
                "decidido_por = nullif(current_setting('caixa.usuario_id', true), '')::bigint, "
                "atualizado_em = now() where id = %s", ((motivo or "").strip() or "Descartado", rid))
    return obter(cur, rid)


def juntar(cur, rid: int, outro: int) -> dict:
    """Junta dois rascunhos (um com o pedido, outro com o comprovante)."""
    if rid == outro:
        raise ErroAPI("validacao", "Escolha dois rascunhos diferentes")
    a, b = sorted((_travar(cur, rid), _travar(cur, outro)), key=lambda x: x["id"] != rid)
    _pendente(a)
    _pendente(b)
    ea, eb = dict(a["extraido"]), dict(b["extraido"])
    for chave in ("pedido", "comprovante"):
        if chave in ea and chave in eb:
            raise ErroAPI("conflito", f"Os dois rascunhos já têm {chave}: não dá para juntar")
        if chave in eb:
            ea[chave] = eb[chave]
    ea["_confianca"] = {**(eb.get("_confianca") or {}), **(ea.get("_confianca") or {})}
    ea["_ilegiveis"] = sorted(set(ea.get("_ilegiveis") or []) | set(eb.get("_ilegiveis") or []))
    ea.pop("_candidatos", None)
    cur.execute("update documento set rascunho_id = %s where rascunho_id = %s", (a["id"], b["id"]))
    cur.execute("update rascunho set estado = 'descartado', descarte_motivo = %s, decidido_em = now(), "
                "decidido_por = nullif(current_setting('caixa.usuario_id', true), '')::bigint, "
                "atualizado_em = now() where id = %s", (MOTIVO_JUNTADO.format(id=a["id"]), b["id"]))
    # quem apontava para b como candidato passa a apontar para a
    _gravar(cur, a["id"], ea, {**dict(b["correcoes"]), **dict(a["correcoes"])})
    return obter(cur, a["id"])
