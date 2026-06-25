# Guia de Deploy Local — Sistema de Controle de Estoque

Este guia explica como instalar e executar o sistema em um servidor local da empresa,
substituindo o ambiente Render (nuvem) por um servidor próprio com SQLite.

---

## Requisitos do Servidor

| Item | Mínimo | Recomendado |
|------|--------|-------------|
| Sistema Operacional | Windows 10/11, Ubuntu 20.04+, Debian 11+ | Ubuntu 22.04 LTS |
| Python | 3.10 | 3.11 ou 3.12 |
| RAM | 1 GB livre | 2 GB+ |
| Disco | 500 MB livre | 2 GB+ |
| Rede | Acesso à rede local | IP fixo na rede |

> **Nota:** O sistema usa SQLite como banco de dados — não é necessário instalar PostgreSQL, MySQL ou qualquer outro servidor de banco de dados.

---

## 1. Instalar o Python

### Windows
1. Acesse https://www.python.org/downloads/ e baixe o Python 3.11 ou 3.12
2. Execute o instalador e marque **"Add Python to PATH"** antes de clicar em Install
3. Verifique a instalação: abra o Prompt de Comando (cmd) e execute:
   ```
   python --version
   ```

### Ubuntu / Debian
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
python3 --version
```

---

## 2. Baixar o Código-Fonte

### Opção A — Via Git (recomendado, permite atualizações fáceis)

```bash
git clone https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git inventory-system
cd inventory-system
```

> Substitua a URL pelo endereço real do repositório. Se o repositório for privado, você precisará de credenciais Git.

### Opção B — Arquivo ZIP

1. Faça o download do ZIP do repositório
2. Extraia em uma pasta de sua escolha, por exemplo: `C:\sistemas\inventory-system` (Windows) ou `/opt/inventory-system` (Linux)
3. Abra o terminal e navegue até a pasta extraída

---

## 3. Criar o Ambiente Virtual Python

O ambiente virtual isola as dependências do sistema para não conflitar com outros programas.

### Windows (Prompt de Comando ou PowerShell)
```cmd
cd C:\sistemas\inventory-system
python -m venv venv
venv\Scripts\activate
```

### Linux / macOS
```bash
cd /opt/inventory-system
python3 -m venv venv
source venv/bin/activate
```

> Você saberá que o ambiente está ativo quando o prompt mostrar `(venv)` na frente.

---

## 4. Instalar as Dependências

Com o ambiente virtual ativo:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> A instalação pode levar alguns minutos na primeira vez.

---

## 5. Configurar o Arquivo `.env`

Crie (ou edite) o arquivo `.env` na raiz do projeto. Ele não deve ser commitado no Git.

```bash
# Linux/macOS
cp .env.example .env   # se existir
# OU crie manualmente:
nano .env
```

**Windows** — abra o bloco de notas e salve como `.env` na raiz do projeto.

### Conteúdo do `.env` para uso local (SQLite):

```ini
# Chave secreta — TROQUE por uma string longa e aleatória em produção!
# Gere uma: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=troque-esta-chave-por-uma-segura-em-producao

# Banco de dados: DEIXE EM BRANCO ou remova esta linha para usar SQLite local
# Não coloque DATABASE_URL para não tentar conectar no PostgreSQL do Render
DATABASE_URL=

# Usuário administrador padrão (criado automaticamente no primeiro acesso)
ADMIN_USER=admin
ADMIN_PASSWORD=SenhaForte@2024
ADMIN_FULL_NAME=Administrador TI

# Itens por página nas listagens
ITEMS_PER_PAGE=20
```

> **IMPORTANTE:** Não defina `DATABASE_URL` com valor `postgres://...`. Deixe em branco ou remova a linha para que o sistema use SQLite automaticamente.

---

## 6. Migrar os Dados do Render (PostgreSQL → SQLite)

> **Pule esta seção se for uma instalação do zero (banco vazio).**

Se você tem dados no Render que precisa migrar para o servidor local:

### 6.1 Exportar do Render

No painel do Render, acesse o serviço PostgreSQL → **Backups** → faça o download do dump mais recente.

Ou via linha de comando (com `pg_dump` instalado):
```bash
pg_dump "postgresql://USER:SENHA@HOST:PORT/DBNAME" \
  --format=plain --no-owner --no-privileges \
  --file=backup_render.sql
```

### 6.2 Converter para SQLite

O dump PostgreSQL não é diretamente compatível com SQLite. Use o script de migração incluído:

```bash
# Com o ambiente virtual ativo
python migrate.py
```

Ou entre em contato com o desenvolvedor para fazer a migração assistida.

### 6.3 Alternativa: Usar o Backup SQLite do Sistema

Se você usou o botão **"Backup SQLite"** no painel de Relatórios enquanto o sistema ainda estava em modo SQLite local, copie o arquivo `estoque.db` para a pasta `instance/`:

```bash
cp /caminho/do/backup/estoque.db instance/estoque.db
```

---

## 7. Iniciar o Sistema

### Modo Desenvolvimento (testes, não usar em produção)

```bash
# Com o ambiente virtual ativo
python run.py
```

O sistema estará disponível em: **http://localhost:5000**

### Modo Produção com Waitress (Windows — recomendado)

`waitress` já está nas dependências e funciona bem no Windows sem configuração adicional:

```bash
# Com o ambiente virtual ativo
waitress-serve --host=0.0.0.0 --port=8080 "run:app"
```

O sistema estará disponível em: **http://IP_DO_SERVIDOR:8080**

### Modo Produção com Gunicorn (Linux — recomendado)

```bash
# Com o ambiente virtual ativo
gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 120 run:app
```

---

## 8. Acesso pela Rede Local

Para que outros computadores da empresa acessem o sistema:

1. **Descubra o IP do servidor:**
   - Windows: `ipconfig` no cmd → procure "Endereço IPv4"
   - Linux: `ip addr show` ou `hostname -I`

2. **Libere a porta no firewall:**

   **Windows:**
   ```
   netsh advfirewall firewall add rule name="Estoque App" dir=in action=allow protocol=TCP localport=8080
   ```

   **Ubuntu/Debian:**
   ```bash
   sudo ufw allow 8080/tcp
   ```

3. **Acesso dos outros PCs:** abra o navegador e acesse `http://192.168.X.X:8080`
   (substitua pelo IP real do servidor)

---

## 9. Executar como Serviço (início automático)

Para que o sistema inicie automaticamente quando o servidor ligar:

### Windows — Usando NSSM (Non-Sucking Service Manager)

1. Baixe o NSSM: https://nssm.cc/download
2. Extraia e abra um prompt de comando como **Administrador**
3. Execute:
   ```cmd
   nssm install InventarioEstoque
   ```
4. Na tela que abrir, configure:
   - **Path:** `C:\sistemas\inventory-system\venv\Scripts\waitress-serve.exe`
   - **Arguments:** `--host=0.0.0.0 --port=8080 run:app`
   - **Startup directory:** `C:\sistemas\inventory-system`
5. Clique em **Install service**
6. Inicie o serviço:
   ```cmd
   nssm start InventarioEstoque
   ```

### Linux — Usando systemd

Crie o arquivo de serviço:

```bash
sudo nano /etc/systemd/system/estoque.service
```

Conteúdo do arquivo:

```ini
[Unit]
Description=Sistema de Controle de Estoque
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/inventory-system
Environment="PATH=/opt/inventory-system/venv/bin"
ExecStart=/opt/inventory-system/venv/bin/gunicorn \
    --bind 0.0.0.0:8080 \
    --workers 2 \
    --timeout 120 \
    run:app
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Ative e inicie o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable estoque
sudo systemctl start estoque
sudo systemctl status estoque
```

---

## 10. Backup dos Dados

### Backup pelo Sistema (recomendado)

No sistema, vá em **Relatórios → Backup SQLite** — disponível apenas para administradores.
O download do arquivo `estoque.db` será iniciado automaticamente.

> Este botão só aparece em modo SQLite local. Em PostgreSQL (Render) ele fica desabilitado.

### Backup Manual

Copie o arquivo `instance/estoque.db` para um local seguro (HD externo, NAS, etc.):

```bash
# Linux — copia com timestamp
cp instance/estoque.db /backup/estoque_$(date +%Y%m%d_%H%M%S).db
```

**Windows — agendar backup automático:**
1. Abra o **Agendador de Tarefas**
2. Crie uma tarefa básica para copiar `instance\estoque.db` para uma pasta de backup
3. Configure para rodar diariamente

---

## 11. Atualizações do Sistema

Quando houver novas versões do sistema:

```bash
# 1. Entre na pasta do projeto
cd /opt/inventory-system   # ou C:\sistemas\inventory-system no Windows

# 2. Ative o ambiente virtual
source venv/bin/activate   # Linux
# venv\Scripts\activate   # Windows

# 3. Baixe as atualizações
git pull origin main

# 4. Atualize as dependências (se necessário)
pip install -r requirements.txt

# 5. Reinicie o serviço
sudo systemctl restart estoque   # Linux com systemd
# nssm restart InventarioEstoque  # Windows com NSSM
```

> O sistema aplica migrações de banco de dados automaticamente na inicialização — não é necessário executar scripts SQL manualmente.

---

## 12. Solução de Problemas

### Erro: "python não reconhecido como comando"
- Windows: reinstale o Python marcando "Add Python to PATH"
- Linux: use `python3` em vez de `python`

### Erro: "No module named 'flask'"
- Verifique se o ambiente virtual está ativo (deve aparecer `(venv)` no prompt)
- Execute novamente: `pip install -r requirements.txt`

### Erro: "Address already in use" (porta ocupada)
- Outro processo está usando a porta 8080. Troque para outra porta (ex: 8090):
  ```bash
  gunicorn --bind 0.0.0.0:8090 run:app
  ```

### Acesso negado ao arquivo `estoque.db`
- Linux: verifique as permissões:
  ```bash
  chmod 664 instance/estoque.db
  chown www-data:www-data instance/estoque.db
  ```

### Sistema abre mas mostra "Internal Server Error"
- Verifique os logs:
  ```bash
  # Linux com systemd
  journalctl -u estoque -n 50
  # Ou diretamente
  python run.py   # mostra erros no terminal
  ```

### Esqueceu a senha do administrador
- **Somente em emergência**, com acesso direto ao servidor:
  ```bash
  # Com o ambiente virtual ativo
  python -c "
  from app import create_app
  from app.extensions import db
  from app.models import User
  app = create_app()
  with app.app_context():
      u = User.query.filter_by(username='admin').first()
      u.set_password('NovaSenha@2024')
      db.session.commit()
      print('Senha alterada com sucesso.')
  "
  ```

---

## 13. Estrutura de Arquivos

```
inventory-system/
├── app/                  # Código principal da aplicação
│   ├── __init__.py       # Fábrica da app Flask
│   ├── models.py         # Modelos do banco de dados
│   ├── routes.py         # Rotas principais (dashboard, movimentações, relatórios)
│   ├── routes_purchasing.py   # Módulo de compras
│   ├── routes_budget.py  # Módulo de orçamento e fornecedores
│   └── ...
├── templates/            # Arquivos HTML (Jinja2)
├── static/               # CSS, JS, imagens
├── instance/             # Pasta gerada automaticamente
│   └── estoque.db        # Banco de dados SQLite (NÃO versionar)
├── .env                  # Configurações locais (NÃO versionar)
├── requirements.txt      # Dependências Python
├── run.py                # Ponto de entrada
└── config.py             # Configurações da aplicação
```

---

## 14. Informações de Contato e Suporte

Para dúvidas técnicas sobre o sistema, entre em contato com o desenvolvedor responsável ou
consulte o histórico de alterações no repositório Git.

---

*Última atualização: Junho 2026*
