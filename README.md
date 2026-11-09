# BarberFlow

Sistema de gestão para barbearias, desenvolvido para centralizar o atendimento ao cliente e as rotinas operacionais do estabelecimento em uma única plataforma.

## Visão geral

O BarberFlow reúne recursos para atendimento, agendamento, gestão de serviços, produtos e acompanhamento das atividades da barbearia.

### Área do cliente
- Apresentação dos serviços, preços e portfólio.
- Consulta de disponibilidade e agendamento on-line.
- Cadastro, autenticação e área para acompanhamento de agendamentos e pedidos.
- Loja on-line com catálogo de produtos, carrinho e checkout.

### Painel administrativo
- Dashboard com indicadores operacionais e financeiros.
- Gestão de agenda e agendamentos.
- Cadastro e manutenção de serviços, preços e duração.
- Gestão de produtos, categorias e estoque.
- Administração do portfólio de cortes.
- Acompanhamento de pedidos da loja.

## Requisitos

- Python compatível com as dependências definidas em `requirements.txt`.
- Docker Engine e Docker Compose, caso a implantação seja realizada por contêiner.
- Navegador web atualizado.
- Para disponibilização pública, domínio, HTTPS e serviço de hospedagem compatível.

## Instalação e execução

### Execução local

Instale as dependências:

```bash
pip install -r requirements.txt
```

Inicie a aplicação:

```bash
python app.py
```

Como alternativa, utilize o Uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Por padrão, a aplicação utiliza SQLite quando não há uma variável `DATABASE_URL` configurada.

### Execução com Docker Compose

Crie um arquivo `.env` na raiz do projeto e informe as credenciais iniciais e a chave de sessão:

```dotenv
INITIAL_ADMIN_EMAIL=admin@exemplo.com
INITIAL_ADMIN_PASSWORD=defina-uma-senha-forte
SECRET_KEY=defina-um-segredo-aleatorio-e-persistente
```

Gere uma chave segura com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Inicie os contêineres:

```bash
docker compose up --build -d
```

A aplicação ficará disponível em `http://localhost:8000`. O painel administrativo poderá ser acessado em `http://localhost:8000/admin`.

O banco SQLite é armazenado no volume persistente `barberflow_data`. Evite utilizar `docker compose down -v` em ambientes com dados que devam ser preservados, pois esse comando remove os volumes associados.

## Configuração para produção

Antes de disponibilizar o sistema publicamente:

- Defina `ENVIRONMENT=production`.
- Configure uma `SECRET_KEY` forte, persistente e armazenada de forma segura.
- Configure `COOKIE_SECURE=1` quando a aplicação estiver operando com HTTPS.
- Publique a aplicação atrás de um proxy ou serviço com HTTPS.
- Configure o serviço SMTP e a URL pública HTTPS para habilitar o envio de mensagens e a recuperação de senha.
- Utilize armazenamento persistente para o banco de dados e para os arquivos enviados ao sistema.
- Mantenha rotinas de backup e procedimentos testados de restauração.

Não exponha a aplicação publicamente sem HTTPS. Não armazene credenciais reais no repositório ou em arquivos versionados.

## Cadastro e primeiro acesso do cliente

O cliente pode realizar o cadastro pela área pública. Quando o cadastro é realizado pela administração, os dados são registrados no painel e o próprio cliente define sua senha por meio do fluxo de primeiro acesso.

Para cadastros existentes, o sistema encaminha um link individual e temporário ao endereço de e-mail registrado. O link expira após 30 minutos. O envio depende da configuração correta do SMTP e da URL pública HTTPS.

O CPF é utilizado na identificação do cadastro e deve ser único. A informação do CPF, isoladamente, não permite criar ou redefinir uma senha.

## Segurança

- Senhas armazenadas com hash PBKDF2.
- Sessões assinadas e cookies HTTP-only.
- Chave de sessão configurável por variável de ambiente.
- Criação da conta administrativa inicial por credenciais definidas no ambiente.
- Fluxo de recuperação de senha com link temporário enviado por e-mail.

A chave `SECRET_KEY` deve ser mantida em sigilo e não deve ser alterada sem planejamento, pois é utilizada em mecanismos de segurança da aplicação. Proteja também as credenciais SMTP e as cópias de segurança.

## Ambiente de demonstração

As instruções para preparar uma base de demonstração com dados fictícios estão disponíveis em [docs/DEMONSTRACAO.md](docs/DEMONSTRACAO.md). O procedimento utiliza uma base separada e não deve ser executado apontando para o banco de dados operacional.
