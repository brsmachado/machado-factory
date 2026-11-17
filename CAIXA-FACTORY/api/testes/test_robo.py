"""O robô: leitura, casamento pedido/comprovante, conferências, aprovação, aviso e Telegram."""
from datetime import date
from types import SimpleNamespace

import pytest

from conftest import CHAT_DONO


def erro(r):
    return r.status_code, r.json()["erro"]["codigo"]


def pedido(numero, fornecedor, duplicatas, itens=None, total=None, data="2026-11-10", nf="13001", cnpj=None):
    total = total or f"{sum(float(v) for _, v in duplicatas):.2f}"
    return {"tipo_documento": "pedido_compra", "comprovante": None,
            "confianca": {"numero_pedido": 0.99, "total_pedido": 0.98, "duplicatas": 0.97},
            "pedido": {"numero_pedido": f"PEDIDO DE COMPRA{numero}", "numero_nf": f"NFe {nf}", "data_pedido": data,
                       "fornecedor_nome": fornecedor, "fornecedor_cnpj": cnpj,
                       "itens": itens or [{"descricao": "item", "quantidade": "1", "valor_unitario": total,
                                           "valor_total": total}],
                       "total_pedido": total, "condicao_pagamento": "30",
                       "duplicatas": [{"vencimento": v, "valor": x} for v, x in duplicatas]}}


def pix(valor, data="2026-11-12", recebedor="SB INDUSTRIA E COMERCIO DE PAPEL LTDA", conf=0.99):
    return {"tipo_documento": "comprovante_pix", "pedido": None,
            "confianca": {"valor_pago": conf, "data_pagamento": 0.99},
            "comprovante": {"valor": valor, "data_pagamento": data, "recebedor_nome": recebedor,
                            "recebedor_documento": None, "id_transacao": "E1234567890"}}


def enviar(api, leitor, *leituras, como="robo"):
    files = [("arquivos", (f"f{i}.png", leitor.arquivo(l), "image/png")) for i, l in enumerate(leituras)]
    r = api.post("/robo/ingestao", como=como, files=files)
    assert r.status_code == 200, r.json()
    return r.json()["resultados"]


def codigos(rasc):
    return sorted(p["codigo"] for p in rasc["pendencias"])


# --- A-01: o caso que quase custou R$ 398,00 ------------------------------

SB_ITENS = [{"descricao": "PAPEL ACOPLADO SB - MONO, TAM: 32X37 CM", "quantidade": "250",
             "valor_unitario": "38.90", "valor_total": "9725.00"}]


def test_pedido_e_comprovante_com_desconto_na_nota(api, leitor, sql, docs_dir):
    # 1º chega o pedido: o total impresso já vem com o desconto da SB
    [r1] = enviar(api, leitor, pedido("03600-1/26", "SB INDUSTRIA E COMERCIO DE PAPEL LTDA",
                                      [("2026-12-12", "9327.00")], itens=SB_ITENS, total="9327.00"))
    rasc = r1["rascunho"]
    assert r1["acao"] == "criado" and rasc["dados"]["numero_pedido"] == "PC 03600-1/26"
    assert rasc["dados"]["fornecedor_id"] == 2
    assert {"C1", "falta_comprovante"} <= set(codigos(rasc))
    c1 = next(p for p in rasc["pendencias"] if p["codigo"] == "C1")
    assert c1["mensagem"] == ("Os itens somam R$ 9.725,00 mas o total do pedido saiu R$ 9.327,00. "
                              "A SB lança o desconto na própria nota — o valor cheio correto costuma ser a soma "
                              "dos itens. Confirme qual usar.")

    # 2º o PIX: casa pelo valor e vira um rascunho só
    [r2] = enviar(api, leitor, pix("9336.00"))
    assert r2["acao"] == "juntado" and r2["rascunho"]["id"] == rasc["id"]
    rasc = r2["rascunho"]
    # pago 9.336,00 >= cheio 9.327,00: lido do jeito errado, a operação daria prejuízo
    assert "C4" in codigos(rasc) and rasc["pode_aprovar"] is False
    assert erro(api.post(f"/robo/rascunhos/{rasc['id']}/aprovar")) == (422, "validacao")

    # o dono escolhe: soma dos itens
    r = api.patch(f"/robo/rascunhos/{rasc['id']}", json={"valor_cheio": "9725.00"})
    rasc = r.json()
    assert rasc["dados"]["duplicatas"] == [{"valor": "9725.00", "vencimento": "2026-12-12"}]
    assert codigos(rasc) == [] and rasc["pode_aprovar"]
    assert rasc["previa"]["lucro"] == "389.00" and rasc["previa"]["retorno"] == "0.041667"

    r = api.post(f"/robo/rascunhos/{rasc['id']}/aprovar")
    assert r.status_code == 201, r.json()
    op = r.json()["operacao"]
    assert (op["origem"], op["valor_cheio"], op["valor_pago"], op["data_pagamento"], op["lucro"]) == \
        ("robo", "9725.00", "9336.00", "2026-11-12", "389.00")
    assert sorted(d["nome_arquivo"] for d in op["documentos"]) == [
        "2026-11-10_PC-03600-1-26_pedido-compra.png", "2026-11-12_PC-03600-1-26_comprovante-pix.png"]
    assert api.get("/resumo").json()["caixa"] == "102474.32"
    assert api.get(f"/robo/rascunhos/{rasc['id']}").json()["estado"] == "aprovado"
    assert erro(api.post(f"/robo/rascunhos/{rasc['id']}/aprovar")) == (409, "conflito")


def test_robo_nao_aprova_nem_corrige(api, leitor):
    [r] = enviar(api, leitor, pedido("03601-1/26", "SB INDUSTRIA", [("2026-12-12", "1000.00")]))
    rid = r["rascunho"]["id"]
    assert erro(api.post(f"/robo/rascunhos/{rid}/aprovar", como="robo")) == (403, "sem_permissao")
    assert erro(api.patch(f"/robo/rascunhos/{rid}", como="robo", json={"valor_pago": "1.00"})) == (403, "sem_permissao")
    assert erro(api.post(f"/robo/rascunhos/{rid}/descartar", como="robo")) == (403, "sem_permissao")
    files = [("arquivos", ("x.png", leitor.arquivo(pix("1.00")), "image/png"))]
    assert erro(api.post("/robo/ingestao", como="leitura", files=files)) == (403, "sem_permissao")


# --- A-04: dois pedidos e dois PIX no mesmo dia ---------------------------

def test_casa_por_valor_dois_pedidos_no_mesmo_dia(api, leitor):
    brislu = "BRISLU PLASTICOS LTDA"
    a, b = enviar(api, leitor,
                  pedido("03295-9/26", brislu, [("2026-12-12", "12975.90"), ("2026-12-22", "12975.90")], data="2026-11-12"),
                  pedido("03331-9/26", brislu, [("2026-12-12", "16863.66"), ("2026-12-22", "16863.66")], data="2026-11-12"))
    # o PIX maior chega primeiro: tem que ir para o pedido maior
    p1, p2 = enviar(api, leitor, pix("32313.60", recebedor=brislu), pix("24864.00", recebedor=brislu))
    assert p1["acao"] == p2["acao"] == "juntado"
    assert p1["rascunho"]["id"] == b["rascunho"]["id"] and p2["rascunho"]["id"] == a["rascunho"]["id"]
    assert p1["rascunho"]["previa"]["retorno"] == "0.043750"
    assert all(codigos(x["rascunho"]) == [] for x in (p1, p2))


def test_comprovante_antes_do_pedido(api, leitor):
    [c] = enviar(api, leitor, pix("4107.84", data="2026-11-12"))
    assert codigos(c["rascunho"]) == ["falta_pedido"]
    [p] = enviar(api, leitor, pedido("03602-1/26", "SB INDUSTRIA E COMERCIO DE PAPEL LTDA",
                                     [("2026-12-12", "4279.00")], data="2026-11-10"))
    assert p["acao"] == "juntado" and p["rascunho"]["id"] == c["rascunho"]["id"]
    assert p["rascunho"]["pode_aprovar"]


def test_ambiguo_nao_chuta_e_deixa_juntar(api, leitor):
    sb = "SB INDUSTRIA E COMERCIO DE PAPEL LTDA"
    a, b = enviar(api, leitor, pedido("03603-1/26", sb, [("2026-12-12", "1000.00")]),
                  pedido("03603-2/26", sb, [("2026-12-12", "1000.00")]))
    [c] = enviar(api, leitor, pix("960.00"))
    assert c["acao"] == "criado"                                   # não escolheu sozinho
    amb = [p["rascunho_id"] for p in c["rascunho"]["pendencias"] if p["codigo"] == "ambiguo"]
    assert sorted(amb) == sorted([a["rascunho"]["id"], b["rascunho"]["id"]])
    r = api.post(f"/robo/rascunhos/{b['rascunho']['id']}/juntar", json={"com": c["rascunho"]["id"]})
    assert r.status_code == 200 and r.json()["pode_aprovar"] and len(r.json()["documentos"]) == 2
    assert api.get(f"/robo/rascunhos/{c['rascunho']['id']}").json()["estado"] == "descartado"


# --- outras conferências ---------------------------------------------------

def test_mesma_foto_duas_vezes(api, leitor):
    conteudo = leitor.arquivo(pix("100.00"))
    r1 = api.post("/robo/ingestao", como="robo", files=[("arquivos", ("a.png", conteudo, "image/png"))])
    r2 = api.post("/robo/ingestao", como="robo", files=[("arquivos", ("a.png", conteudo, "image/png"))])
    assert r1.json()["resultados"][0]["ok"] is True
    assert r2.json()["resultados"][0]["erro"]["codigo"] == "conflito"
    assert leitor.chamadas == 1                                   # não pagou a leitura de novo


def test_pedido_ja_lancado_e_ano_errado(api, leitor):
    # C8: PC 03273-2/26 já é a operação 7.  C5/A-02: vencimento impresso com o ano errado
    enviar(api, leitor, pedido("03273-2/26", "SB INDUSTRIA E COMERCIO DE PAPEL LTDA",
                               [("2025-12-12", "4279.00")]))
    [r] = enviar(api, leitor, pix("4107.84"))
    rasc = r["rascunho"]
    assert {"C5", "C8"} <= set(codigos(rasc)) and not rasc["pode_aprovar"]
    rasc = api.patch(f"/robo/rascunhos/{rasc['id']}", json={
        "numero_pedido": "PC 03273-3/26", "duplicatas": [{"valor": "4279.00", "vencimento": "2026-12-12"}]}).json()
    assert codigos(rasc) == [] and rasc["dados"]["valor_cheio"] == "4279.00"


def test_fornecedor_desconhecido_e_pix_para_outro(api, leitor):
    enviar(api, leitor, pedido("03604-1/26", "PLASTIFLEX EMBALAGENS LTDA", [("2026-12-12", "2000.00")]))
    [r] = enviar(api, leitor, pix("1920.00", recebedor="OUTRA EMPRESA QUALQUER SA"))
    assert {"C3", "fornecedor"} <= set(codigos(r["rascunho"]))
    rasc = api.patch(f"/robo/rascunhos/{r['rascunho']['id']}", json={"fornecedor_id": 1}).json()
    assert "fornecedor" not in codigos(rasc) and rasc["pode_aprovar"]       # C3 é aviso; o dono decide


def test_leitura_duvidosa_e_caixa_insuficiente(api, leitor):
    enviar(api, leitor, pedido("03605-1/26", "SB INDUSTRIA E COMERCIO DE PAPEL LTDA", [("2026-12-12", "200000.00")]))
    [r] = enviar(api, leitor, pix("192000.00", conf=0.6))
    assert {"C7", "confianca"} <= set(codigos(r["rascunho"]))
    assert r["rascunho"]["pode_aprovar"]                           # avisos não travam...
    assert erro(api.post(f"/robo/rascunhos/{r['rascunho']['id']}/aprovar")) == (422, "caixa_insuficiente")  # ...o caixa sim


def test_documento_que_nao_e_pedido_nem_pix(api, leitor):
    [r] = enviar(api, leitor, {"tipo_documento": "outro", "pedido": None, "comprovante": None, "confianca": {}})
    assert r["acao"] == "nao_reconhecido" and r["rascunho"] is None


# --- aviso diário ---------------------------------------------------------

def _aviso(robo, dia):
    return robo.aviso(hoje=date.fromisoformat(dia))


def test_aviso_do_dia(app, api, telegram):
    robo = app.state.robo
    res = _aviso(robo, "2026-10-26")
    t = res["texto"]
    assert t.startswith("Caixa Factory · 26/10/2026")
    assert "VENCEM HOJE — R$ 29.839,56" in t
    assert "  Brislu Plásticos · PC 03295-5/26 · 2ª de 2 · R$ 12.975,90" in t
    assert "ATRASADAS — R$ 9.725,00" in t and "venceu 24/10 (2 dias)" in t
    assert "Caixa hoje: R$ 111.810,32 · a receber: R$ 43.843,56" in t
    assert res["enviado"] and telegram.enviadas[-1]["chat_id"] == CHAT_DONO
    assert [b[0][1] for b in res["botoes"]] == ["rec:7", "rec:9", "rec:10"]   # as de hoje e a atrasada


def test_alerta_de_caixa_parado_sem_repetir_todo_dia(app, api, sql):
    robo = app.state.robo
    # caixa de R$ 111.810,32 parado, limite R$ 20.000 por 3 dias seguidos
    assert _aviso(robo, "2026-10-27")["alerta_id"] is None
    assert _aviso(robo, "2026-10-28")["alerta_id"] is None
    r = _aviso(robo, "2026-10-29")
    assert r["alerta_id"] and "⚠ R$ 111.810,32 parados há 3 dias" in r["texto"]
    assert "Suas operações rendem 3,26% ao mês" in r["texto"] and "R$ 121,66 por dia" in r["texto"]
    assert _aviso(robo, "2026-10-30")["alerta_id"] is None           # mesmo valor: não repete...
    assert _aviso(robo, "2026-11-05")["alerta_id"]                   # ...até 7 dias depois
    api.post("/movimentos", json={"tipo": "aporte", "data": "2026-11-06", "valor": "40000.00"})
    assert _aviso(robo, "2026-11-06")["alerta_id"]                   # ou se o valor mudar mais de 20%
    assert len(api.get("/robo/alertas").json()["itens"]) == 3
    assert sql.execute("select count(*) from caixa_diario").fetchone()[0] == 6


def test_dia_sem_nada_nao_manda(app, api, sql, telegram):
    sql.execute("update parametro set valor = '1000000' where chave = 'caixa_parado_limite'")
    for d in (7, 9, 10, 11):
        api.post(f"/duplicatas/{d}/receber", json={"data": "2026-11-16"})
    res = _aviso(app.state.robo, "2026-11-17")
    assert res["enviar"] is False and res["enviado"] is False and telegram.enviadas == []
    r = api.post("/robo/conciliacao", como="robo", params={"forcar": True})
    assert r.status_code == 200 and r.json()["enviado"] is True


# --- Telegram ---------------------------------------------------------------

def _msg(chat, **kw):
    return {"update_id": 1, "message": {"message_id": 1, "chat": {"id": int(chat)}, **kw}}


def _clique(dado, message_id=1, chat=CHAT_DONO):
    return {"update_id": 2, "callback_query": {"id": "cb", "data": dado,
                                               "message": {"message_id": message_id, "chat": {"id": int(chat)}}}}


@pytest.fixture
def bot(app, api, telegram):
    from caixa_api.robo.telegram import BotTelegram
    return BotTelegram(app.state.robo, telegram)


def test_telegram_foto_ate_lancamento(bot, telegram, leitor, api, sql):
    telegram.arquivos["f1"] = leitor.arquivo(pedido("03606-1/26", "SB INDUSTRIA E COMERCIO DE PAPEL LTDA",
                                                    [("2026-12-12", "9327.00")], itens=SB_ITENS, total="9327.00"))
    telegram.arquivos["f2"] = leitor.arquivo(pix("9336.00"))
    bot.processar(_msg(CHAT_DONO, photo=[{"file_id": "f1", "file_size": 10}]))
    bot.processar(_msg(CHAT_DONO, document={"file_id": "f2"}))
    ultimo = telegram.editadas[-1]
    assert ultimo["texto"].startswith("Juntei com o que já tinha chegado.")
    assert "PC 03606-1/26" in ultimo["texto"] and "Os itens somam R$ 9.725,00" in ultimo["texto"]
    dados = [d for linha in ultimo["botoes"] for _, d in linha]
    rid = int(dados[-1].split(":")[1])
    assert dados[:2] == [f"a01:{rid}:itens", f"a01:{rid}:total"] and f"apr:{rid}" not in dados

    bot.processar(_clique(f"a01:{rid}:itens"))
    dados = [d for linha in telegram.editadas[-1]["botoes"] for _, d in linha]
    assert f"apr:{rid}" in dados and "Lucro R$ 389,00 · retorno 4,17%" in telegram.editadas[-1]["texto"]

    bot.processar(_clique(f"apr:{rid}"))
    assert telegram.enviadas[-1]["texto"].startswith("✅ Lançado: operação")
    # quem aprovou foi o dono, não o robô
    quem = sql.execute("select u.email from evento e join usuario u on u.id = e.usuario_id "
                       "where e.entidade = 'operacao' and e.acao = 'criou' order by e.id desc limit 1").fetchone()[0]
    assert quem == "admin@teste.invalid"


def test_telegram_botao_recebi(bot, telegram, api):
    bot.processar(_clique("rec:11"))
    assert telegram.cliques[-1] == "Recebida ✓"
    assert api.get("/operacoes/7").json()["estado"] == "encerrada"
    bot.processar(_clique("rec:11"))                               # de novo: avisa, não quebra
    assert telegram.enviadas[-1]["texto"].startswith("⚠ Duplicata 1 do PC 03273-2/26 já foi recebida")


def test_telegram_ignora_outros_chats(bot, telegram, api):
    bot.processar(_msg("777", text="/resumo"))
    bot.processar(_clique("rec:11", chat="777"))
    assert telegram.enviadas == [] and api.get("/operacoes/7").json()["estado"] != "encerrada"


def test_telegram_comandos(bot, telegram, leitor):
    bot.processar(_msg(CHAT_DONO, text="/resumo"))
    assert telegram.enviadas[-1]["texto"].startswith("Caixa livre: R$ 111.810,32")
    bot.processar(_msg(CHAT_DONO, text="/agenda"))
    assert "Em aberto: R$ 43.843,56" in telegram.enviadas[-1]["texto"]
    telegram.arquivos["f"] = leitor.arquivo(pedido("03607-1/26", "SB INDUSTRIA", [("2025-12-12", "500.00")]))
    bot.processar(_msg(CHAT_DONO, photo=[{"file_id": "f"}]))
    rid = int(telegram.editadas[-1]["texto"].split()[2])
    bot.processar(_msg(CHAT_DONO, text=f"/corrigir {rid} duplicatas 2026-12-12=500.00"))
    assert "Duplicatas: 12/12/2026 R$ 500,00" in telegram.enviadas[-1]["texto"]
    bot.processar(_msg(CHAT_DONO, text=f"/descartar {rid} foto errada"))
    assert "🗑 Descartado: foto errada" in telegram.enviadas[-1]["texto"]
    bot.processar(_msg(CHAT_DONO, text="/corrigir abc"))
    assert telegram.enviadas[-1]["texto"].startswith("Não entendi")


# --- leitura com o Claude (sem rede) ---------------------------------------

def test_normalizar():
    from caixa_api.robo.extracao import normalizar
    n = normalizar(pedido("03273-2/26", "SB", [("2026-11-15", "4.279,00"), ("15/11/2026", "4279.00")],
                         total="8558.00"))
    assert n["pedido"]["numero_pedido"] == "PC 03273-2/26" and n["pedido"]["numero_nf"] == "13001"
    assert n["pedido"]["duplicatas"][0] == {"vencimento": "2026-11-15", "valor": "4279.00"}
    assert n["pedido"]["duplicatas"][1]["vencimento"] is None and "duplicatas.2.vencimento" in n["ilegiveis"]
    assert normalizar({"tipo_documento": "xpto"})["tipo_documento"] == "outro"


class _ClienteFalso:
    def __init__(self, resposta):
        self.resposta = resposta
        self.pedidos = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.pedidos.append(kw)
        return self.resposta


def test_extrator_claude_monta_o_pedido_certo():
    import json
    from caixa_api.robo.extracao import ESQUEMA, ErroExtracao, ExtratorClaude
    bruto = pix("4107.84")
    resp = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(bruto))])
    cli = _ClienteFalso(resp)
    lido = ExtratorClaude(cli).extrair(b"%PDF-1.7 ...", "application/pdf")
    assert lido["comprovante"]["valor"] == "4107.84"
    kw = cli.pedidos[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": ESQUEMA}}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["messages"][0]["content"][0]["type"] == "document"
    assert "thinking" not in kw and "temperature" not in kw

    recusa = SimpleNamespace(stop_reason="refusal", content=[])
    with pytest.raises(ErroExtracao):
        ExtratorClaude(_ClienteFalso(recusa)).extrair(b"\x89PNG", "image/png")
    with pytest.raises(ErroExtracao):
        ExtratorClaude(cli).extrair(b"...", "image/heic")


def test_telegram_laco_guarda_onde_parou(bot, telegram, sql):
    class Fim(Exception):
        pass
    lotes = [[_msg(CHAT_DONO, text="/ajuda") | {"update_id": 41}, _msg("777", text="oi") | {"update_id": 42}]]

    def atualizacoes(offset, espera=50):
        if not lotes:
            raise Fim
        assert offset == 0
        return lotes.pop()
    telegram.atualizacoes = atualizacoes
    with pytest.raises(Fim):
        bot.rodar()
    assert sql.execute("select valor from parametro where chave = 'telegram_offset'").fetchone()[0] == "43"
    assert len(telegram.enviadas) == 1 and telegram.enviadas[0]["texto"].startswith("Mande a foto")
