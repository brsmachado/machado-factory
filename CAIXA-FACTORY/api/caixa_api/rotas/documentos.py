"""docs/04-api.md §7 — documentos (pedidos e comprovantes)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from .. import fmt
from ..auth import Usuario, pode_lancar, pode_ler
from ..documentos import Arquivos, salvar
from ..erros import ErroAPI
from ..escrita import executar

r = APIRouter(tags=["documentos"])


def _json(d: dict) -> dict:
    return {"id": d["id"], "operacao_id": d["operacao_id"], "tipo": d["tipo"],
            "nome_arquivo": d["nome_arquivo"], "mime": d["mime"], "bytes": d["bytes"],
            "sha256": d["sha256"], "data_doc": fmt.data_iso(d["data_doc"]),
            "enviado_em": d["enviado_em"].isoformat()}


@r.post("/documentos", status_code=201)
def enviar(request: Request,
           arquivo: UploadFile = File(...),
           tipo: Literal["pedido_compra", "comprovante_pix", "nota_fiscal", "outro"] = Form(...),
           operacao_id: Optional[int] = Form(default=None),
           data_doc: Optional[date] = Form(default=None),
           u: Usuario = Depends(pode_lancar)):
    limite = request.app.state.cfg.max_upload_bytes
    conteudo = arquivo.file.read(limite + 1)
    if len(conteudo) > limite:
        raise ErroAPI("validacao", f"Arquivo maior que {limite // (1024 * 1024)} MB")
    if not conteudo:
        raise ErroAPI("validacao", "Arquivo vazio")
    def fn(cur, arqs):
        novo, d = salvar(cur, arqs, conteudo, tipo, operacao_id=operacao_id, data_doc=data_doc)
        return (201 if novo else 200), _json(d)   # mesmo arquivo de novo: o que já existe

    return executar(request, u, "POST /documentos", fn, status=201)


@r.get("/documentos/{doc_id}")
def obter(doc_id: int, request: Request, u: Usuario = Depends(pode_ler)):
    d = request.app.state.banco.um("select * from documento where id = %s", (doc_id,))
    if not d:
        raise ErroAPI("nao_encontrado", f"Documento {doc_id} não existe")
    return _json(d)


@r.get("/documentos/{doc_id}/arquivo")
def arquivo(doc_id: int, request: Request, u: Usuario = Depends(pode_ler)):
    d = request.app.state.banco.um("select * from documento where id = %s", (doc_id,))
    if not d:
        raise ErroAPI("nao_encontrado", f"Documento {doc_id} não existe")
    p = Arquivos(request.app.state.cfg.documentos_dir).absoluto(d["caminho"])
    if not p.is_file():
        raise ErroAPI("nao_encontrado", "O arquivo deste documento não está na pasta de documentos")
    return FileResponse(p, media_type=d["mime"] or "application/octet-stream",
                        content_disposition_type="inline", filename=d["nome_arquivo"],
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"})
