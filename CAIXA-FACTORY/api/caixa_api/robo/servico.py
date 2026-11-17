"""O robô: o que ele faz, independente de por onde chega o pedido (API ou Telegram)."""
import hashlib
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from .. import fmt
from ..documentos import detectar
from ..erros import ErroAPI
from ..escrita import rodar
from . import aviso, rascunhos
from .extracao import ErroExtracao, Extrator

log = logging.getLogger("caixa_api.robo")


class Robo:
    def __init__(self, banco, cfg, extrator: Optional[Extrator] = None, telegram=None):
        self.banco = banco
        self.cfg = cfg
        self.extrator = extrator
        self.telegram = telegram

    # quem age ---------------------------------------------------------------
    def usuario_robo(self) -> int:
        u = self.banco.um("select id, papel from usuario where email = %s and ativo", (self.cfg.robo_email,))
        if not u or u["papel"] != "operador":
            raise ErroAPI("erro_interno", f"Usuário do robô ({self.cfg.robo_email}) não existe ou não é operador: "
                                          "rode `python -m caixa_api.cli criar-robo`")
        return u["id"]

    def usuario_dono(self) -> int:
        u = self.banco.um("select id, papel from usuario where lower(email) = lower(%s) and ativo",
                          (self.cfg.telegram_usuario_email,))
        if not u or u["papel"] not in ("admin", "operador"):
            raise ErroAPI("erro_interno", "TELEGRAM_USUARIO_EMAIL precisa ser um usuário ativo admin ou operador")
        return u["id"]

    def gravar(self, usuario_id: int, fn):
        return rodar(self.banco, self.cfg.documentos_dir, usuario_id, fn)

    # documentos -------------------------------------------------------------
    def receber_documento(self, conteudo: bytes, usuario_id: Optional[int] = None) -> dict:
        """Lê um documento e põe no rascunho certo. Devolve o resultado de rascunhos.ingerir."""
        if not conteudo:
            raise ErroAPI("validacao", "Arquivo vazio")
        if len(conteudo) > self.cfg.max_upload_bytes:
            raise ErroAPI("validacao", f"Arquivo maior que {self.cfg.max_upload_bytes // (1024 * 1024)} MB")
        tipo = detectar(conteudo)      # magic bytes, não extensão
        if not tipo:
            raise ErroAPI("validacao", "Tipo de arquivo não aceito: mande foto (JPG/PNG) ou PDF")
        sha = hashlib.sha256(conteudo).hexdigest()
        with self.banco.transacao() as cur:
            ja = rascunhos.ja_recebido(cur, sha)
        if ja:   # mesma foto duas vezes: não lê de novo, não cria outro rascunho
            onde = (f"operação {ja['operacao_id']}" if ja["operacao_id"]
                    else f"rascunho {ja['rascunho_id']}" if ja["rascunho_id"] else "documentos")
            raise ErroAPI("conflito", f"Este arquivo já foi recebido ({onde})",
                          {"documento_id": ja["id"], "rascunho_id": ja["rascunho_id"],
                           "operacao_id": ja["operacao_id"]})
        if self.extrator is None:
            raise ErroAPI("erro_interno", "Leitura de documentos não configurada (falta ANTHROPIC_API_KEY)")
        try:
            lido = self.extrator.extrair(conteudo, tipo[1])   # fora da transação: pode levar segundos
        except ErroExtracao as e:
            raise ErroAPI("validacao", f"Não consegui ler o documento: {e}") from e
        uid = usuario_id or self.usuario_robo()
        return self.gravar(uid, lambda cur, arqs: rascunhos.ingerir(cur, arqs, conteudo, lido))

    # aviso ------------------------------------------------------------------
    def aviso(self, enviar: bool = True, forcar: bool = False, hoje=None) -> dict:
        res = self.gravar(self.usuario_robo(), lambda cur, arqs: aviso.montar(cur, hoje))
        res["enviado"] = False
        if enviar and (res["enviar"] or forcar) and self.telegram and self.cfg.telegram_chat_id:
            self.telegram.enviar(self.cfg.telegram_chat_id, res["texto"], res["botoes"])
            res["enviado"] = True
        return res


# --- texto para o Telegram ------------------------------------------------

def texto_rascunho(r: dict) -> tuple[str, list]:
    d = r["dados"]
    titulo = f"📄 Rascunho {r['id']}" + (f" — {d['numero_pedido']}" if d.get("numero_pedido") else "")
    linhas = [titulo]
    if r["fornecedor"]:
        linhas.append(r["fornecedor"]["nome"])
    valores = []
    if d.get("valor_cheio"):
        valores.append(f"valor cheio {fmt.brl(d['valor_cheio'])}")
    if d.get("valor_pago"):
        pix = f" (PIX {date.fromisoformat(d['data_pagamento']):%d/%m})" if d.get("data_pagamento") else ""
        valores.append(f"pago {fmt.brl(d['valor_pago'])}{pix}")
    if valores:
        linhas.append(" · ".join(valores).capitalize())
    p = r.get("previa")
    if p:
        linhas.append(f"Lucro {fmt.brl(p['lucro'])} · retorno {fmt.br_decimal(Decimal(p['retorno']) * 100)}% · "
                      f"{fmt.br_decimal(Decimal(p['taxa_mes']) * 100)}% ao mês "
                      f"({fmt.br_decimal(Decimal(p['prazo_medio_dias']), 0)} dias)")
    if d.get("duplicatas"):
        linhas.append("Duplicatas: " + "; ".join(
            f"{date.fromisoformat(x['vencimento']):%d/%m/%Y} {fmt.brl(x['valor'])}" for x in d["duplicatas"]))
    if r["fornecedor"] and r["fornecedor"].get("observacoes"):
        linhas.append(f"ℹ {r['fornecedor']['observacoes']}")
    erros = [x for x in r["pendencias"] if x["nivel"] == "erro"]
    avisos = [x for x in r["pendencias"] if x["nivel"] != "erro"]
    if erros:
        linhas.append("")
        linhas += [f"⚠ {x['mensagem']}" for x in erros]
    if avisos:
        linhas.append("")
        linhas += [f"• {x['mensagem']}" for x in avisos]
    if r["estado"] == "aprovado":
        linhas += ["", f"✅ Aprovado: operação {r['operacao_id']}"]
    elif r["estado"] == "descartado":
        linhas += ["", f"🗑 Descartado: {r['descarte_motivo']}"]
    elif r["pode_aprovar"]:
        linhas += ["", "Tudo conferido. Aprovar lança a operação."]

    botoes = []
    if r["estado"] == "pendente":
        c1 = next((x for x in r["pendencias"] if x["codigo"] == "C1"), None)
        if c1:
            botoes.append([(f"Usar itens {fmt.brl(c1['soma_itens'])}", f"a01:{r['id']}:itens"),
                           (f"Usar total {fmt.brl(c1['total_pedido'])}", f"a01:{r['id']}:total")])
        for x in r["pendencias"]:
            if x["codigo"] == "ambiguo":
                botoes.append([(f"Juntar com o rascunho {x['rascunho_id']}", f"jun:{r['id']}:{x['rascunho_id']}")])
        linha = [("🗑 Descartar", f"des:{r['id']}")]
        if r["pode_aprovar"]:
            linha.insert(0, ("✅ Aprovar", f"apr:{r['id']}"))
        botoes.append(linha)
    return "\n".join(linhas), botoes

