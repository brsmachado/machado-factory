"""docs/04-api.md §6 — fornecedores.

`observacoes` aparece como aviso na tela de lançamento: é a memória das
armadilhas (ex.: "lança o desconto na própria nota — conferir soma dos itens").
`desconto_padrao` é só sugestão de preenchimento (A-05).
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from .. import fmt
from ..auth import Usuario, pode_lancar, pode_ler
from ..erros import ErroAPI
from ..escrita import executar

r = APIRouter(tags=["fornecedores"])


def _cnpj(v: Optional[str]) -> Optional[str]:
    if v is None or not v.strip():
        return None
    s = re.sub(r"[.\-/\s]", "", v)
    if not re.fullmatch(r"\d{14}", s):
        raise ValueError("CNPJ precisa ter 14 dígitos")
    # dígitos verificadores
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(c) * p for c, p in zip(s[:n], pesos))
        dv = 0 if soma % 11 < 2 else 11 - soma % 11
        if int(s[n]) != dv:
            raise ValueError("CNPJ inválido (dígito verificador não confere)")
    return s


class FornecedorDados(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2, max_length=200)
    cnpj: Optional[str] = None
    chave_pix: Optional[str] = Field(default=None, max_length=200)
    desconto_padrao: Optional[fmt.Fracao] = None
    prazo_padrao: Optional[str] = Field(default=None, max_length=40, pattern=r"^\d{1,3}(/\d{1,3})*$")
    observacoes: Optional[str] = Field(default=None, max_length=2000)
    ativo: Optional[bool] = None

    _v_cnpj = field_validator("cnpj")(lambda cls, v: _cnpj(v))


CAMPOS = ("nome", "cnpj", "chave_pix", "desconto_padrao", "prazo_padrao", "observacoes", "ativo")


def _json(f: dict) -> dict:
    return {"id": f["id"], "nome": f["nome"], "cnpj": f["cnpj"], "chave_pix": f["chave_pix"],
            "desconto_padrao": fmt.taxa(f["desconto_padrao"], 4), "prazo_padrao": f["prazo_padrao"],
            "observacoes": f["observacoes"], "ativo": f["ativo"]}


@r.get("/fornecedores")
def listar(request: Request, u: Usuario = Depends(pode_ler), inativos: bool = False):
    linhas = request.app.state.banco.todos(
        "select * from fornecedor where ativo or %s order by nome", (inativos,))
    return {"itens": [_json(f) for f in linhas]}


@r.get("/fornecedores/{forn_id}")
def obter(forn_id: int, request: Request, u: Usuario = Depends(pode_ler)):
    f = request.app.state.banco.um("select * from fornecedor where id = %s", (forn_id,))
    if not f:
        raise ErroAPI("nao_encontrado", f"Fornecedor {forn_id} não existe")
    return _json(f)


@r.post("/fornecedores", status_code=201)
def criar(dados: FornecedorDados, request: Request, u: Usuario = Depends(pode_lancar)):
    if not dados.nome:
        raise ErroAPI("validacao", "nome: obrigatório", {"campo": "nome"})

    def fn(cur, arqs):
        cur.execute("""insert into fornecedor (nome, cnpj, chave_pix, desconto_padrao, prazo_padrao, observacoes, ativo)
                       values (%s, %s, %s, %s, %s, %s, coalesce(%s, true)) returning *""",
                    tuple(getattr(dados, c) for c in CAMPOS))
        return _json(cur.fetchone())
    return executar(request, u, "POST /fornecedores", fn, status=201)


@r.patch("/fornecedores/{forn_id}")
def alterar(forn_id: int, dados: FornecedorDados, request: Request, u: Usuario = Depends(pode_lancar)):
    campos = [c for c in CAMPOS if c in dados.model_fields_set]
    if "nome" in campos and not dados.nome:
        raise ErroAPI("validacao", "nome: não pode ficar vazio", {"campo": "nome"})
    if "ativo" in campos and dados.ativo is None:
        raise ErroAPI("validacao", "ativo: true ou false", {"campo": "ativo"})

    def fn(cur, arqs):
        if campos:
            sets = ", ".join(f"{c} = %s" for c in campos)
            cur.execute(f"update fornecedor set {sets} where id = %s returning *",
                        [getattr(dados, c) for c in campos] + [forn_id])
        else:
            cur.execute("select * from fornecedor where id = %s", (forn_id,))
        f = cur.fetchone()
        if not f:
            raise ErroAPI("nao_encontrado", f"Fornecedor {forn_id} não existe")
        return _json(f)
    return executar(request, u, f"PATCH /fornecedores/{forn_id}", fn)
