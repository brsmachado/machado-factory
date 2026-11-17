"""Aviso diário (docs/06-robo.md, Robôs 2 e 3 numa mensagem só).

Todo dia útil às 9h:
  - o que vence hoje, o que vence nos próximos dias e o que está atrasado,
    com um botão "Recebi" por duplicata (o clique é do dono; o robô não
    marca nada sozinho);
  - o alerta de dinheiro parado, quando o caixa passa do limite por N dias
    seguidos — repetido só se o valor mudar mais de 20% ou a cada 7 dias;
  - os rascunhos esperando conferência.
Tom: informar, não cobrar.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from .. import fmt


def _param(cur, chave: str, padrao: str) -> str:
    cur.execute("select valor from parametro where chave = %s", (chave,))
    p = cur.fetchone()
    return p["valor"] if p and p["valor"] != "" else padrao


def _curto(nome: str) -> str:
    """'SB Indústria e Comércio de Papel' -> 'SB Indústria'."""
    return " ".join(nome.split()[:2])


def _ordinal(n: int) -> str:
    return f"{n}ª"


def _linha_dup(d: dict) -> str:
    return f"  {_curto(d['fornecedor'])} · {d['numero_pedido']} · {_ordinal(d['sequencia'])} de {d['de']} · {fmt.brl(d['valor'])}"


def _caixa_parado(cur, hoje: date, caixa: Decimal) -> tuple[Optional[str], Optional[int]]:
    limite = Decimal(_param(cur, "caixa_parado_limite", "20000.00"))
    minimo = int(_param(cur, "caixa_parado_dias", "3"))
    repetir = int(_param(cur, "alerta_repetir_dias", "7"))
    variacao = Decimal(_param(cur, "alerta_repetir_variacao", "0.20"))
    if caixa <= limite:
        return None, None

    # há quantos dias seguidos o caixa está acima do limite
    cur.execute("select dia, caixa from caixa_diario where dia <= %s order by dia desc", (hoje,))
    inicio = hoje
    for l in cur.fetchall():
        if l["caixa"] <= limite:
            break
        inicio = l["dia"]
    dias = (hoje - inicio).days + 1
    if dias < minimo:
        return None, None

    cur.execute("select id, valor, dia from alerta where tipo = 'caixa_parado' order by dia desc, id desc limit 1")
    ultimo = cur.fetchone()
    if ultimo and ultimo["dia"] >= inicio:                     # já avisou nesta mesma sequência
        mudou = ultimo["valor"] and abs(caixa - ultimo["valor"]) / ultimo["valor"] > variacao
        if not mudou and (hoje - ultimo["dia"]).days < repetir:
            return None, None

    cur.execute("select taxa_mes from v_carteira")
    taxa_mes = cur.fetchone()["taxa_mes"] or Decimal(0)
    linhas = [f"⚠ {fmt.brl(caixa)} parados há {dias} dias"]
    if taxa_mes > 0:
        por_dia = (caixa * taxa_mes / 30).quantize(fmt.CENTAVO)
        linhas += ["", f"Suas operações rendem {fmt.br_decimal(taxa_mes * 100)}% ao mês. Esse dinheiro "
                       f"parado está deixando de render cerca de {fmt.brl(por_dia)} por dia — "
                       f"{fmt.brl(por_dia * 30)} por mês."]
    cur.execute("select coalesce(sum(d.valor), 0) as total, max(d.vencimento) as ate from duplicata d "
                "join operacao o on o.id = d.operacao_id where o.situacao = 'confirmada' and d.recebida_em is null")
    ar = cur.fetchone()
    if ar["total"]:
        linhas.append(f"Entram ainda {fmt.brl(ar['total'])} até {ar['ate']:%d/%m}.")
    texto = "\n".join(linhas)
    cur.execute("insert into alerta (tipo, dia, mensagem, valor, dias) values ('caixa_parado', %s, %s, %s, %s) "
                "returning id", (hoje, texto, caixa, dias))
    return texto, cur.fetchone()["id"]


def montar(cur, hoje: Optional[date] = None) -> dict:
    """Monta o aviso do dia e registra o caixa do dia. Devolve
    {texto, botoes, enviar, alerta_id}. `enviar` é False num dia sem nada a dizer."""
    if hoje is None:
        cur.execute("select current_date as h")
        hoje = cur.fetchone()["h"]
    cur.execute("select caixa, aplicado, capital, a_receber from v_caixa")
    c = cur.fetchone()
    cur.execute("""insert into caixa_diario (dia, caixa, aplicado, capital) values (%s, %s, %s, %s)
                   on conflict (dia) do update set caixa = excluded.caixa, aplicado = excluded.aplicado,
                          capital = excluded.capital, registrado_em = now()""",
                (hoje, c["caixa"], c["aplicado"], c["capital"]))

    breve = int(_param(cur, "vence_em_breve_dias", "3"))
    cur.execute("""
        select d.id, d.sequencia, d.valor, d.vencimento, o.numero_pedido, f.nome as fornecedor,
               (select count(*) from duplicata x where x.operacao_id = d.operacao_id)::int as de
          from duplicata d join operacao o on o.id = d.operacao_id join fornecedor f on f.id = o.fornecedor_id
         where o.situacao = 'confirmada' and d.recebida_em is null and d.vencimento <= %s
         order by d.vencimento, d.id""", (hoje + timedelta(days=breve),))
    dups = cur.fetchall()
    hoje_l = [d for d in dups if d["vencimento"] == hoje]
    breve_l = [d for d in dups if d["vencimento"] > hoje]
    atras_l = [d for d in dups if d["vencimento"] < hoje]

    partes = [f"Caixa Factory · {hoje:%d/%m/%Y}"]

    def bloco(titulo, lista, linha):
        total = sum((d["valor"] for d in lista), Decimal(0))
        partes.append("\n".join([f"{titulo} — {fmt.brl(total)}"] + [linha(d) for d in lista]))

    if hoje_l:
        bloco("VENCEM HOJE", hoje_l, _linha_dup)
    if breve_l:
        bloco(f"VENCEM ATÉ {(hoje + timedelta(days=breve)):%d/%m}", breve_l,
              lambda d: _linha_dup(d) + f" · {d['vencimento']:%d/%m}")
    if atras_l:
        def atrasada(d):
            n = (hoje - d["vencimento"]).days
            return (f"  {_curto(d['fornecedor'])} · {d['numero_pedido']} · {fmt.brl(d['valor'])} · "
                    f"venceu {d['vencimento']:%d/%m} ({n} {'dia' if n == 1 else 'dias'})")
        bloco("ATRASADAS", atras_l, atrasada)

    alerta, alerta_id = _caixa_parado(cur, hoje, c["caixa"])
    if alerta:
        partes.append(alerta)

    cur.execute("select count(*) as n from rascunho where estado = 'pendente'")
    n_rasc = cur.fetchone()["n"]
    if n_rasc:
        partes.append(f"📄 {n_rasc} {'rascunho esperando' if n_rasc == 1 else 'rascunhos esperando'} "
                      "sua conferência (/pendentes)")

    partes.append(f"Caixa hoje: {fmt.brl(c['caixa'])} · a receber: {fmt.brl(c['a_receber'])}")
    botoes = [[(f"✓ Recebi {fmt.brl(d['valor'])} · {d['numero_pedido']}", f"rec:{d['id']}")]
              for d in hoje_l + atras_l]
    return {"texto": "\n\n".join(partes), "botoes": botoes,
            "enviar": bool(hoje_l or breve_l or atras_l or alerta or n_rasc), "alerta_id": alerta_id}
