# Caixa Factory — documentação técnica

Sistema de gestão do capital próprio que Bruno aplica nas compras da Machado
Embalagens.

**O que o sistema faz, em uma frase:** registra que o investidor pagou um
fornecedor à vista com desconto, acompanha as duplicatas que a empresa devolve, e
calcula quanto isso rende por mês — inclusive quanto custa o dinheiro que fica
parado no caixa.

Esta documentação descreve o sistema a ser construído. Hoje a operação roda numa
página HTML com os dados embutidos (artefato publicado no Claude); o conteúdo
dessa página é a especificação funcional validada em produção desde agosto/2026,
com 7 operações e R$ 150.000 de capital.

## Índice

| Arquivo | O que tem dentro |
|---|---|
| [01-dominio.md](01-dominio.md) | Glossário, ciclo de vida, regras de negócio numeradas, armadilhas reais |
| [02-modelo-dados.md](02-modelo-dados.md) | DDL PostgreSQL completo, constraints, triggers, views |
| [03-formulas.md](03-formulas.md) | Todo o cálculo com exemplos conferidos nos dados reais |
| [04-api.md](04-api.md) | Endpoints REST, payloads, erros, idempotência |
| [05-telas.md](05-telas.md) | Telas, estados, validação de formulário |
| [06-robo.md](06-robo.md) | Os três robôs: ingestão, conciliação e alerta de caixa parado |
| [07-migracao.md](07-migracao.md) | Como importar os dados que já existem |
| [08-deploy.md](08-deploy.md) | VPS Hostinger, domínio Locaweb, HTTPS, backup e cron |
| [seed/estado-2026-10-19.json](seed/estado-2026-10-19.json) | Os dados reais de hoje, para carga inicial e testes |

## Cinco princípios que não se negociam

**1. Dinheiro é `NUMERIC(14,2)`, nunca `float`.** Em nenhuma camada — nem no
banco, nem na API, nem no JavaScript da tela. No front, trabalhe com centavos
inteiros ou com string decimal. `0.1 + 0.2 !== 0.3` já custou dinheiro a muita
gente.

**2. Datas de negócio são `DATE`, sem hora, no fuso `America/Sao_Paulo`.**
Vencimento, pagamento e recebimento são dias, não instantes. Timestamp com fuso
só para auditoria (`criado_em`, `atualizado_em`).

**3. Nada é apagado.** Operação errada é **estornada**, não deletada. Recebimento
errado é **desfeito**, e o desfazer fica no log. Toda alteração grava em
`evento`. Isso é dinheiro de verdade: a trilha de auditoria vale mais que a
limpeza da tabela.

**4. O robô nunca grava uma operação financeira sozinho.** Ele lê os documentos,
monta um **rascunho** e para. Uma pessoa confere e confirma. A única coisa que o
robô pode gravar sem aprovação é um alerta.

**5. Existem duas taxas diferentes e elas nunca podem ser confundidas.** O
desconto do fornecedor é calculado sobre o valor cheio; o retorno do investidor é
calculado sobre o que saiu do bolso dele, que é menor. Um desconto de 4% rende
4,17%. Toda tela, relatório e campo precisa dizer qual das duas está mostrando.
Ver [RN-07](01-dominio.md#rn-07--as-duas-taxas).

## Infraestrutura

- **Servidor:** VPS Hostinger (Ubuntu 22.04/24.04)
- **Domínio:** registrado na Locaweb — entra por um **registro A** apontando
  `caixa.<dominio>` para o IP da VPS. Os nameservers ficam na Locaweb para não
  derrubar o e-mail. Detalhes em [08-deploy.md](08-deploy.md).
- **Banco:** PostgreSQL 15+ (o DDL está em Postgres; adaptar para MySQL é direto)
- **API:** qualquer coisa que fale REST — FastAPI, Node/Express, Laravel
- **Front:** a página atual já é HTML+JS puro e pode virar o front quase sem
  mudança, trocando o estado embutido por chamadas à API
- **Agendador:** cron no servidor, ou um worker com fila para os robôs
- **Armazenamento de documentos:** sistema de arquivos do servidor, na mesma
  convenção de pastas que já está em uso (ver [07-migracao.md](07-migracao.md))

## Tamanho real do problema

Para calibrar expectativa: em três meses de operação são **7 operações, 11
duplicatas, 2 aportes**. O volume anual projetado fica na casa de 50 a 100
operações. Isso não é um sistema de alto volume — é um sistema que precisa estar
**certo**, não rápido. Escolha simplicidade sobre arquitetura.
