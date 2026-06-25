# Guia de Instalação — Sistema de Controle de Estoque
### Para a equipe de TI

Este documento ensina a instalar e colocar o sistema em funcionamento em um servidor
ou computador da empresa. Após a instalação, qualquer pessoa na rede poderá acessar
o sistema pelo navegador, sem instalar nada.

---

## O que você vai precisar

| Item | Detalhe |
|------|---------|
| Um computador/servidor que fique ligado | Windows 10/11 ou Ubuntu 20.04+ |
| Python 3.11 ou 3.12 instalado | Instruções no Passo 1 |
| Git instalado | Instruções no Passo 2 |
| Acesso à internet (só na instalação) | Para baixar o código e dependências |
| O endereço do repositório GitHub | `https://github.com/Murilo-Fruttuoso/inventory-system` |

---

## Passo 1 — Instalar o Python

### Windows

1. Acesse: **https://www.python.org/downloads/**
2. Clique no botão amarelo para baixar a versão mais recente (3.12.x)
3. Execute o instalador
4. **IMPORTANTE:** na primeira tela do instalador, marque a opção **"Add Python to PATH"**
5. Clique em **"Install Now"**
6. Quando terminar, abra o **Prompt de Comando** (tecla Windows → digite `cmd` → Enter)
7. Digite e pressione Enter:
   ```
   python --version
   ```
   Deve aparecer algo como `Python 3.12.x` — se aparecer, está correto.

### Ubuntu / Debian (Linux)

Abra o terminal e execute:
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 --version
```

---

## Passo 2 — Instalar o Git

### Windows

1. Acesse: **https://git-scm.com/download/win**
2. Baixe e execute o instalador — pode clicar em **"Next"** em todas as telas
3. Após instalar, abra o **Prompt de Comando** e verifique:
   ```
   git --version
   ```

### Ubuntu / Debian (Linux)

```bash
sudo apt install -y git
```

---

## Passo 3 — Baixar o código do sistema

Escolha uma pasta onde o sistema vai ficar instalado. Exemplos:
- Windows: `C:\sistemas\`
- Linux: `/opt/`

### Windows

Abra o Prompt de Comando e execute:
```cmd
mkdir C:\sistemas
cd C:\sistemas
git clone https://github.com/Murilo-Fruttuoso/inventory-system.git
cd inventory-system
```

### Linux

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone https://github.com/Murilo-Fruttuoso/inventory-system.git
sudo chown -R $USER:$USER /opt/inventory-system
cd /opt/inventory-system
```

---

## Passo 4 — Criar o ambiente virtual Python

O ambiente virtual isola as dependências do sistema. Execute dentro da pasta do projeto:

### Windows
```cmd
cd C:\sistemas\inventory-system
python -m venv venv
venv\Scripts\activate
```

### Linux
```bash
cd /opt/inventory-system
python3 -m venv venv
source venv/bin/activate
```

> Você saberá que funcionou quando aparecer `(venv)` no início da linha do terminal.

---

## Passo 5 — Instalar as dependências

Com o ambiente virtual **ativo** (aparece `(venv)` no terminal):

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> Isso vai baixar e instalar automaticamente tudo que o sistema precisa.
> Pode levar de 2 a 5 minutos dependendo da velocidade da internet.

---

## Passo 6 — Criar o arquivo de configuração

O sistema lê as configurações de um arquivo chamado `.env` na pasta raiz do projeto.

### Windows — crie com o Bloco de Notas

1. Abra o Bloco de Notas
2. Cole o conteúdo abaixo, **substituindo os valores em MAIÚSCULAS**:

```
SECRET_KEY=uma-frase-longa-e-aleatoria-qualquer-troque-isso
ADMIN_USER=admin
ADMIN_PASSWORD=TROQUE_PELA_SENHA_DO_ADMINISTRADOR
ADMIN_FULL_NAME=Administrador TI
ITEMS_PER_PAGE=20
```

3. Salve como **`.env`** (com ponto na frente) dentro da pasta `C:\sistemas\inventory-system\`
   - No Bloco de Notas: Arquivo → Salvar Como → mude "Tipo" para "Todos os arquivos" → nome: `.env`

### Linux — crie via terminal

```bash
cd /opt/inventory-system
nano .env
```

Cole o conteúdo abaixo, edite os valores e salve (Ctrl+O, Enter, Ctrl+X):

```
SECRET_KEY=uma-frase-longa-e-aleatoria-qualquer-troque-isso
ADMIN_USER=admin
ADMIN_PASSWORD=TROQUE_PELA_SENHA_DO_ADMINISTRADOR
ADMIN_FULL_NAME=Administrador TI
ITEMS_PER_PAGE=20
```

> **Não coloque a linha `DATABASE_URL`** — sem ela, o sistema usa SQLite automaticamente
> e o banco de dados fica salvo permanentemente na pasta `instance/estoque.db`.

---

## Passo 7 — Testar se o sistema funciona

Com o ambiente virtual ativo, execute:

### Windows
```cmd
cd C:\sistemas\inventory-system
venv\Scripts\activate
python run.py
```

### Linux
```bash
cd /opt/inventory-system
source venv/bin/activate
python run.py
```

Você deve ver algo como:
```
 * Running on http://0.0.0.0:5000
 * Press CTRL+C to quit
```

Abra o navegador no mesmo computador e acesse: **http://localhost:5000**

O sistema vai aparecer com a tela de login. Use:
- **Usuário:** o valor que você colocou em `ADMIN_USER` (ex: `admin`)
- **Senha:** o valor que você colocou em `ADMIN_PASSWORD`

Se o login funcionar, o sistema está instalado corretamente. Pressione **Ctrl+C** no
terminal para parar — vamos configurar o modo produção no próximo passo.

---

## Passo 8 — Rodar em modo produção (acesso pela rede)

O `python run.py` serve para testes. Para uso real, use o **Waitress** (Windows) ou
**Gunicorn** (Linux), que já estão incluídos nas dependências.

### Windows — Waitress

Com o ambiente virtual ativo:
```cmd
cd C:\sistemas\inventory-system
venv\Scripts\activate
waitress-serve --host=0.0.0.0 --port=8080 run:app
```

### Linux — Gunicorn

```bash
cd /opt/inventory-system
source venv/bin/activate
gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 120 run:app
```

O sistema agora está acessível em qualquer computador da rede pelo endereço:
**http://IP_DO_SERVIDOR:8080**

Para descobrir o IP do servidor:
- Windows: abra o cmd e execute `ipconfig` → procure "Endereço IPv4"
- Linux: execute `hostname -I`

---

## Passo 9 — Liberar a porta no firewall

Para que outros computadores consigam acessar o sistema:

### Windows

Abra o **Prompt de Comando como Administrador** e execute:
```cmd
netsh advfirewall firewall add rule name="Sistema Estoque" dir=in action=allow protocol=TCP localport=8080
```

### Linux (Ubuntu com ufw)

```bash
sudo ufw allow 8080/tcp
sudo ufw reload
```

---

## Passo 10 — Fazer o sistema iniciar automaticamente

Para que o sistema suba sozinho quando o servidor for ligado ou reiniciado:

### Windows — usando NSSM

**NSSM** é uma ferramenta gratuita que transforma qualquer programa em serviço do Windows.

1. Baixe o NSSM em: **https://nssm.cc/download**
2. Extraia o ZIP e copie o arquivo `nssm.exe` (da pasta `win64`) para `C:\Windows\System32\`
3. Abra o **Prompt de Comando como Administrador**
4. Execute:
   ```cmd
   nssm install SistemaEstoque
   ```
5. Uma janela vai abrir. Preencha:
   - **Path:** `C:\sistemas\inventory-system\venv\Scripts\waitress-serve.exe`
   - **Startup directory:** `C:\sistemas\inventory-system`
   - **Arguments:** `--host=0.0.0.0 --port=8080 run:app`
6. Clique na aba **"Environment"** e adicione:
   ```
   PATH=C:\sistemas\inventory-system\venv\Scripts;C:\Windows\System32
   ```
7. Clique em **"Install service"**
8. Inicie o serviço:
   ```cmd
   nssm start SistemaEstoque
   ```
9. Para verificar se está rodando:
   ```cmd
   nssm status SistemaEstoque
   ```

A partir de agora o sistema inicia automaticamente com o Windows.

### Linux — usando systemd

1. Crie o arquivo de serviço:
   ```bash
   sudo nano /etc/systemd/system/estoque.service
   ```

2. Cole o conteúdo abaixo (ajuste o caminho e usuário se necessário):
   ```ini
   [Unit]
   Description=Sistema de Controle de Estoque
   After=network.target

   [Service]
   Type=simple
   User=NOME_DO_USUARIO_DO_SERVIDOR
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
   > Substitua `NOME_DO_USUARIO_DO_SERVIDOR` pelo usuário Linux que instalou o sistema (ex: `ubuntu`, `user`, `ti`)

3. Ative e inicie:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable estoque
   sudo systemctl start estoque
   sudo systemctl status estoque
   ```
   Deve aparecer `Active: active (running)` em verde.

---

## Criar usuários adicionais

Após o primeiro acesso como administrador, crie os demais usuários pelo próprio sistema:

1. Acesse o sistema no navegador
2. Faça login como administrador
3. Clique em **Admin → Usuários** no menu superior
4. Clique em **"Novo Usuário"**
5. Preencha nome, usuário, senha e perfil de acesso

### Perfis de acesso disponíveis

| Perfil | O que pode fazer |
|--------|-----------------|
| **Administrador** | Acesso total, incluindo gestão de usuários |
| **Aprovador** | Aprova solicitações de compra |
| **Comprador** | Gerencia compras e orçamento |
| **Solicitante** | Abre solicitações, vê estoque e relatórios (sem orçamento) |
| **Usuário** | Somente dashboard e produtos |

---

## Backup dos dados

O banco de dados fica salvo em: `instance/estoque.db` (dentro da pasta do projeto).

### Pelo sistema (recomendado)

1. Acesse o sistema como administrador
2. Vá em **Relatórios**
3. Clique no botão **"Backup SQLite"**
4. O arquivo `estoque.db` será baixado para o seu computador

### Backup manual — copiar o arquivo

Simplesmente copie o arquivo `instance/estoque.db` para um HD externo, pendrive ou
pasta de rede. Para restaurar, basta substituir o arquivo e reiniciar o serviço.

### Agendamento automático no Windows (via Agendador de Tarefas)

1. Crie um arquivo `backup_estoque.bat` com o conteúdo:
   ```bat
   @echo off
   set ORIGEM=C:\sistemas\inventory-system\instance\estoque.db
   set DESTINO=C:\backup\estoque_%date:~6,4%%date:~3,2%%date:~0,2%.db
   copy "%ORIGEM%" "%DESTINO%"
   ```
2. Abra o **Agendador de Tarefas** do Windows
3. Crie uma tarefa para executar esse `.bat` diariamente

---

## Atualizações do sistema

Quando o desenvolvedor lançar uma atualização:

```bash
# 1. Entre na pasta do projeto
cd C:\sistemas\inventory-system     # Windows
# cd /opt/inventory-system          # Linux

# 2. Ative o ambiente virtual
venv\Scripts\activate               # Windows
# source venv/bin/activate          # Linux

# 3. Baixe as atualizações
git pull origin main

# 4. Atualize as dependências (se necessário)
pip install -r requirements.txt

# 5. Reinicie o serviço
nssm restart SistemaEstoque         # Windows
# sudo systemctl restart estoque    # Linux
```

> O sistema aplica atualizações do banco de dados automaticamente na reinicialização.
> Não é necessário executar nenhum script SQL manualmente.

---

## Solução de problemas

### "python não é reconhecido como comando" (Windows)
Reinstale o Python marcando **"Add Python to PATH"** na primeira tela do instalador.

### "pip não é reconhecido como comando"
Ative o ambiente virtual primeiro: `venv\Scripts\activate` (Windows) ou `source venv/bin/activate` (Linux).

### O sistema abre mas mostra "Internal Server Error"
Verifique os logs. Com o ambiente virtual ativo, pare o serviço e rode manualmente:
```bash
python run.py
```
O erro aparecerá no terminal.

### Não consigo acessar de outro computador
Verifique se o firewall está liberado (Passo 9) e se está usando o IP correto do servidor.

### Esqueci a senha do administrador
Com o ambiente virtual ativo, execute:
```bash
python -c "
from app import create_app
from app.extensions import db
from app.models import User
app = create_app()
with app.app_context():
    u = User.query.filter_by(username='admin').first()
    u.set_password('NovaSenha@2024')
    db.session.commit()
    print('Senha alterada.')
"
```

### Verificar se o serviço está rodando
```cmd
nssm status SistemaEstoque          # Windows
sudo systemctl status estoque       # Linux
```

---

*Sistema: Controle de Estoque — repositório: https://github.com/Murilo-Fruttuoso/inventory-system*
