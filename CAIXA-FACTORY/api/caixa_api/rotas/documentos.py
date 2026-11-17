"""docs/04-api.md §7 — documentos (pedidos e comprovantes)."""
import hashlib
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from .. import fmt
from ..auth import Usuario, pode_lancar, pode_ler
from ..documentos import Arquivos, detectar, nome_arquivo
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
    tipo_real = detectar(conteudo)       # pelo conteúdo, não pela extensão
    if not tipo_real:
        raise ErroAPI("validacao", "Tipo de arquivo não aceito: envie PDF, PNG, JPG, WEBP ou HEIC")
    ext, mime = tipo_real
    sha = hashlib.sha256(conteudo).hexdigest()

    def fn(cur, arqs):
        cur.execute("select * from documento where sha256 = %s", (sha,))
        existente = cur.fetchone()
        if existente:
            # mesmo arquivo de novo: devolve o que já existe, sem duplicar
            return 200, _json(existente)
        numero_pedido = None
        if operacao_id is not None:
            cur.execute("select numero_pedido from operacao where id = %s", (operacao_id,))
            o = cur.fetchone()
            if not o:
                raise ErroAPI("validacao", f"Operação {operacao_id} não existe")
            numero_pedido = o["numero_pedido"]
        cur.execute("select current_date as hoje")
        dia = data_doc or cur.fetchone()["hoje"]
        caminho = arqs.livre(dia, nome_arquivo(dia, numero_pedido, tipo, ext))
        arqs.gravar(caminho, conteudo)
        cur.execute("""insert into documento (operacao_id, tipo, nome_arquivo, caminho, mime, bytes, sha256, data_doc)
                       values (%s, %s, %s, %s, %s, %s, %s, %s) returning *""",
                    (operacao_id, tipo, caminho.rsplit("/", 1)[-1], caminho, mime, len(conteudo), sha, data_doc))
        return 201, _json(cur.fetchone())

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
