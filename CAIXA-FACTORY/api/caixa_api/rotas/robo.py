"""docs/04-api.md §9 — o robô pela API (para a tela e para quem não usa o Telegram)."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel, Field

from .. import fmt
from ..auth import Usuario, pode_lancar, pode_ler, usuario_atual
from ..erros import ErroAPI
from ..escrita import executar
from ..robo import rascunhos

r = APIRouter(prefix="/robo", tags=["robô"])


def pode_robo(u: Usuario = Depends(usuario_atual)) -> Usuario:
    """O robô (token de serviço) ou uma pessoa que lança. Leitura não."""
    if not u.robo and u.papel not in ("operador", "admin"):
        raise ErroAPI("sem_permissao", "Seu usuário é só de leitura")
    return u


class Correcoes(BaseModel):
    """Os mesmos campos do POST /operacoes, todos opcionais. Dinheiro como string."""
    fornecedor_id: Optional[int] = None
    numero_pedido: Optional[str] = Field(default=None, max_length=60)
    numero_nf: Optional[str] = Field(default=None, max_length=60)
    data_pedido: Optional[str] = None
    data_pagamento: Optional[str] = None
    valor_pago: Optional[str] = None
    valor_cheio: Optional[str] = None
    duplicatas: Optional[list[dict]] = None
    observacoes: Optional[str] = Field(default=None, max_length=2000)

    def mudancas(self) -> dict:
        return {k: getattr(self, k) for k in self.model_fields_set}


class Motivo(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=500)


class Juntar(BaseModel):
    com: int


@r.post("/ingestao")
def ingestao(request: Request, arquivos: list[UploadFile] = File(...), u: Usuario = Depends(pode_robo)):
    """Recebe pedidos e comprovantes; devolve o rascunho de cada um. Mandar o
    mesmo arquivo duas vezes não cria dois rascunhos (casamento pelo sha256)."""
    if len(arquivos) > 10:
        raise ErroAPI("validacao", "No máximo 10 arquivos por vez")
    robo = request.app.state.robo
    limite = request.app.state.cfg.max_upload_bytes
    resultados = []
    for arq in arquivos:
        conteudo = arq.file.read(limite + 1)
        try:
            res = robo.receber_documento(conteudo, u.id)
            resultados.append({"arquivo": arq.filename, "ok": True, **res})
        except ErroAPI as e:     # um arquivo ruim não derruba os outros
            resultados.append({"arquivo": arq.filename, "ok": False,
                               "erro": {"codigo": e.codigo, "mensagem": e.mensagem, "detalhe": e.detalhe}})
    return {"resultados": resultados}


@r.get("/rascunhos")
def listar(request: Request, u: Usuario = Depends(pode_ler),
           estado: Optional[str] = Query(default="pendente", pattern="^(pendente|aprovado|descartado|todos)$")):
    with request.app.state.banco.transacao() as cur:
        return {"itens": rascunhos.listar(cur, None if estado == "todos" else estado)}


@r.get("/rascunhos/{rid}")
def obter(rid: int, request: Request, u: Usuario = Depends(pode_ler)):
    with request.app.state.banco.transacao() as cur:
        return rascunhos.obter(cur, rid)


@r.patch("/rascunhos/{rid}")
def corrigir(rid: int, dados: Correcoes, request: Request, u: Usuario = Depends(pode_lancar)):
    return executar(request, u, f"PATCH /robo/rascunhos/{rid}",
                    lambda cur, arqs: rascunhos.corrigir(cur, rid, dados.mudancas()))


@r.post("/rascunhos/{rid}/aprovar", status_code=201)
def aprovar(rid: int, request: Request, dados: Optional[Correcoes] = None, u: Usuario = Depends(pode_lancar)):
    """Confirma, opcionalmente com correções. Só pessoa: o robô não aprova."""
    return executar(request, u, f"POST /robo/rascunhos/{rid}/aprovar",
                    lambda cur, arqs: rascunhos.aprovar(cur, arqs, rid, dados.mudancas() if dados else None),
                    status=201, idempotente=True)


@r.post("/rascunhos/{rid}/descartar")
def descartar(rid: int, request: Request, dados: Optional[Motivo] = None, u: Usuario = Depends(pode_lancar)):
    return executar(request, u, f"POST /robo/rascunhos/{rid}/descartar",
                    lambda cur, arqs: rascunhos.descartar(cur, rid, dados.motivo if dados else None))


@r.post("/rascunhos/{rid}/juntar")
def juntar(rid: int, dados: Juntar, request: Request, u: Usuario = Depends(pode_lancar)):
    """Junta o pedido de um rascunho com o comprovante de outro (quando o robô ficou na dúvida)."""
    return executar(request, u, f"POST /robo/rascunhos/{rid}/juntar",
                    lambda cur, arqs: rascunhos.juntar(cur, rid, dados.com))


@r.post("/conciliacao")
def conciliacao(request: Request, u: Usuario = Depends(pode_robo),
                enviar: bool = True, forcar: bool = False):
    """O aviso do dia (o cron chama às 9h). Manda no Telegram se estiver configurado."""
    res = request.app.state.robo.aviso(enviar=enviar, forcar=forcar)
    return {"texto": res["texto"], "enviado": res["enviado"], "alerta_id": res["alerta_id"],
            "botoes": [[{"texto": t, "acao": d} for t, d in linha] for linha in res["botoes"]]}


@r.get("/alertas")
def alertas(request: Request, u: Usuario = Depends(pode_ler), todos: bool = False):
    linhas = request.app.state.banco.todos(
        "select * from alerta where %s or baixado_em is null order by criado_em desc limit 100", (todos,))
    return {"itens": [{"id": a["id"], "tipo": a["tipo"], "mensagem": a["mensagem"], "valor": fmt.dinheiro(a["valor"]),
                       "dias": a["dias"], "dia": fmt.data_iso(a["dia"]), "criado_em": a["criado_em"].isoformat(),
                       "baixado_em": a["baixado_em"].isoformat() if a["baixado_em"] else None} for a in linhas]}


@r.post("/alertas/{aid}/baixar", status_code=204)
def baixar(aid: int, request: Request, u: Usuario = Depends(pode_lancar)):
    def fn(cur, arqs):
        cur.execute("update alerta set baixado_em = coalesce(baixado_em, now()) where id = %s returning id", (aid,))
        if not cur.fetchone():
            raise ErroAPI("nao_encontrado", f"Alerta {aid} não existe")
        return None
    return executar(request, u, f"POST /robo/alertas/{aid}/baixar", fn)
