"""Operações: leitura, lançamento na ordem de validação, edição, estorno."""
import pytest


def nova(**kw):
    base = {"fornecedor_id": 2, "numero_pedido": "PC 03400-0/26", "numero_nf": "13000",
            "data_pedido": "2026-11-10", "data_pagamento": "2026-11-12",
            "valor_pago": "9600.00", "valor_cheio": "10000.00", "observacoes": "teste",
            "duplicatas": [{"valor": "3333.34", "vencimento": "2026-12-22"},
                           {"valor": "3333.33", "vencimento": "2026-12-12"},
                           {"valor": "3333.33", "vencimento": "2027-01-02"}]}
    base.update(kw)
    return base


def erro(r):
    return r.status_code, r.json()["erro"]["codigo"]


def test_obter_igual_ao_exemplo_da_especificacao(api):
    j = api.get("/operacoes/7", como="leitura").json()
    assert j["fornecedor"] == {"id": 2, "nome": "SB Indústria e Comércio de Papel"}
    assert {k: j[k] for k in ("numero_pedido", "numero_nf", "data_pagamento", "valor_pago", "valor_cheio",
                              "lucro", "retorno", "desconto", "prazo_medio_dias", "taxa_mes", "lucro_mes_reais")} == {
        "numero_pedido": "PC 03273-2/26", "numero_nf": "12893", "data_pagamento": "2026-10-19",
        "valor_pago": "4107.84", "valor_cheio": "4279.00", "lucro": "171.16", "retorno": "0.041667",
        "desconto": "0.040000", "prazo_medio_dias": "27.0", "taxa_mes": "0.046402", "lucro_mes_reais": "190.61"}
    assert j["duplicatas"][0]["vencimento"] == "2026-11-15"
    assert api.get("/operacoes/999").json()["erro"]["codigo"] == "nao_encontrado"


def test_listar_e_filtrar(api):
    j = api.get("/operacoes").json()
    assert j["total"] == 7 and [o["id"] for o in j["itens"]][:2] == [7, 6]
    assert {o["id"] for o in api.get("/operacoes", params={"estado": "encerrada"}).json()["itens"]} == {1, 2, 3}
    assert {o["id"] for o in api.get("/operacoes", params={"estado": "parcial"}).json()["itens"]} == {4, 5}
    assert {o["id"] for o in api.get("/operacoes", params={"q": "acoplado"}).json()["itens"]} == {3, 6, 7}
    assert api.get("/operacoes", params={"fornecedor_id": 1, "por_pagina": 2}).json()["total"] == 4
    assert len(api.get("/operacoes", params={"fornecedor_id": 1, "por_pagina": 2}).json()["itens"]) == 2
    assert api.get("/operacoes", params={"estado": "xpto"}).status_code == 422


def test_lancar(api, sql):
    r = api.post("/operacoes", json=nova())
    assert r.status_code == 201, r.json()
    j = r.json()
    # a sequência é do servidor, por vencimento
    assert [(d["sequencia"], d["vencimento"], d["valor"]) for d in j["duplicatas"]] == [
        (1, "2026-12-12", "3333.33"), (2, "2026-12-22", "3333.34"), (3, "2027-01-02", "3333.33")]
    assert j["estado"] == "em_aberto" and j["retorno"] == "0.041667" and j["origem"] == "manual"
    assert api.get("/resumo").json()["caixa"] == "102210.32"
    # quem lançou fica no log
    quem = sql.execute("select usuario_id from evento where entidade = 'operacao' and entidade_id = %s",
                       (j["id"],)).fetchone()[0]
    assert quem == sql.execute("select id from usuario where papel = 'operador'").fetchone()[0]


@pytest.mark.parametrize("mudanca,esperado", [
    ({"fornecedor_id": 99}, (422, "validacao")),                                         # 1
    ({"valor_pago": "0.00"}, (422, "validacao")),                                        # 2
    ({"valor_pago": "10000.01"}, (422, "validacao")),                                    # 3 RN-02
    ({"duplicatas": []}, (422, "validacao")),                                            # 4
    ({"valor_cheio": "10000.01", "valor_pago": "9600.00"}, (422, "soma_duplicatas")),    # 5 RN-01
    ({"duplicatas": [{"valor": "10000.00", "vencimento": "2025-12-12"}]}, (422, "validacao")),  # 6 A-02
    ({"duplicatas": [{"valor": "10000.00", "vencimento": "2027-11-13"}]}, (422, "validacao")),  # 6 > 365 dias
    ({"valor_pago": "9999.99", "valor_cheio": "200000.00",
      "duplicatas": [{"valor": "200000.00", "vencimento": "2026-12-12"}]}, (201, None)),
    ({"valor_pago": "111810.33", "valor_cheio": "200000.00",
      "duplicatas": [{"valor": "200000.00", "vencimento": "2026-12-12"}]}, (422, "caixa_insuficiente")),  # 7
    ({"valor_pago": 9600}, (422, "validacao")),                      # dinheiro como número JSON: recusado
    ({"valor_pago": "9600,00"}, (422, "validacao")),                 # vírgula: recusado
])
def test_validacoes_do_lancamento(api, mudanca, esperado):
    r = api.post("/operacoes", json=nova(**mudanca))
    if esperado[0] == 201:
        assert r.status_code == 201, r.json()
    else:
        assert erro(r) == esperado, r.json()


def test_caixa_insuficiente_diz_quanto_ha(api):
    r = api.post("/operacoes", json=nova(valor_pago="120000.00", valor_cheio="130000.00",
                                         duplicatas=[{"valor": "130000.00", "vencimento": "2026-12-12"}]))
    e = r.json()["erro"]
    assert e["codigo"] == "caixa_insuficiente"
    assert e["mensagem"].startswith("Caixa insuficiente: você tem R$ 111.810,32 livre.")
    assert e["detalhe"] == {"disponivel": "111810.32", "solicitado": "120000.00"}


def test_soma_duplicatas_mostra_a_diferenca(api):
    r = api.post("/operacoes", json=nova(duplicatas=[{"valor": "9999.99", "vencimento": "2026-12-12"}]))
    assert r.json()["erro"]["detalhe"] == {"soma_duplicatas": "9999.99", "valor_cheio": "10000.00",
                                           "diferenca": "0.01"}


def test_pedido_repetido_e_conflito(api):
    assert erro(api.post("/operacoes", json=nova(numero_pedido="PC 03273-2/26"))) == (409, "conflito")


def test_idempotencia(api):
    h = {"Idempotency-Key": "f3c1d6a2-0000-4000-8000-000000000001"}
    r1 = api.post("/operacoes", json=nova(), headers=h)
    r2 = api.post("/operacoes", json=nova(), headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.headers.get("idempotent-replay") == "true"
    assert api.get("/resumo").json()["caixa"] == "102210.32"          # só uma compra saiu do caixa
    # mesma chave em outra rota: conflito
    r3 = api.post("/movimentos", json={"tipo": "aporte", "data": "2026-11-12", "valor": "1.00"}, headers=h)
    assert erro(r3) == (409, "conflito")


def test_alterar_troca_duplicatas_e_renumera(api):
    op = api.post("/operacoes", json=nova()).json()
    d1, d2, d3 = op["duplicatas"]
    # muda o vencimento da 1ª para depois da 3ª, apaga a 2ª e acrescenta uma nova
    r = api.patch(f"/operacoes/{op['id']}", json={"duplicatas": [
        {"id": d1["id"], "valor": "3333.33", "vencimento": "2027-01-10"},
        {"id": d3["id"], "valor": "3333.33", "vencimento": "2027-01-02"},
        {"valor": "3333.34", "vencimento": "2026-12-01"}]})
    assert r.status_code == 200, r.json()
    ds = r.json()["duplicatas"]
    assert [(d["sequencia"], d["vencimento"]) for d in ds] == [(1, "2026-12-01"), (2, "2027-01-02"), (3, "2027-01-10")]
    assert ds[2]["id"] == d1["id"] and ds[1]["id"] == d3["id"]
    assert r.json()["avisos"] == []


def test_alterar_duplicata_recebida(api):
    # op 4: duplicata 6 recebida, 7 em aberto
    base = [{"id": 6, "valor": "12975.90", "vencimento": "2026-10-16"},
            {"id": 7, "valor": "12975.90", "vencimento": "2026-10-26"}]
    mudou_valor = [{**base[0], "valor": "12975.89"}, {**base[1], "valor": "12975.91"}]
    assert erro(api.patch("/operacoes/4", json={"duplicatas": mudou_valor})) == (422, "validacao")
    assert erro(api.patch("/operacoes/4", json={"duplicatas": [
        {"valor": "25951.80", "vencimento": "2026-10-26"}]})) == (422, "validacao")      # recebida sumiu
    r = api.patch("/operacoes/4", json={"duplicatas": [{**base[0], "vencimento": "2026-10-17"}, base[1]]})
    assert r.status_code == 200 and len(r.json()["avisos"]) == 1                          # vencimento: com aviso


def test_alterar_revalida_caixa_na_edicao(api):
    # caixa 111.810,32. A op 7 (paga 4.107,84) pode subir até 4.107,84 + caixa
    r = api.patch("/operacoes/7", json={"valor_pago": "4279.00"})
    assert r.status_code == 200 and r.json()["lucro"] == "0.00"
    assert erro(api.patch("/operacoes/7", json={"valor_cheio": "4300.00"})) == (422, "soma_duplicatas")
    api.post("/movimentos", json={"tipo": "retirada", "data": "2026-11-12", "valor": "111639.16"})  # caixa 0
    assert api.get("/resumo").json()["caixa"] == "0.00"
    # baixar o pago devolve caixa: 4.279,00 -> 4.200,00 = R$ 79,00 livre
    assert api.patch("/operacoes/7", json={"valor_pago": "4200.00", "observacoes": "x"}).status_code == 200
    assert api.get("/resumo").json()["caixa"] == "79.00"
    # op 4: paga 24.864,00, já recebeu 12.975,90. Pode subir exatamente até 24.864,00 + 79,00:
    # o que ela já recebeu continua no caixa depois da edição, então não reduz o limite
    r = api.patch("/operacoes/4", json={"valor_pago": "24943.01"})
    assert erro(r) == (422, "caixa_insuficiente"), r.json()
    assert r.json()["erro"]["detalhe"] == {"disponivel": "24943.00", "solicitado": "24943.01"}
    assert api.patch("/operacoes/4", json={"valor_pago": "24943.00"}).status_code == 200
    assert api.get("/resumo").json()["caixa"] == "0.00"


def test_estorno(api):
    r = api.post("/operacoes/5/estorno", json={"motivo": "Pedido cancelado pelo fornecedor"})
    assert r.status_code == 200 and r.json()["estado"] == "estornada"
    assert api.get("/operacoes").json()["total"] == 6                       # sai dos cálculos
    assert api.get("/operacoes", params={"estado": "estornada"}).json()["total"] == 1
    # caixa: sai o efeito da op 5 (−32.313,60 pago, +16.863,66 recebido)
    assert api.get("/resumo").json()["caixa"] == "127260.26"
    assert erro(api.post("/operacoes/5/estorno", json={"motivo": "de novo"})) == (409, "conflito")
    assert erro(api.patch("/operacoes/5", json={"observacoes": "x"})) == (409, "conflito")
    assert erro(api.post("/duplicatas/9/receber", json={})) == (409, "conflito")


def test_excluir(api):
    assert erro(api.delete("/operacoes/4")) == (409, "conflito")           # tem recebimento: estorno
    assert api.delete("/operacoes/7").status_code == 204
    j = api.get("/operacoes/7").json()
    assert j["situacao"] == "estornada" and j["estorno_motivo"] == "Excluída"   # lógico, nada apagado
