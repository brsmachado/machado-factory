# A tela

`index.html` + `app.css` + `app.js`, sem build e sem dependência. É a página do
Caixa Machado com o estado embutido trocado pela API (docs/05-telas.md): mesmo
CSS, mesmas seções e mesmo comportamento. A diferença é que todo número vem do
servidor e toda gravação passa pelas validações dele.

- `/` painel · `#/fornecedores` · `#/historico` · login na própria página
- **A conferir** mostra os rascunhos do robô, com "Usar itens / Usar total"
  (A-01), "Juntar", "Corrigir e aprovar", "Aprovar" e "Descartar". Quando a
  lista esvazia, o quadro some.
- "Enviar documentos" manda pedido e comprovante para o robô ler.
- Dinheiro em centavos inteiros no navegador, nunca float. A entrada aceita
  `1.234,56`, `1234,56` e `1234.56`.
- Testada em 680 px (painel lateral), 1240 px e 375 px, claro e escuro, sem
  rolagem lateral: `testes/LEIA-ME.md`.

Servida pela API (`StaticFiles` em `/`, `WEB_DIR` muda a pasta). A sessão fica
no `localStorage` e expira em 12 h.
