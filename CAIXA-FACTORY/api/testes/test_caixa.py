"""Recebimentos, movimentos, fornecedores, documentos, login e permissões."""
import hashlib

import pytest


def erro(r):
    return r.status_code, r.json()["erro"]["codigo"]


# --- recebimentos ----------------------------------------------------------

def test_receber_e_desfazer(api, sql):
    r = api.post("/duplicatas/11/receber", json={"data": "2026-11-15"})
    assert r.status_code == 200 and r.json()["estado"] == "encerrada"
    assert api.get("/resumo").json()["caixa"] == "116089.32"
    assert erro(api.post("/duplicatas/11/receber", json={})) == (409, "conflito")
    r = api.delete("/duplicatas/11/receber")
    assert r.status_code == 200 and r.json()["duplicatas"][0]["recebida_em"] is None
    assert api.get("/resumo").json()["caixa"] == "111810.32"
    acoes = [a for (a,) in sql.execute("select acao from evento where entidade = 'duplicata' and entidade_id = 11 "
                                       "order by id")]
    assert acoes[-2:] == ["recebeu", "desfez"]


def test_receber_valida_datas(api):
    assert erro(api.post("/duplicatas/11/receber", json={"data": "2026-10-18"})) == (422, "validacao")   # RN-04
    assert erro(api.post("/duplicatas/11/receber", json={"data": "2099-01-01"})) == (422, "validacao")   # futuro
    assert api.post("/duplicatas/11/receber", json={"data": "2026-10-19"}).status_code == 200            # antecipação


def test_receber_sem_data_usa_hoje(api):
    r = api.post("/duplicatas/11/receber")
    assert r.status_code == 200 and r.json()["duplicatas"][0]["recebida_em"] is not None


def test_receber_lote_tudo_ou_nada(api):
    r = api.post("/duplicatas/receber-lote", json={"itens": [{"id": 7, "data": "2026-10-26"},
                                                             {"id": 11, "data": "2026-10-01"}]})  # 2ª antes do PIX
    assert erro(r) == (422, "validacao")
    assert api.get("/resumo").json()["caixa"] == "111810.32"                 # a 1ª também não entrou
    r = api.post("/duplicatas/receber-lote", json={"itens": [{"id": 7, "data": "2026-10-26"},
                                                             {"id": 9, "data": "2026-10-26"}]})
    assert r.status_code == 200 and r.json()["recebidas"] == [7, 9]
    assert api.get("/resumo").json()["caixa"] == "141649.88"
    assert erro(api.post("/duplicatas/receber-lote", json={"itens": [{"id": 10}, {"id": 10}]})) == (422, "validacao")


# --- movimentos ------------------------------------------------------------

def test_aporte_e_retirada(api):
    assert api.post("/movimentos", json={"tipo": "aporte", "data": "2026-11-12", "valor": "1000.00"}).status_code == 201
    r = api.post("/movimentos", json={"tipo": "retirada", "data": "2026-11-12", "valor": "112810.33"})
    assert erro(r) == (422, "caixa_insuficiente")
    assert r.json()["erro"]["detalhe"]["disponivel"] == "112810.32"
    assert api.post("/movimentos", json={"tipo": "retirada", "data": "2026-11-12", "valor": "112810.32"}).status_code == 201
    assert api.get("/resumo").json()["caixa"] == "0.00"
    assert len(api.get("/movimentos").json()["itens"]) == 4


def test_excluir_movimento_olha_a_linha_do_tempo(api):
    # os dois aportes já foram usados em compras: nenhum pode sair
    assert erro(api.delete("/movimentos/1")) == (422, "caixa_insuficiente")
    assert erro(api.delete("/movimentos/2")) == (422, "caixa_insuficiente")
    novo = api.post("/movimentos", json={"tipo": "aporte", "data": "2026-11-12", "valor": "500.00"}).json()
    assert api.delete(f"/movimentos/{novo['id']}").status_code == 204
    ret = api.post("/movimentos", json={"tipo": "retirada", "data": "2026-11-12", "valor": "10.00"}).json()
    assert api.delete(f"/movimentos/{ret['id']}").status_code == 204       # tirar retirada sempre pode
    assert api.get("/resumo").json()["caixa"] == "111810.32"


# --- fornecedores ----------------------------------------------------------

def test_fornecedores(api):
    r = api.patch("/fornecedores/2", json={
        "cnpj": "26.107.828/0001-37", "chave_pix": "pix@exemplo.invalid", "desconto_padrao": "0.0400",
        "prazo_padrao": "30", "observacoes": "Lança o desconto na própria nota (A-01)"})
    assert r.status_code == 200, r.json()
    assert (r.json()["cnpj"], r.json()["desconto_padrao"]) == ("26107828000137", "0.0400")
    assert erro(api.patch("/fornecedores/1", json={"cnpj": "26107828000138"})) == (422, "validacao")
    assert erro(api.patch("/fornecedores/1", json={"cnpj": "26107828000137"})) == (409, "conflito")
    assert erro(api.patch("/fornecedores/1", json={"desconto_padrao": 0.04})) == (422, "validacao")
    novo = api.post("/fornecedores", json={"nome": "Fornecedor Novo", "prazo_padrao": "28/35/42"})
    assert novo.status_code == 201
    api.patch(f"/fornecedores/{novo.json()['id']}", json={"ativo": False})
    assert len(api.get("/fornecedores").json()["itens"]) == 2
    assert len(api.get("/fornecedores", params={"inativos": True}).json()["itens"]) == 3
    r = api.post("/operacoes", json={"fornecedor_id": novo.json()["id"], "numero_pedido": "X", "data_pagamento": "2026-11-12",
                                     "valor_pago": "1.00", "valor_cheio": "1.00",
                                     "duplicatas": [{"valor": "1.00", "vencimento": "2026-12-12"}]})
    assert erro(r) == (422, "validacao") and "inativo" in r.json()["erro"]["mensagem"]


# --- documentos ------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


def enviar(api, conteudo, tipo="comprovante_pix", nome="foto.png", **campos):
    return api.post("/documentos", files={"arquivo": (nome, conteudo, "application/octet-stream")},
                    data={"tipo": tipo, **{k: str(v) for k, v in campos.items()}})


def test_documento_com_operacao(api, docs_dir):
    r = enviar(api, PDF, nome="qualquer.png", operacao_id=7, data_doc="2026-10-19")
    assert r.status_code == 201, r.json()
    j = r.json()
    assert j["nome_arquivo"] == "2026-10-19_PC-03273-2-26_comprovante-pix.pdf"     # tipo real: pdf
    assert j["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert (docs_dir / "operacoes/2026-10" / j["nome_arquivo"]).read_bytes() == PDF
    # o mesmo arquivo de novo: 200 com o mesmo documento, nada duplicado
    r2 = enviar(api, PDF, operacao_id=7, data_doc="2026-10-19")
    assert r2.status_code == 200 and r2.json()["id"] == j["id"]
    b = api.get(f"/documentos/{j['id']}/arquivo", como="leitura")
    assert b.status_code == 200 and b.content == PDF and b.headers["content-disposition"].startswith("inline")
    assert api.get("/operacoes/7").json()["documentos"][0]["id"] == j["id"]


def test_documento_vinculado_depois_e_renomeado(api, docs_dir):
    j = enviar(api, PNG, tipo="pedido_compra", data_doc="2026-11-10").json()
    assert j["nome_arquivo"] == "2026-11-10_SEM-PEDIDO_pedido-compra.png"
    op = api.post("/operacoes", json={
        "fornecedor_id": 1, "numero_pedido": "PC 03500-1/26", "data_pagamento": "2026-11-12",
        "valor_pago": "970.00", "valor_cheio": "1000.00", "documento_ids": [j["id"]],
        "duplicatas": [{"valor": "1000.00", "vencimento": "2026-12-12"}]}).json()
    doc = op["documentos"][0]
    assert doc["nome_arquivo"] == "2026-11-10_PC-03500-1-26_pedido-compra.png"
    pasta = docs_dir / "operacoes/2026-11"
    assert sorted(p.name for p in pasta.iterdir()) == ["2026-11-10_PC-03500-1-26_pedido-compra.png"]
    assert api.get(f"/documentos/{j['id']}/arquivo").content == PNG
    # o mesmo documento não pode ir para outra operação
    r = api.patch("/operacoes/7", json={"documento_ids": [j["id"]]})
    assert erro(r) == (409, "conflito")


def test_documento_falha_nao_deixa_arquivo(api, docs_dir):
    j = enviar(api, PNG, tipo="pedido_compra", data_doc="2026-11-10").json()
    r = api.post("/operacoes", json={   # caixa insuficiente: a transação desfaz, o nome antigo fica
        "fornecedor_id": 1, "numero_pedido": "PC 03500-2/26", "data_pagamento": "2026-11-12",
        "valor_pago": "999999.00", "valor_cheio": "999999.00", "documento_ids": [j["id"]],
        "duplicatas": [{"valor": "999999.00", "vencimento": "2026-12-12"}]})
    assert erro(r) == (422, "caixa_insuficiente")
    assert sorted(p.name for p in (docs_dir / "operacoes/2026-11").iterdir()) == ["2026-11-10_SEM-PEDIDO_pedido-compra.png"]


def test_documento_tipo_pelo_conteudo(api):
    r = enviar(api, b"<html><script>alert(1)</script>", nome="comprovante.pdf")
    assert erro(r) == (422, "validacao")
    assert erro(enviar(api, PNG, operacao_id=999)) == (422, "validacao")


# --- login e permissões ----------------------------------------------------

def test_sem_login(api):
    assert erro(api.get("/resumo", como=None)) == (401, "nao_autenticado")
    r = api.tc.get("/api/v1/resumo", headers={"Authorization": "Bearer inventado"})
    assert erro(r) == (401, "nao_autenticado")


def test_login_e_logout(api):
    from conftest import SENHA
    r = api.tc.post("/api/v1/auth/entrar", json={"email": "Leitura@teste.invalid", "senha": SENHA})
    assert r.status_code == 200
    tok = r.json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert api.tc.get("/api/v1/auth/eu", headers=h).json()["papel"] == "leitura"
    assert api.tc.post("/api/v1/auth/sair", headers=h).status_code == 204
    assert api.tc.get("/api/v1/auth/eu", headers=h).status_code == 401
    r = api.tc.post("/api/v1/auth/entrar", json={"email": "leitura@teste.invalid", "senha": "errada"})
    assert erro(r) == (401, "nao_autenticado")
    r2 = api.tc.post("/api/v1/auth/entrar", json={"email": "ninguem@teste.invalid", "senha": "errada"})
    assert r2.json()["erro"]["mensagem"] == r.json()["erro"]["mensagem"]       # não revela se o e-mail existe


@pytest.mark.parametrize("metodo,url,corpo", [
    ("post", "/operacoes", {}),
    ("post", "/duplicatas/11/receber", {}),
    ("post", "/movimentos", {"tipo": "aporte", "data": "2026-11-12", "valor": "1.00"}),
    ("post", "/operacoes/7/estorno", {"motivo": "teste"}),
    ("delete", "/operacoes/7", None),
    ("patch", "/fornecedores/1", {"nome": "X"}),
])
@pytest.mark.parametrize("como", ["leitura", "robo"])
def test_leitura_e_robo_nao_gravam(api, metodo, url, corpo, como):
    kw = {"json": corpo} if corpo is not None else {}
    r = getattr(api, metodo)(url, como=como, **kw)
    assert erro(r) == (403, "sem_permissao"), r.json()


def test_robo_le(api):
    assert api.get("/agenda", como="robo").status_code == 200
    assert api.get("/auth/eu", como="robo").json()["robo"] is True
