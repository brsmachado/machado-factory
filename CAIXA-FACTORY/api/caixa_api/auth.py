"""Login, sessões e papéis (docs/04-api.md §1).

- Tela: POST /auth/entrar devolve um token de sessão (Bearer). O banco guarda
  só o sha256 do token.
- Robô: o token de serviço vem do ROBO_TOKEN do .env e age como o usuário
  ROBO_EMAIL, que precisa ter papel `operador` — nunca `admin`
  (docs/06-robo.md, "Segurança dos robôs"). O robô só lê e, quando os
  endpoints /robo existirem, cria rascunhos; ele não grava operação, não
  recebe duplicata, não estorna.
- Papéis: leitura (só GET) · operador (lança e recebe) · admin (tudo, inclusive usuários).

Senha com scrypt da biblioteca padrão — sem dependência extra.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request

from .erros import ErroAPI

# scrypt: n=2^15, r=8, p=1 (~32 MB, ~0,1 s) — recomendação OWASP
_N, _R, _P, _DKLEN = 2 ** 15, 8, 1, 32


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${dk.hex()}"


def confere_senha(senha: str, guardado: str) -> bool:
    try:
        alg, n, r, p, sal, dk = guardado.split("$")
        if alg != "scrypt":
            return False
        calc = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p),
                              dklen=len(bytes.fromhex(dk)), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(calc, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


# hash de uma senha qualquer, para gastar o mesmo tempo quando o e-mail não existe
_HASH_FALSO = hash_senha(secrets.token_hex(16))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Usuario:
    id: int
    nome: str
    email: str
    papel: str
    robo: bool = False

    def json(self) -> dict:
        return {"id": self.id, "nome": self.nome, "email": self.email, "papel": self.papel}


def _bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    if h[:7].lower() == "bearer " and h[7:].strip():
        return h[7:].strip()
    return None


def usuario_atual(request: Request) -> Usuario:
    token = _bearer(request)
    if not token:
        raise ErroAPI("nao_autenticado", "Faça login para continuar")
    cfg = request.app.state.cfg
    banco = request.app.state.banco

    if cfg.robo_token and hmac.compare_digest(token.encode(), cfg.robo_token.encode()):
        u = banco.um("select id, nome, email, papel from usuario where email = %s and ativo", (cfg.robo_email,))
        if not u:
            raise ErroAPI("nao_autenticado", f"Usuário do robô ({cfg.robo_email}) não existe ou está inativo")
        if u["papel"] != "operador":
            raise ErroAPI("sem_permissao", "O usuário do robô precisa ter papel operador, nunca admin")
        return Usuario(u["id"], u["nome"], u["email"], u["papel"], robo=True)

    u = banco.um(
        """update sessao s set ultimo_uso = now()
             from usuario u
            where s.token_hash = %s and s.expira_em > now()
              and u.id = s.usuario_id and u.ativo
        returning u.id, u.nome, u.email, u.papel""",
        (hash_token(token),),
    )
    if not u:
        raise ErroAPI("nao_autenticado", "Sessão expirada ou inválida: faça login de novo")
    return Usuario(u["id"], u["nome"], u["email"], u["papel"])


def pode_ler(u: Usuario = Depends(usuario_atual)) -> Usuario:
    return u


def pode_lancar(u: Usuario = Depends(usuario_atual)) -> Usuario:
    """Lançar, receber, editar: pessoa com papel operador ou admin. O robô não."""
    if u.robo:
        raise ErroAPI("sem_permissao", "O robô não grava operação financeira: ele só monta rascunhos")
    if u.papel not in ("operador", "admin"):
        raise ErroAPI("sem_permissao", "Seu usuário é só de leitura")
    return u


def so_admin(u: Usuario = Depends(usuario_atual)) -> Usuario:
    if u.robo or u.papel != "admin":
        raise ErroAPI("sem_permissao", "Só administrador")
    return u
