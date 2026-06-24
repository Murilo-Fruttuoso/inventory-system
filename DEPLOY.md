# Deploy no Render — Guia de Configuração

## Por que os dados somem?

O Render usa um **filesystem efêmero** para aplicações web. Isso significa que:
- A cada novo deploy (push no GitHub), o servidor é recriado do zero
- Arquivos locais (como `instance/estoque.db`) **são apagados**
- O banco SQLite **não persiste** entre deploys

## Solução: PostgreSQL no Render

O Render oferece um banco PostgreSQL gratuito que persiste permanentemente.

---

## Passo a Passo

### 1. Criar banco PostgreSQL no Render

1. Acesse https://dashboard.render.com
2. Clique em **"New +"** → **"PostgreSQL"**
3. Configure:
   - **Name**: `inventory-db`
   - **Plan**: Free
4. Clique em **"Create Database"**
5. Aguarde o banco ser criado (~1 minuto)
6. Copie a **"Internal Database URL"** (começa com `postgresql://...`)

### 2. Configurar variáveis de ambiente no serviço web

No painel do seu serviço web no Render, vá em **"Environment"** e adicione:

| Variável | Valor |
|----------|-------|
| `DATABASE_URL` | Cole a URL do PostgreSQL copiada acima |
| `SECRET_KEY` | Uma string aleatória longa (ex: `openssl rand -hex 32`) |
| `ADMIN_USER` | `admin` |
| `ADMIN_PASSWORD` | Sua senha do admin |
| `ADMIN_FULL_NAME` | `Administrador` |
| `SEED_USERS` | JSON com seus usuários (ver abaixo) |

### 3. Configurar SEED_USERS

Esta variável garante que seus usuários sejam **sempre recriados** mesmo após
um novo deploy, sem apagar usuários que já existem.

Formato JSON (coloque tudo em uma linha):
```json
[{"username":"mfruttuoso","full_name":"Murilo Fruttuoso","role":"admin","password":"SUA_SENHA"},{"username":"aprovador","full_name":"Nome Aprovador","role":"approver","password":"SENHA_APROVADOR"}]
```

**Roles disponíveis**: `admin`, `approver`, `buyer`, `user`

> ⚠️ Guarde essas senhas em local seguro. Após o primeiro login você pode
> alterá-las pelo painel de Usuários.

### 4. Fazer o deploy

Após configurar as variáveis:
```bash
git push origin main
```

O Render vai detectar o push e fazer o deploy automaticamente.

---

## Como funciona o seed de usuários

O sistema usa `app/seed.py` que é executado automaticamente a cada inicialização:

1. Lê as variáveis `ADMIN_USER` / `ADMIN_PASSWORD` / `SEED_USERS`
2. Para cada usuário configurado, verifica se já existe no banco
3. **Se não existir**: cria o usuário
4. **Se já existir**: não faz nada (não sobrescreve senhas/dados)

Isso garante que:
- Após um deploy limpo, os usuários são recriados automaticamente
- Usuários criados pela interface nunca são apagados
- Senhas alteradas pela interface são preservadas

---

## Migração de dados do SQLite para PostgreSQL

Se você já tem dados no SQLite que quer mover para o PostgreSQL:

1. Configure o `DATABASE_URL` para o PostgreSQL no Render
2. Faça o deploy — as tabelas serão criadas automaticamente
3. Os usuários do `SEED_USERS` serão criados
4. Re-importe o Plano de Contas e Orçamentos via `/budget/accounts/import`
   e `/budget/monthly/import` usando os arquivos Excel originais
