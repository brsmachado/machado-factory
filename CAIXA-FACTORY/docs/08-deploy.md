# 08 — Deploy: VPS Hostinger + domínio Locaweb

## 1. Decisão de DNS — leia antes de mexer

O domínio está na Locaweb e o e-mail provavelmente também. **Não troque os
nameservers da Locaweb para a Hostinger** sem antes copiar os registros MX: a
troca de nameservers derruba o e-mail no mesmo instante, e recuperar isso no
meio de um dia de trabalho é desagradável.

O caminho seguro é manter o DNS na Locaweb e criar **um registro A** apontando um
subdomínio para o IP da VPS:

| Tipo | Nome | Valor | TTL |
|---|---|---|---|
| A | `caixa` | `<IP da VPS Hostinger>` | 3600 |

Resultado: `caixa.machadoemb.com.br` → VPS. O site principal, o e-mail e todo o
resto continuam na Locaweb, intocados.

No painel da Locaweb isso fica em **Domínios → (seu domínio) → Zona de DNS →
Adicionar registro**. A propagação costuma levar de minutos a algumas horas;
confira com:

```bash
dig +short caixa.machadoemb.com.br
```

Só prossiga para o HTTPS quando esse comando devolver o IP da VPS — o Certbot
valida pelo DNS e falha se ainda estiver propagando.

## 2. Preparar a VPS

Ubuntu 22.04 ou 24.04. Primeiro acesso como root:

```bash
# usuário de trabalho, sem senha para sudo
adduser caixa
usermod -aG sudo caixa
rsync --archive --chown=caixa:caixa ~/.ssh /home/caixa

# desligar senha no SSH — só chave
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh

# firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

apt update && apt upgrade -y
apt install -y nginx postgresql postgresql-contrib python3-venv python3-pip \
               certbot python3-certbot-nginx fail2ban unattended-upgrades
systemctl enable --now fail2ban
dpkg-reconfigure -plow unattended-upgrades
```

`fail2ban` e `unattended-upgrades` não são luxo: uma VPS com IP público leva
tentativa de invasão na primeira hora de vida.

> **Atalho:** os passos de 2 a 8 estão automatizados em
> [`deploy/instalar.sh`](../deploy/instalar.sh). Clone o repositório em
> `/opt/caixa-factory/repo` (deploy key do GitHub, só leitura) e rode
> `sudo bash /opt/caixa-factory/repo/CAIXA-FACTORY/deploy/instalar.sh caixa.machadoemb.com.br seu@email`.
> O script pode rodar de novo a cada atualização (`git pull` antes). Ele não mexe
> no SSH. O banco entra pelo socket local com peer auth, sem senha no `.env`.

## 3. Banco

```bash
sudo -u postgres psql <<'SQL'
create user caixa with password 'TROQUE_ESTA_SENHA';
create database caixa_factory owner caixa;
\c caixa_factory
create schema caixa authorization caixa;
SQL
```

O Postgres fica ouvindo só em `localhost` (padrão) — **não abra a porta 5432 no
firewall**. A aplicação conversa com ele pelo socket local.

Rode o DDL de [02-modelo-dados.md](02-modelo-dados.md) e depois a carga de
[07-migracao.md](07-migracao.md).

## 4. Aplicação

```
/opt/caixa-factory/
  app/            código
  venv/           virtualenv
  documentos/     pedidos e comprovantes (o que hoje está em operacoes/AAAA-MM)
  .env            segredos — chmod 600
```

`.env`:

```ini
DATABASE_URL=postgresql://caixa:SENHA@localhost/caixa_factory
SECRET_KEY=<openssl rand -hex 32>
DOCUMENTOS_DIR=/opt/caixa-factory/documentos
TZ=America/Sao_Paulo
# do @BotFather
TELEGRAM_BOT_TOKEN=
# o seu chat com o robô (ele ignora qualquer outro)
TELEGRAM_CHAT_ID=
# seu usuário no sistema: os cliques no Telegram agem como você
TELEGRAM_USUARIO_EMAIL=
# leitura das fotos de pedido e comprovante (Claude)
ANTHROPIC_API_KEY=
ROBO_TOKEN=<openssl rand -hex 32>
```

Serviço systemd em `/etc/systemd/system/caixa-factory.service`:

```ini
[Unit]
Description=Caixa Factory
After=network.target postgresql.service

[Service]
User=caixa
WorkingDirectory=/opt/caixa-factory/app
EnvironmentFile=/opt/caixa-factory/.env
ExecStart=/opt/caixa-factory/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

# o processo não precisa de nada fora da própria pasta
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/caixa-factory/documentos

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now caixa-factory
```

## 5. Nginx + HTTPS

`/etc/nginx/sites-available/caixa-factory`:

```nginx
server {
    listen 80;
    server_name caixa.machadoemb.com.br;

    client_max_body_size 25M;          # comprovantes e PDFs

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/caixa-factory /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

certbot --nginx -d caixa.machadoemb.com.br --agree-tos -m bruno@machadoemb.com.br
```

O Certbot reescreve o bloco para 443 e instala a renovação automática. Confira:

```bash
systemctl status certbot.timer
certbot renew --dry-run
```

Depois do HTTPS, acrescente os cabeçalhos no bloco 443:

```nginx
add_header Strict-Transport-Security "max-age=31536000" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

## 6. Backup — a parte que ninguém faz e depois chora

São dados financeiros sem segunda via. Backup diário, fora da VPS.

`/opt/caixa-factory/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
DIA=$(date +%F)
DEST=/opt/caixa-factory/backups
mkdir -p "$DEST"

sudo -u postgres pg_dump -Fc caixa_factory > "$DEST/banco-$DIA.dump"
tar czf "$DEST/documentos-$DIA.tar.gz" -C /opt/caixa-factory documentos

# guarda 30 dias localmente
find "$DEST" -type f -mtime +30 -delete

# cópia fora da VPS — escolha um:
# rclone copy "$DEST" remoto:caixa-factory/     # Google Drive, S3, Backblaze
# rsync -az "$DEST/" usuario@outro-servidor:/backups/caixa-factory/
```

```bash
chmod +x /opt/caixa-factory/backup.sh
# crontab -e do usuário caixa
0 2 * * * /opt/caixa-factory/backup.sh >> /var/log/caixa-backup.log 2>&1
```

**Backup que nunca foi restaurado não é backup.** Uma vez por mês, restaure o
dump num banco de teste e rode a conferência de
[07-migracao.md](07-migracao.md#5-conferência-obrigatória-pós-carga).

A Hostinger oferece snapshot da VPS no painel — use **junto**, não no lugar: o
snapshot salva a máquina, o `pg_dump` salva os dados num formato que você
consegue abrir em qualquer lugar.

## 7. O robô

Um robô só, em dois pedaços: o serviço que conversa no Telegram e o aviso das
9h no cron.

```bash
cd /opt/caixa-factory/app && set -a && . ../.env && set +a
../venv/bin/python -m caixa_api.cli criar-robo        # usuário do robô, papel operador
../venv/bin/python -m caixa_api.robo aviso --mostrar  # confere o texto sem mandar
```

Para achar o `TELEGRAM_CHAT_ID`: mande qualquer mensagem para o robô e abra
`https://api.telegram.org/bot<TOKEN>/getUpdates` — o número está em
`message.chat.id`.

`/etc/systemd/system/caixa-robo.service`:

```ini
[Unit]
Description=Caixa Factory — robô do Telegram
After=network-online.target postgresql.service

[Service]
User=caixa
WorkingDirectory=/opt/caixa-factory/app
EnvironmentFile=/opt/caixa-factory/.env
ExecStart=/opt/caixa-factory/venv/bin/python -m caixa_api.robo telegram
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/caixa-factory/documentos

[Install]
WantedBy=multi-user.target
```

O robô usa long polling: não precisa de webhook nem de porta aberta.

```cron
# crontab do usuário caixa — fuso da VPS em America/Sao_Paulo
0 9 * * 1-5  cd /opt/caixa-factory/app && set -a && . ../.env && set +a && \
             ../venv/bin/python -m caixa_api.robo aviso >> /var/log/caixa-robo.log 2>&1
```

Num dia sem vencimento, atraso, dinheiro parado nem rascunho esperando, o aviso
não manda nada. `/aviso` no Telegram manda na hora.

Confirme o fuso da máquina antes:

```bash
timedatectl set-timezone America/Sao_Paulo
```

Uma VPS em UTC faz o robô das 9h disparar às 6h — erro silencioso e irritante.

## 8. Monitoramento mínimo

```cron
*/10 * * * * curl -fsS https://caixa.machadoemb.com.br/api/v1/saude > /dev/null \
             || echo "Caixa Factory fora do ar" | mail -s alerta bruno@machadoemb.com.br
```

Melhor ainda: um monitor externo gratuito (UptimeRobot, Better Stack) batendo em
`/api/v1/saude`. Monitor que roda na própria máquina não avisa quando a máquina
cai.

Lembre que `/saude` devolve o resultado da asserção de integridade do caixa — se
ela quebrar, os números estão errados e isso precisa acordar alguém.

## 9. Checklist de corte

- [ ] Registro A criado na Locaweb e propagado (`dig` devolvendo o IP)
- [ ] MX da Locaweb **intocados** — mande um e-mail de teste para confirmar
- [ ] HTTPS válido, cadeado no navegador, `certbot renew --dry-run` passando
- [ ] SSH só por chave, root bloqueado, ufw ativo
- [ ] Banco carregado e `v_caixa` batendo com a tabela de conferência
- [ ] Backup rodando e **uma restauração testada**
- [ ] Fuso da VPS em America/Sao_Paulo
- [ ] Token do robô diferente do token de usuário
- [ ] `caixa-robo` ativo e respondendo `/resumo` no Telegram
- [ ] Artefato antigo com o aviso de substituição, mas ainda no ar
