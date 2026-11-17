"""Arquivos de pedidos e comprovantes (docs/04-api.md §7, docs/07-migracao.md §6).

Convenção de nome, a mesma da pasta de hoje:
    operacoes/AAAA-MM/AAAA-MM-DD_PC-<pedido com - no lugar de / e espaço>_<tipo>.<ext>

O tipo real do arquivo é conferido pelos primeiros bytes (magic bytes), não
pela extensão (docs/06-robo.md). Documento enviado sem operação recebe
`SEM-PEDIDO` no nome e é renomeado quando for vinculado a uma operação.

Renomear dentro de uma transação: o arquivo novo é criado como hard link
antes do commit (se falhar, a transação desfaz); o nome antigo só é removido
depois do commit. Se a transação falhar, os links novos são removidos.
"""
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

from .erros import ErroAPI

SUFIXO_TIPO = {
    "pedido_compra": "pedido-compra",
    "comprovante_pix": "comprovante-pix",
    "nota_fiscal": "nota-fiscal",
    "outro": "outro",
}


def detectar(conteudo: bytes) -> Optional[tuple[str, str]]:
    """(extensão, mime) pelo conteúdo, ou None se não for um tipo aceito."""
    if conteudo.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if conteudo.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if len(conteudo) >= 12 and conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "webp", "image/webp"
    if len(conteudo) >= 12 and conteudo[4:8] == b"ftyp" and conteudo[8:12] in (b"heic", b"heix", b"mif1", b"heif"):
        return "heic", "image/heic"
    return None


def slug_pedido(numero_pedido: Optional[str]) -> str:
    if not numero_pedido:
        return "SEM-PEDIDO"
    s = re.sub(r"[\s/]+", "-", numero_pedido.strip())
    s = re.sub(r"[^A-Za-z0-9-]", "", s)
    return s.strip("-") or "SEM-PEDIDO"


def nome_arquivo(data_doc: date, numero_pedido: Optional[str], tipo: str, ext: str) -> str:
    return f"{data_doc.isoformat()}_{slug_pedido(numero_pedido)}_{SUFIXO_TIPO[tipo]}.{ext}"


class Arquivos:
    """Mudanças em disco que acompanham uma transação."""

    def __init__(self, base: Path):
        self.base = base.resolve()
        self.criados: list[Path] = []
        self.remover_apos_commit: list[Path] = []

    def absoluto(self, relativo: str) -> Path:
        p = (self.base / relativo).resolve()
        if self.base not in p.parents:
            raise ErroAPI("erro_interno", "Caminho de documento fora da pasta de documentos")
        return p

    def livre(self, data_doc: date, nome: str) -> str:
        """Caminho relativo livre: se já existe, acrescenta -2, -3..."""
        pasta = f"operacoes/{data_doc:%Y-%m}"
        raiz, ext = os.path.splitext(nome)
        i = 1
        while True:
            cand = f"{pasta}/{nome}" if i == 1 else f"{pasta}/{raiz}-{i}{ext}"
            if not self.absoluto(cand).exists() and self.absoluto(cand) not in self.criados:
                return cand
            i += 1

    def gravar(self, relativo: str, conteudo: bytes) -> None:
        p = self.absoluto(relativo)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "xb") as f:        # 'x': nunca sobrescreve
            f.write(conteudo)
        self.criados.append(p)

    def renomear(self, de: str, para: str) -> None:
        a, b = self.absoluto(de), self.absoluto(para)
        b.parent.mkdir(parents=True, exist_ok=True)
        os.link(a, b)
        self.criados.append(b)
        self.remover_apos_commit.append(a)

    def confirmar(self) -> None:
        for p in self.remover_apos_commit:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        self.criados.clear()
        self.remover_apos_commit.clear()

    def desfazer(self) -> None:
        for p in self.criados:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        self.criados.clear()
        self.remover_apos_commit.clear()


def vincular(cur, arqs: Arquivos, operacao_id: int, numero_pedido: str, ids: list[int]) -> None:
    """Liga documentos a uma operação e corrige o nome para a convenção."""
    if not ids:
        return
    cur.execute("select id, operacao_id, tipo, nome_arquivo, caminho, data_doc, enviado_em::date as enviado "
                "from documento where id = any(%s) for update", (list(set(ids)),))
    docs = {d["id"]: d for d in cur.fetchall()}
    faltam = sorted(set(ids) - docs.keys())
    if faltam:
        raise ErroAPI("validacao", f"Documento {faltam[0]} não existe", {"documento_ids": faltam})
    for d in docs.values():
        if d["operacao_id"] not in (None, operacao_id):
            raise ErroAPI("conflito", f"Documento {d['id']} já pertence a outra operação",
                          {"documento_id": d["id"], "operacao_id": d["operacao_id"]})
        if d["operacao_id"] == operacao_id:
            continue
        data_doc = d["data_doc"] or d["enviado"]
        ext = d["nome_arquivo"].rsplit(".", 1)[-1]
        novo_nome = nome_arquivo(data_doc, numero_pedido, d["tipo"], ext)
        novo = d["caminho"]
        if novo_nome != d["nome_arquivo"]:
            novo = arqs.livre(data_doc, novo_nome)
            arqs.renomear(d["caminho"], novo)
        cur.execute("update documento set operacao_id = %s, nome_arquivo = %s, caminho = %s where id = %s",
                    (operacao_id, novo.rsplit("/", 1)[-1], novo, d["id"]))


def salvar(cur, arqs: Arquivos, conteudo: bytes, tipo: str, *, operacao_id: Optional[int] = None,
           rascunho_id: Optional[int] = None, data_doc: Optional[date] = None,
           numero_pedido: Optional[str] = None) -> tuple[bool, dict]:
    """Grava o arquivo e a linha em documento. Devolve (novo, linha).

    Mesmo sha256 já guardado: devolve o existente (novo=False) sem gravar nada.
    O tipo real vem dos primeiros bytes; extensão e nome enviados não importam.
    """
    import hashlib
    tipo_real = detectar(conteudo)
    if not tipo_real:
        raise ErroAPI("validacao", "Tipo de arquivo não aceito: envie PDF, PNG, JPG, WEBP ou HEIC")
    ext, mime = tipo_real
    sha = hashlib.sha256(conteudo).hexdigest()
    cur.execute("select * from documento where sha256 = %s", (sha,))
    existente = cur.fetchone()
    if existente:
        return False, existente
    if operacao_id is not None and numero_pedido is None:
        cur.execute("select numero_pedido from operacao where id = %s", (operacao_id,))
        o = cur.fetchone()
        if not o:
            raise ErroAPI("validacao", f"Operação {operacao_id} não existe")
        numero_pedido = o["numero_pedido"]
    cur.execute("select current_date as hoje")
    dia = data_doc or cur.fetchone()["hoje"]
    caminho = arqs.livre(dia, nome_arquivo(dia, numero_pedido, tipo, ext))
    arqs.gravar(caminho, conteudo)
    cur.execute("""insert into documento (operacao_id, rascunho_id, tipo, nome_arquivo, caminho, mime, bytes, sha256, data_doc)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning *""",
                (operacao_id, rascunho_id, tipo, caminho.rsplit("/", 1)[-1], caminho, mime, len(conteudo), sha, data_doc))
    return True, cur.fetchone()
