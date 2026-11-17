"""Resumo, resultado mensal, agenda, saúde e exportação — conferidos nos dados reais."""
import csv
import io
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]


def test_resumo_bate_com_a_conferencia(api):
    r = api.get("/resumo", como="leitura")
    assert r.status_code == 200
    j = r.json()
    assert {k: j[k] for k in ("caixa", "aplicado", "capital", "a_receber", "lucro_realizado", "lucro_a_receber")} == {
        "caixa": "111810.32", "aplicado": "42032.64", "capital": "153842.96",
        "a_receber": "43843.56", "lucro_realizado": "3842.96", "lucro_a_receber": "1810.92"}
    assert j["duplicatas_abertas"] == 4 and j["operacoes_abertas"] == 4
    rent = j["rentabilidade"]
    assert rent["lucro_mes_reais"] == "4965.73"
    assert rent["taxa_mes"].startswith("0.0326")
    assert rent["ocupacao"].startswith("0.273")
    assert rent["rendimento_caixa_inteiro"].startswith("0.0089")
    # dinheiro e taxa sempre como string (docs/04-api.md §1)
    assert all(isinstance(v, str) for v in rent.values())


def test_resultado_mensal(api):
    meses = {m["mes"]: m for m in api.get("/resultado-mensal").json()["meses"]}
    assert list(meses) == ["2026-08", "2026-09", "2026-10", "2026-11"]
    esperado = {"2026-08": ("249.90", "8936.52", "3966.71", "110.92"),
                "2026-09": ("3200.32", "103260.88", "21739.12", "673.75"),
                "2026-10": ("2108.57", "56379.73", "93620.27", "3501.35"),
                "2026-11": ("95.09", "2053.92", "147946.08", "6849.36")}
    for mes, (lucro, aplic, parado, custo) in esperado.items():
        m = meses[mes]
        assert (m["lucro"], m["aplicado_medio"], m["parado_medio"], m["custo_do_parado"]) == (lucro, aplic, parado, custo)
    assert meses["2026-10"]["capital_medio"] == "150000.00"
    assert meses["2026-10"]["estado"] == "fechado"

    filtrado = api.get("/resultado-mensal", params={"de": "2026-09", "ate": "2026-10"}).json()["meses"]
    assert [m["mes"] for m in filtrado] == ["2026-09", "2026-10"]
    assert api.get("/resultado-mensal", params={"de": "2026-13"}).json()["erro"]["codigo"] == "validacao"


def test_agenda(api):
    j = api.get("/agenda", params={"dias": 3650}).json()
    assert [d["id"] for d in j["duplicatas"]] == [10, 7, 9, 11]       # por vencimento
    assert j["total"] == "43843.56"
    d7 = next(d for d in j["duplicatas"] if d["id"] == 7)
    assert (d7["sequencia"], d7["de"], d7["valor"], d7["numero_pedido"]) == (2, 2, "12975.90", "PC 03295-5/26")


def test_saude_sem_login(api):
    r = api.get("/saude", como=None)
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["integridade"]["identidade_caixa"] == "ok"


def _ler_csv(conteudo: bytes):
    assert conteudo.startswith("﻿".encode())               # BOM para o Excel
    return list(csv.reader(io.StringIO(conteudo.decode("utf-8-sig")), delimiter=";"))


def test_exportar_operacoes_bate_com_a_planilha_de_hoje(api):
    r = api.get("/exportar/operacoes.csv", como="leitura")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    novo = _ler_csv(r.content)
    antigo = _ler_csv((RAIZ / "CAIXA-MACHADO" / "registros" / "operacoes.csv").read_bytes())
    assert novo[0] == antigo[0]                                  # mesmas colunas, mesma ordem
    assert len(novo) == len(antigo) == 12                        # 11 duplicatas + cabeçalho

    def chave(l):   # pedido + parcela
        return l[2].split(" - ")[0], l[11]
    # A planilha antiga traz "Lucro por mes" um pouco diferente nas duas compras
    # da Brislu de 16/09, e nenhuma variação da fórmula de 03-formulas reproduz
    # o número dela. O CSV é espelho e "pode estar um passo atrás"
    # (07-migracao §1); vale a fórmula: pago × taxa_mes.
    divergencia_conhecida = {"PC 03331-1/26": ("1208,25", "1208,03"),
                             "PC 03295-5/26": ("929,68", "929,53")}
    a = {chave(l): l for l in antigo[1:]}
    for l in novo[1:]:
        velho = list(a[chave(l)])
        pedido = chave(l)[0]
        if pedido in divergencia_conhecida:
            assert (velho[10], l[10]) == divergencia_conhecida[pedido]
            velho[10] = l[10]
        # valores, taxas, prazos, parcelas, datas e situação iguais aos da planilha
        assert l[0] == velho[0] and l[3:16] == velho[3:16], (l, velho)


def test_exportar_movimentos(api):
    linhas = _ler_csv(api.get("/exportar/movimentos.csv").content)
    assert linhas[0] == ["Data", "Tipo", "Valor", "Observacoes"]
    assert linhas[1][:3] == ["16/09/2026", "Aporte", "50000,00"]
