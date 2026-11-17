"""O robô no Telegram (long polling — não precisa abrir porta nem webhook).

    python -m caixa_api.robo telegram      # serviço contínuo (systemd)

Só conversa com TELEGRAM_CHAT_ID; mensagem de qualquer outro chat é ignorada.
Foto ou PDF que chega vira documento lido e rascunho. Os botões são cliques do
dono e agem em nome de TELEGRAM_USUARIO_EMAIL (fica no log como ele).

Comandos:
  /resumo                        caixa, aplicado, a receber, rendimento
  /agenda                        próximos retornos
  /aviso                         o aviso do dia, agora
  /pendentes                     rascunhos esperando conferência
  /corrigir <id> <campo> <valor> corrige um rascunho
  /descartar <id> [motivo]
  /ajuda
"""
import logging
import time
from decimal import Decimal
from typing import Optional

import httpx

from .. import fmt
from .. import operacoes as ops
from ..erros import ErroAPI
from . import rascunhos
from .servico import Robo, texto_rascunho

log = logging.getLogger("caixa_api.robo.telegram")

AJUDA = """Mande a foto da tela do pedido de compra e a foto (ou PDF) do comprovante do PIX — em mensagens separadas, em qualquer ordem. Eu leio, junto os dois, confiro e te mostro o rascunho para aprovar. Nada é lançado sem o seu clique.

/resumo — caixa e rendimento
/agenda — próximos retornos
/aviso — o aviso do dia, agora
/pendentes — rascunhos esperando você
/corrigir 12 valor_pago 4107.84
/corrigir 12 data_pagamento 2026-10-19
/corrigir 12 duplicatas 2026-11-15=4279.00;2026-11-25=1000.00
/corrigir 12 fornecedor_id 2
/descartar 12 motivo

Campos de /corrigir: fornecedor_id, numero_pedido, numero_nf, data_pedido, data_pagamento, valor_pago, valor_cheio, duplicatas, observacoes."""


class ClienteTelegram:
    """O mínimo da Bot API, com httpx."""

    def __init__(self, token: str, base: str = "https://api.telegram.org", http: Optional[httpx.Client] = None):
        self.base = f"{base}/bot{token}"
        self.base_arquivo = f"{base}/file/bot{token}"
        self.http = http or httpx.Client(timeout=70)

    def _chamar(self, metodo: str, **dados):
        r = self.http.post(f"{self.base}/{metodo}", json=dados)
        corpo = r.json()
        if not corpo.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {corpo.get('description')}")
        return corpo["result"]

    @staticmethod
    def _teclado(botoes):
        if not botoes:
            return None
        return {"inline_keyboard": [[{"text": t[:64], "callback_data": d} for t, d in linha] for linha in botoes]}

    def enviar(self, chat_id, texto: str, botoes=None) -> int:
        dados = {"chat_id": chat_id, "text": texto[:4096]}
        if botoes:
            dados["reply_markup"] = self._teclado(botoes)
        return self._chamar("sendMessage", **dados)["message_id"]

    def editar(self, chat_id, message_id: int, texto: str, botoes=None) -> None:
        dados = {"chat_id": chat_id, "message_id": message_id, "text": texto[:4096],
                 "reply_markup": self._teclado(botoes) or {"inline_keyboard": []}}
        try:
            self._chamar("editMessageText", **dados)
        except RuntimeError as e:
            if "not modified" not in str(e):
                raise

    def responder_clique(self, callback_id: str, texto: str = "") -> None:
        self._chamar("answerCallbackQuery", callback_query_id=callback_id, text=texto[:200])

    def atualizacoes(self, offset: int, espera: int = 50) -> list:
        return self._chamar("getUpdates", offset=offset, timeout=espera,
                            allowed_updates=["message", "callback_query"])

    def baixar(self, file_id: str, limite: int) -> bytes:
        info = self._chamar("getFile", file_id=file_id)
        if info.get("file_size") and info["file_size"] > limite:
            raise ErroAPI("validacao", f"Arquivo maior que {limite // (1024 * 1024)} MB")
        r = self.http.get(f"{self.base_arquivo}/{info['file_path']}")
        r.raise_for_status()
        return r.content


class BotTelegram:
    def __init__(self, robo: Robo, cliente: ClienteTelegram):
        self.robo = robo
        self.tg = cliente
        self.chat = str(robo.cfg.telegram_chat_id)

    # roteamento -------------------------------------------------------------
    def processar(self, upd: dict) -> None:
        if "callback_query" in upd:
            cq = upd["callback_query"]
            msg = cq.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != self.chat:
                log.warning("clique de chat não autorizado ignorado")
                return
            self._clique(cq["id"], msg.get("message_id"), cq.get("data") or "")
            return
        msg = upd.get("message")
        if not msg:
            return
        if str(msg["chat"]["id"]) != self.chat:
            log.warning("mensagem de chat não autorizado ignorada: %s", msg["chat"].get("id"))
            return
        if msg.get("photo"):
            self._documento(max(msg["photo"], key=lambda p: p.get("file_size", 0))["file_id"])
        elif msg.get("document"):
            self._documento(msg["document"]["file_id"])
        elif (msg.get("text") or "").startswith("/"):
            self._comando(msg["text"])
        else:
            self.tg.enviar(self.chat, "Mande a foto do pedido ou do comprovante, ou /ajuda.")

    # documentos -------------------------------------------------------------
    def _documento(self, file_id: str) -> None:
        aviso_id = self.tg.enviar(self.chat, "Recebi. Lendo o documento…")
        try:
            conteudo = self.tg.baixar(file_id, self.robo.cfg.max_upload_bytes)
            res = self.robo.receber_documento(conteudo)
        except ErroAPI as e:
            self.tg.editar(self.chat, aviso_id, f"⚠ {e.mensagem}")
            return
        if res["acao"] == "nao_reconhecido":
            self.tg.editar(self.chat, aviso_id, "Guardei o arquivo, mas não reconheci como pedido de compra "
                                                "nem como comprovante de PIX.")
            return
        texto, botoes = texto_rascunho(res["rascunho"])
        cab = "Juntei com o que já tinha chegado.\n\n" if res["acao"] == "juntado" else ""
        self.tg.editar(self.chat, aviso_id, cab + texto, botoes)

    # botões -----------------------------------------------------------------
    def _clique(self, callback_id: str, message_id: Optional[int], dado: str) -> None:
        partes = dado.split(":")
        try:
            dono = self.robo.usuario_dono()
            if partes[0] == "rec":
                op = self.robo.gravar(dono, lambda cur, a: _receber_hoje(cur, int(partes[1])))
                self.tg.responder_clique(callback_id, "Recebida ✓")
                self.tg.enviar(self.chat, f"✓ Recebida: {op['numero_pedido']} · caixa agora {self._caixa()}")
                return
            if partes[0] == "apr":
                res = self.robo.gravar(dono, lambda cur, a: rascunhos.aprovar(cur, a, int(partes[1])))
                texto, botoes = texto_rascunho(res["rascunho"])
                self.tg.responder_clique(callback_id, "Lançado ✓")
                self.tg.editar(self.chat, message_id, texto, botoes)
                o = res["operacao"]
                self.tg.enviar(self.chat, f"✅ Lançado: operação {o['id']} — {o['numero_pedido']} · "
                                          f"{fmt.brl(o['valor_pago'])} · caixa agora {self._caixa()}")
                return
            if partes[0] == "des":
                r = self.robo.gravar(dono, lambda cur, a: rascunhos.descartar(cur, int(partes[1]), "Descartado no Telegram"))
            elif partes[0] == "a01":
                r = self.robo.gravar(dono, lambda cur, a: rascunhos.escolher_valor_cheio(cur, int(partes[1]), partes[2]))
            elif partes[0] == "jun":
                r = self.robo.gravar(dono, lambda cur, a: rascunhos.juntar(cur, int(partes[1]), int(partes[2])))
            else:
                self.tg.responder_clique(callback_id, "Botão desconhecido")
                return
            texto, botoes = texto_rascunho(r)
            self.tg.responder_clique(callback_id, "Feito")
            self.tg.editar(self.chat, message_id, texto, botoes)
        except ErroAPI as e:
            self.tg.responder_clique(callback_id, "Não deu")
            self.tg.enviar(self.chat, f"⚠ {e.mensagem}")

    def _caixa(self) -> str:
        return fmt.brl(self.robo.banco.um("select caixa from v_caixa")["caixa"])

    # comandos ---------------------------------------------------------------
    def _comando(self, texto: str) -> None:
        cmd, *args = texto.strip().split(maxsplit=3)
        cmd = cmd.split("@")[0].lower()
        try:
            if cmd in ("/start", "/ajuda", "/help"):
                self.tg.enviar(self.chat, AJUDA)
            elif cmd == "/resumo":
                self.tg.enviar(self.chat, self._resumo())
            elif cmd == "/agenda":
                self.tg.enviar(self.chat, self._agenda())
            elif cmd == "/aviso":
                self.robo.aviso(forcar=True)
            elif cmd == "/pendentes":
                with self.robo.banco.transacao() as cur:
                    lista = rascunhos.listar(cur)
                if not lista:
                    self.tg.enviar(self.chat, "Nenhum rascunho esperando.")
                for r in lista:
                    self.tg.enviar(self.chat, *texto_rascunho(r))
            elif cmd == "/corrigir" and len(args) == 3:
                rid, campo, valor = int(args[0]), args[1], args[2]
                if campo == "duplicatas":
                    valor = [{"vencimento": v.split("=")[0].strip(), "valor": v.split("=")[1].strip()}
                             for v in valor.split(";") if "=" in v]
                elif campo == "fornecedor_id":
                    valor = int(valor)
                r = self.robo.gravar(self.robo.usuario_dono(), lambda cur, a: rascunhos.corrigir(cur, rid, {campo: valor}))
                self.tg.enviar(self.chat, *texto_rascunho(r))
            elif cmd == "/descartar" and args:
                motivo = " ".join(args[1:]) or "Descartado no Telegram"
                r = self.robo.gravar(self.robo.usuario_dono(),
                                     lambda cur, a: rascunhos.descartar(cur, int(args[0]), motivo))
                self.tg.enviar(self.chat, *texto_rascunho(r))
            else:
                self.tg.enviar(self.chat, "Não entendi. /ajuda mostra o que eu sei fazer.")
        except (ValueError, IndexError):
            self.tg.enviar(self.chat, "Não entendi os números do comando. /ajuda mostra exemplos.")
        except ErroAPI as e:
            self.tg.enviar(self.chat, f"⚠ {e.mensagem}")

    def _resumo(self) -> str:
        c = self.robo.banco.um("select * from v_caixa, v_carteira")
        return "\n".join([
            f"Caixa livre: {fmt.brl(c['caixa'])}",
            f"Aplicado: {fmt.brl(c['aplicado'])} · a receber {fmt.brl(c['a_receber'])}",
            f"Capital: {fmt.brl(c['capital'])}",
            f"Lucro realizado: {fmt.brl(c['lucro_realizado'])} · a receber {fmt.brl(c['lucro_a_receber'])}",
            f"Operações rendem {fmt.br_decimal(c['taxa_mes'] * 100)}% ao mês; com "
            f"{fmt.br_decimal(c['ocupacao'] * 100, 1)}% do capital girando, o caixa inteiro rende "
            f"{fmt.br_decimal(c['rendimento_caixa_inteiro'] * 100)}% ao mês.",
        ])

    def _agenda(self) -> str:
        linhas = self.robo.banco.todos("select * from v_agenda")
        if not linhas:
            return "Nenhuma duplicata em aberto."
        total = sum((d["valor"] for d in linhas), Decimal(0))
        return "\n".join([f"Em aberto: {fmt.brl(total)}"] + [
            f"{d['vencimento']:%d/%m} · {' '.join(d['fornecedor'].split()[:2])} · {d['numero_pedido']} · "
            f"{d['sequencia']}ª de {d['de']} · {fmt.brl(d['valor'])}" + (" · atrasada" if d["atrasada"] else "")
            for d in linhas])

    # laço -------------------------------------------------------------------
    def rodar(self) -> None:
        log.info("robô do Telegram no ar (chat %s)", self.chat)
        while True:
            try:
                offset = int(self.robo.banco.um("select valor from parametro where chave = 'telegram_offset'")["valor"])
                for upd in self.tg.atualizacoes(offset):
                    try:
                        self.processar(upd)
                    except Exception:  # noqa: BLE001 — um update ruim não derruba o robô
                        log.exception("erro processando update %s", upd.get("update_id"))
                    # grava o offset depois de cada update: se cair no meio, retoma dali
                    self.robo.banco.um("update parametro set valor = %s where chave = 'telegram_offset' returning 1",
                                       (str(upd["update_id"] + 1),))
            except httpx.HTTPError as e:
                log.warning("Telegram indisponível (%s); tentando de novo em 10 s", e)
                time.sleep(10)


def _receber_hoje(cur, dup_id: int) -> dict:
    """Botão "Recebi" do aviso: mesma regra do POST /duplicatas/:id/receber."""
    from ..rotas.duplicatas import _receber
    d = _receber(cur, dup_id, None)
    return ops.obter(cur, d["operacao_id"])
