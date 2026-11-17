# Teste da tela no navegador

Percorre a tela inteira em 680 px (a largura do painel lateral, obrigatória
pela docs/05-telas.md) com o Chromium: login, painel, resultado por mês, busca
sem perder o foco, nova operação (caixa insuficiente, prévia, soma errada,
Enter), receber duplicata, robô (enviar pedido + PIX, "Usar itens", aprovar),
estorno sem motivo, retirada grande, tema escuro, 1240 px e 375 px sem rolagem
lateral, fornecedores e histórico. Falha com erro de console ou página rolando
para o lado.

```bash
createdb caixa_tela && DATABASE_URL=postgresql:///caixa_tela ../../banco/aplicar.sh
python3 ../../banco/carregar_seed.py | psql -q caixa_tela
DATABASE_URL=postgresql:///caixa_tela python servidor_tela.py &     # leitor de documentos falso
node tela.js /tmp/tela                                              # capturas em /tmp/tela/shots
```

Login do teste: `dono@teste.invalid` / `senha-de-teste-123` (criado pelo servidor_tela.py).
