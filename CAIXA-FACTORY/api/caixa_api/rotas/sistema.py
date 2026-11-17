"""Login (/auth) e saúde (docs/04-api.md §10)."""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth import Usuario, _HASH_FALSO, confere_senha, hash_token, usuario_atual, _bearer
from ..erros import ErroAPI

r = APIRouter()


class Entrada(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    senha: str = Field(min_length=1, max_length=200)


@r.post("/auth/entrar", tags=["login"])
def entrar(dados: Entrada, request: Request):
    banco = request.app.state.banco
    horas = request.app.state.cfg.sessao_horas
    u = banco.um("select id, nome, email, papel, senha_hash, ativo from usuario where lower(email) = lower(%s)",
                 (dados.email.strip(),))
    ok = confere_senha(dados.senha, u["senha_hash"] if u else _HASH_FALSO)
    # mesma mensagem e mesmo tempo para e-mail inexistente e senha errada
    if not u or not ok or not u["ativo"]:
        raise ErroAPI("nao_autenticado", "E-mail ou senha incorretos")
    if u["email"] == request.app.state.cfg.robo_email:
        raise ErroAPI("sem_permissao", "O usuário do robô não entra pela tela")
    token = secrets.token_urlsafe(32)
    with banco.transacao() as cur:
        cur.execute("delete from sessao where expira_em < now()")
        cur.execute("insert into sessao (token_hash, usuario_id, expira_em) values (%s, %s, now() + %s) "
                    "returning expira_em", (hash_token(token), u["id"], timedelta(hours=horas)))
        expira = cur.fetchone()["expira_em"]
    return {"token": token, "expira_em": expira.isoformat(),
            "usuario": {"id": u["id"], "nome": u["nome"], "email": u["email"], "papel": u["papel"]}}


@r.post("/auth/sair", status_code=204, tags=["login"])
def sair(request: Request, u: Usuario = Depends(usuario_atual)):
    if not u.robo:
        request.app.state.banco.um("delete from sessao where token_hash = %s returning 1",
                                   (hash_token(_bearer(request)),))
    from fastapi import Response
    return Response(status_code=204)


@r.get("/auth/eu", tags=["login"])
def eu(u: Usuario = Depends(usuario_atual)):
    return {**u.json(), "robo": u.robo}


@r.get("/saude", tags=["saúde"])
def saude(request: Request):
    """Sem login, para o monitor externo. Não expõe valores, só ok/erro."""
    cfg = request.app.state.cfg
    corpo = {"ok": False, "versao": cfg.versao, "banco": "erro", "integridade": {}}
    try:
        c = request.app.state.banco.um(
            "select (caixa + aplicado) = (aportes - retiradas + lucro_realizado) as identidade from v_caixa")
        corpo["banco"] = "ok"
        corpo["integridade"]["identidade_caixa"] = "ok" if c["identidade"] else "falhou"
        corpo["ok"] = bool(c["identidade"])
    except Exception as e:  # noqa: BLE001 — saúde não pode cair
        request.app.state.log.error("saúde: banco indisponível: %s", e)
    return JSONResponse(corpo, status_code=200 if corpo["ok"] else 503)
