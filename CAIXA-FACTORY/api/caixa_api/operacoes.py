"""Operações: leitura, lançamento, edição, estorno (docs/04-api.md §3).

As validações do lançamento seguem a ordem da especificação e param na
primeira falha, com mensagem e detalhe úteis para a tela. O banco repete as
regras críticas (RN-01 a RN-06) por trigger: se a aplicação deixar passar
alguma coisa, o commit falha do mesmo jeito.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from . import fmt
from .documentos import Arquivos, vincular
from .erros import ErroAPI

JANELA_VENCIMENTO = timedelta(days=365)     # A-02


# --- modelos de entrada ----------------------------------------------------

class DuplicataEntrada(BaseModel):
    id: Optional[int] = None                 # só no PATCH: duplicata que já existe
    valor: fmt.Dinheiro
    vencimento: date


class OperacaoNova(BaseModel):
    fornecedor_id: int
    numero_pedido: str = Field(min_length=1, max_length=60)
    numero_nf: Optional[str] = Field(default=None, max_length=60)
    data_pedido: Optional[date] = None
    data_pagamento: date
    valor_pago: fmt.Dinheiro
    valor_cheio: fmt.Dinheiro
    observacoes: Optional[str] = Field(default=None, max_length=2000)
    duplicatas: list[DuplicataEntrada] = Field(default_factory=list)
    documento_ids: list[int] = Field(default_factory=list)


class OperacaoAlteracao(BaseModel):
    fornecedor_id: Optional[int] = None
    numero_pedido: Optional[str] = Field(default=None, min_length=1, max_length=60)
    numero_nf: Optional[str] = Field(default=None, max_length=60)
    data_pedido: Optional[date] = None
    data_pagamento: Optional[date] = None
    valor_pago: Optional[fmt.Dinheiro] = None
    valor_cheio: Optional[fmt.Dinheiro] = None
    observacoes: Optional[str] = Field(default=None, max_length=2000)
    duplicatas: Optional[list[DuplicataEntrada]] = None
    documento_ids: Optional[list[int]] = None


class Estorno(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)


# --- leitura ---------------------------------------------------------------

_SELECT = """
select o.id, o.fornecedor_id, f.nome as fornecedor_nome,
       o.numero_pedido, o.numero_nf, o.data_pedido, o.data_pagamento,
       o.valor_pago, o.valor_cheio, o.situacao, o.origem, o.observacoes,
       o.estornada_em, o.estorno_motivo, o.criado_em, o.atualizado_em,
       v.recebido, v.aberto, v.prazo_medio, v.taxa_mes, v.taxa_ano,
       v.estado as estado_calc, coalesce(v.atrasada, false) as atrasada
  from operacao o
  join fornecedor f on f.id = o.fornecedor_id
  left join v_operacao v on v.id = o.id
"""

ESTADOS = ("em_aberto", "parcial", "encerrada", "atrasada", "rascunho", "estornada")


def _json(o: dict, dups: list[dict], docs: list[dict]) -> dict:
    pago, cheio = o["valor_pago"], o["valor_cheio"]
    lucro = cheio - pago
    confirmada = o["situacao"] == "confirmada" and o["estado_calc"] is not None
    taxa_mes = o["taxa_mes"] if confirmada else None
    return {
        "id": o["id"],
        "fornecedor": {"id": o["fornecedor_id"], "nome": o["fornecedor_nome"]},
        "numero_pedido": o["numero_pedido"],
        "numero_nf": o["numero_nf"],
        "data_pedido": fmt.data_iso(o["data_pedido"]),
        "data_pagamento": fmt.data_iso(o["data_pagamento"]),
        "valor_pago": fmt.dinheiro(pago),
        "valor_cheio": fmt.dinheiro(cheio),
        "lucro": fmt.dinheiro(lucro),
        "retorno": fmt.taxa(lucro / pago),          # taxa do investidor (RN-07)
        "desconto": fmt.taxa(lucro / cheio),        # taxa do fornecedor, secundária
        "prazo_medio_dias": fmt.dias(o["prazo_medio"]) if confirmada else None,
        "taxa_mes": fmt.taxa(taxa_mes),
        "taxa_ano": fmt.taxa(o["taxa_ano"]) if confirmada else None,
        "lucro_mes_reais": fmt.dinheiro(pago * taxa_mes) if taxa_mes is not None else None,
        "recebido": fmt.dinheiro(o["recebido"]) if confirmada else None,
        "aberto": fmt.dinheiro(o["aberto"]) if confirmada else None,
        "estado": o["estado_calc"] if confirmada else o["situacao"],
        "atrasada": bool(o["atrasada"]) if confirmada else False,
        "situacao": o["situacao"],
        "origem": o["origem"],
        "observacoes": o["observacoes"],
        "estornada_em": o["estornada_em"].isoformat() if o["estornada_em"] else None,
        "estorno_motivo": o["estorno_motivo"],
        "duplicatas": [{
            "id": d["id"], "sequencia": d["sequencia"], "valor": fmt.dinheiro(d["valor"]),
            "vencimento": fmt.data_iso(d["vencimento"]), "recebida_em": fmt.data_iso(d["recebida_em"]),
            "atrasada": d["recebida_em"] is None and d["atrasada"],
        } for d in dups],
        "documentos": [{
            "id": d["id"], "tipo": d["tipo"], "nome_arquivo": d["nome_arquivo"],
            "data_doc": fmt.data_iso(d["data_doc"]),
        } for d in docs],
    }


def _montar(cur, linhas: list[dict]) -> list[dict]:
    ids = [o["id"] for o in linhas]
    if not ids:
        return []
    cur.execute("select id, operacao_id, sequencia, valor, vencimento, recebida_em, "
                "vencimento < current_date as atrasada from duplicata "
                "where operacao_id = any(%s) order by operacao_id, sequencia", (ids,))
    dups: dict[int, list] = {}
    for d in cur.fetchall():
        dups.setdefault(d["operacao_id"], []).append(d)
    cur.execute("select id, operacao_id, tipo, nome_arquivo, data_doc from documento "
                "where operacao_id = any(%s) order by operacao_id, id", (ids,))
    docs: dict[int, list] = {}
    for d in cur.fetchall():
        docs.setdefault(d["operacao_id"], []).append(d)
    return [_json(o, dups.get(o["id"], []), docs.get(o["id"], [])) for o in linhas]


def obter(cur, op_id: int) -> dict:
    cur.execute(_SELECT + " where o.id = %s", (op_id,))
    o = cur.fetchone()
    if not o:
        raise ErroAPI("nao_encontrado", f"Operação {op_id} não existe")
    return _montar(cur, [o])[0]


def listar(cur, *, estado=None, fornecedor_id=None, q=None, de=None, ate=None,
           pagina=1, por_pagina=50) -> dict:
    onde, p = [], []
    if estado in ("rascunho", "estornada"):
        onde.append("o.situacao = %s"); p.append(estado)
    else:
        onde.append("o.situacao = 'confirmada'")
        if estado == "em_aberto":
            onde.append("v.recebido = 0 and v.aberto > 0")
        elif estado in ("parcial", "encerrada"):
            onde.append("v.estado = %s"); p.append(estado)
        elif estado == "atrasada":
            onde.append("v.atrasada")
    if fornecedor_id:
        onde.append("o.fornecedor_id = %s"); p.append(fornecedor_id)
    if q:
        termo = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        onde.append("(o.numero_pedido ilike %s or o.numero_nf ilike %s or o.observacoes ilike %s)")
        p += [termo, termo, termo]
    if de:
        onde.append("o.data_pagamento >= %s"); p.append(de)
    if ate:
        onde.append("o.data_pagamento <= %s"); p.append(ate)
    where = " where " + " and ".join(onde)

    cur.execute("select count(*) as n from operacao o left join v_operacao v on v.id = o.id" + where, p)
    total = cur.fetchone()["n"]
    cur.execute(_SELECT + where + " order by o.data_pagamento desc, o.id desc limit %s offset %s",
                p + [por_pagina, (pagina - 1) * por_pagina])
    return {"itens": _montar(cur, cur.fetchall()), "total": total, "pagina": pagina, "por_pagina": por_pagina}


# --- regras compartilhadas -------------------------------------------------

def caixa_disponivel(cur) -> Decimal:
    cur.execute("select caixa.caixa_disponivel() as c")
    return cur.fetchone()["c"]


def _fornecedor_ativo(cur, fornecedor_id: int) -> str:
    cur.execute("select nome, ativo, observacoes from fornecedor where id = %s", (fornecedor_id,))
    f = cur.fetchone()
    if not f:
        raise ErroAPI("validacao", f"Fornecedor {fornecedor_id} não existe", {"campo": "fornecedor_id"})
    if not f["ativo"]:
        raise ErroAPI("validacao", f"Fornecedor {f['nome']} está inativo", {"campo": "fornecedor_id"})
    return f["nome"]


def _valores(pago: Decimal, cheio: Decimal) -> None:
    if pago <= 0 or cheio <= 0:
        raise ErroAPI("validacao", "Valor pago e valor cheio precisam ser maiores que zero")
    if cheio < pago:          # RN-02
        raise ErroAPI("validacao", f"O valor pago ({fmt.brl(pago)}) não pode passar do valor cheio "
                                   f"({fmt.brl(cheio)}) — confira a digitação",
                      {"valor_pago": fmt.dinheiro(pago), "valor_cheio": fmt.dinheiro(cheio)})


def _duplicatas(dups: list, cheio: Decimal, data_pagamento: date) -> None:
    if not dups:
        raise ErroAPI("validacao", "Informe pelo menos uma duplicata")
    for i, d in enumerate(dups, 1):
        if d["valor"] <= 0:
            raise ErroAPI("validacao", f"Duplicata {i}: valor precisa ser maior que zero")
    soma = sum((d["valor"] for d in dups), Decimal(0))
    if soma != cheio:         # RN-01, tolerância zero
        raise ErroAPI("soma_duplicatas",
                      f"As duplicatas somam {fmt.brl(soma)} e o valor cheio é {fmt.brl(cheio)}",
                      {"soma_duplicatas": fmt.dinheiro(soma), "valor_cheio": fmt.dinheiro(cheio),
                       "diferenca": fmt.dinheiro(cheio - soma)})
    for i, d in enumerate(dups, 1):   # A-02: quase sempre é o ano digitado errado
        if d["vencimento"] < data_pagamento or d["vencimento"] > data_pagamento + JANELA_VENCIMENTO:
            raise ErroAPI("validacao",
                          f"Duplicata {i}: vencimento {fmt.br_data(d['vencimento'])} fora da janela de "
                          f"{fmt.br_data(data_pagamento)} a {fmt.br_data(data_pagamento + JANELA_VENCIMENTO)}"
                          " — confira o ano (A-02)",
                          {"vencimento": fmt.data_iso(d["vencimento"]), "data_pagamento": fmt.data_iso(data_pagamento)})


def _caixa(disponivel: Decimal, solicitado: Decimal) -> None:
    if solicitado > disponivel:   # RN-03
        raise ErroAPI("caixa_insuficiente",
                      f"Caixa insuficiente: você tem {fmt.brl(max(disponivel, Decimal(0)))} livre. "
                      "Registre um aporte antes de lançar esta compra.",
                      {"disponivel": fmt.dinheiro(disponivel), "solicitado": fmt.dinheiro(solicitado)})


def _ordenar(dups: list[dict]) -> list[dict]:
    """A sequência é do servidor: ordem de vencimento, empate pela ordem enviada."""
    return [d for _, d in sorted(enumerate(dups), key=lambda x: (x[1]["vencimento"], x[0]))]


# --- escrita ---------------------------------------------------------------

def criar(cur, arqs: Arquivos, dados: OperacaoNova) -> int:
    _fornecedor_ativo(cur, dados.fornecedor_id)                              # 1
    _valores(dados.valor_pago, dados.valor_cheio)                            # 2, 3
    dups = [d.model_dump() for d in dados.duplicatas]
    _duplicatas(dups, dados.valor_cheio, dados.data_pagamento)               # 4, 5, 6
    _caixa(caixa_disponivel(cur), dados.valor_pago)                          # 7

    cur.execute(
        """insert into operacao (fornecedor_id, numero_pedido, numero_nf, data_pedido, data_pagamento,
                                 valor_pago, valor_cheio, observacoes, situacao, origem, criado_por)
           values (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmada', 'manual',
                   nullif(current_setting('caixa.usuario_id', true), '')::bigint)
           returning id""",
        (dados.fornecedor_id, dados.numero_pedido.strip(), (dados.numero_nf or "").strip() or None,
         dados.data_pedido, dados.data_pagamento, dados.valor_pago, dados.valor_cheio,
         dados.observacoes))
    op_id = cur.fetchone()["id"]
    for seq, d in enumerate(_ordenar(dups), 1):
        cur.execute("insert into duplicata (operacao_id, sequencia, valor, vencimento) values (%s, %s, %s, %s)",
                    (op_id, seq, d["valor"], d["vencimento"]))
    vincular(cur, arqs, op_id, dados.numero_pedido.strip(), dados.documento_ids)
    return op_id


def _travar(cur, op_id: int) -> dict:
    cur.execute("select * from operacao where id = %s for update", (op_id,))
    o = cur.fetchone()
    if not o:
        raise ErroAPI("nao_encontrado", f"Operação {op_id} não existe")
    return o


def alterar(cur, arqs: Arquivos, op_id: int, dados: OperacaoAlteracao) -> list[str]:
    """Devolve a lista de avisos (ex.: vencimento de duplicata já recebida mudou)."""
    o = _travar(cur, op_id)
    if o["situacao"] == "estornada":
        raise ErroAPI("conflito", "Operação estornada não pode ser alterada")
    mudou = dados.model_fields_set
    novo = {k: getattr(dados, k) if k in mudou else o[k]
            for k in ("fornecedor_id", "numero_pedido", "numero_nf", "data_pedido", "data_pagamento",
                      "valor_pago", "valor_cheio", "observacoes")}
    for k in ("fornecedor_id", "numero_pedido", "data_pagamento", "valor_pago", "valor_cheio"):
        if novo[k] is None:
            raise ErroAPI("validacao", f"{k} não pode ficar vazio", {"campo": k})
    avisos: list[str] = []

    if "fornecedor_id" in mudou and novo["fornecedor_id"] != o["fornecedor_id"]:
        _fornecedor_ativo(cur, novo["fornecedor_id"])
    _valores(novo["valor_pago"], novo["valor_cheio"])

    cur.execute("select id, sequencia, valor, vencimento, recebida_em from duplicata "
                "where operacao_id = %s order by sequencia", (op_id,))
    atuais = {d["id"]: d for d in cur.fetchall()}
    recebido_op = sum((d["valor"] for d in atuais.values() if d["recebida_em"]), Decimal(0))

    if dados.duplicatas is not None:
        lista = [d.model_dump() for d in dados.duplicatas]
        vistos = set()
        for d in lista:
            if d["id"] is None:
                continue
            if d["id"] not in atuais:
                raise ErroAPI("validacao", f"Duplicata {d['id']} não pertence a esta operação")
            if d["id"] in vistos:
                raise ErroAPI("validacao", f"Duplicata {d['id']} aparece duas vezes")
            vistos.add(d["id"])
            a = atuais[d["id"]]
            if a["recebida_em"]:
                if d["valor"] != a["valor"]:
                    raise ErroAPI("validacao", f"A duplicata {a['sequencia']} já foi recebida: o valor não pode "
                                               "mudar. Desfaça o recebimento antes.", {"duplicata_id": a["id"]})
                if d["vencimento"] != a["vencimento"]:
                    avisos.append(f"Vencimento da duplicata {a['sequencia']}, já recebida, mudou de "
                                  f"{fmt.br_data(a['vencimento'])} para {fmt.br_data(d['vencimento'])}")
        for a in atuais.values():
            if a["recebida_em"] and a["id"] not in vistos:
                raise ErroAPI("validacao", f"A duplicata {a['sequencia']} já foi recebida e não pode sair da lista. "
                                           "Desfaça o recebimento antes.", {"duplicata_id": a["id"]})
    else:
        lista = [dict(d) for d in atuais.values()]

    if o["situacao"] == "confirmada":
        _duplicatas(lista, novo["valor_cheio"], novo["data_pagamento"])
        # RN-03 na edição: a própria operação devolve o que pagou antes. O que ela
        # já recebeu continua no caixa depois da edição, então não entra na conta
        # (o banco checa o mesmo: caixa >= 0 depois da mudança).
        if novo["valor_pago"] > o["valor_pago"]:
            _caixa(caixa_disponivel(cur) + o["valor_pago"], novo["valor_pago"])
    if recebido_op and "data_pagamento" in mudou:
        primeira = min(d["recebida_em"] for d in atuais.values() if d["recebida_em"])
        if novo["data_pagamento"] > primeira:
            raise ErroAPI("validacao", f"Pagamento em {fmt.br_data(novo['data_pagamento'])} fica depois de "
                                       f"um recebimento já lançado em {fmt.br_data(primeira)} (RN-04)")

    cur.execute(
        """update operacao set fornecedor_id = %s, numero_pedido = %s, numero_nf = %s, data_pedido = %s,
                  data_pagamento = %s, valor_pago = %s, valor_cheio = %s, observacoes = %s
            where id = %s""",
        (novo["fornecedor_id"], novo["numero_pedido"].strip(), (novo["numero_nf"] or "").strip() or None,
         novo["data_pedido"], novo["data_pagamento"], novo["valor_pago"], novo["valor_cheio"],
         novo["observacoes"], op_id))

    if dados.duplicatas is not None:
        ficam = {d["id"] for d in lista if d["id"]}
        sair = [i for i in atuais if i not in ficam]
        if sair:
            cur.execute("delete from duplicata where id = any(%s)", (sair,))
        ordem = _ordenar(lista)
        exist = [(d["id"], seq, d["valor"], d["vencimento"]) for seq, d in enumerate(ordem, 1) if d["id"]]
        if exist:
            ids, seqs, vals, vencs = map(list, zip(*exist))
            cur.execute(
                """update duplicata d set sequencia = x.seq, valor = x.valor, vencimento = x.venc
                     from unnest(%s::bigint[], %s::int[], %s::numeric[], %s::date[]) as x(id, seq, valor, venc)
                    where d.id = x.id
                      and (d.sequencia, d.valor, d.vencimento) is distinct from (x.seq, x.valor, x.venc)""",
                (ids, seqs, vals, vencs))
        for seq, d in enumerate(ordem, 1):
            if not d["id"]:
                cur.execute("insert into duplicata (operacao_id, sequencia, valor, vencimento) values (%s, %s, %s, %s)",
                            (op_id, seq, d["valor"], d["vencimento"]))

    if dados.documento_ids:
        vincular(cur, arqs, op_id, novo["numero_pedido"].strip(), dados.documento_ids)
    return avisos


def estornar(cur, op_id: int, motivo: str) -> None:
    o = _travar(cur, op_id)
    if o["situacao"] == "estornada":
        raise ErroAPI("conflito", "Operação já está estornada",
                      {"estornada_em": o["estornada_em"].isoformat(), "motivo": o["estorno_motivo"]})
    cur.execute("update operacao set situacao = 'estornada', estornada_em = now(), estorno_motivo = %s "
                "where id = %s", (motivo.strip(), op_id))


def excluir(cur, op_id: int, motivo: Optional[str]) -> None:
    """Exclusão lógica: nada se apaga (princípio 3). Só sem nenhum recebimento (RN-06)."""
    o = _travar(cur, op_id)
    if o["situacao"] == "estornada":
        raise ErroAPI("conflito", "Operação já está estornada")
    cur.execute("select count(*) as n from duplicata where operacao_id = %s and recebida_em is not null", (op_id,))
    if cur.fetchone()["n"]:
        raise ErroAPI("conflito", "Esta operação já tem duplicata recebida: use o estorno "
                                  f"(POST /operacoes/{op_id}/estorno), não a exclusão")
    cur.execute("update operacao set situacao = 'estornada', estornada_em = now(), estorno_motivo = %s "
                "where id = %s", ((motivo or "").strip() or "Excluída", op_id))
