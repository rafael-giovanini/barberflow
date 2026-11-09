# BarberFlow

Sistema web de gestão para barbearias, com área pública para clientes e painel administrativo para operação do estabelecimento.

> **Estado desta branch:** a implementação disponível em `feature/clientes-senhas` utiliza SQLite. O suporte PostgreSQL/Neon e a migração SQLite → PostgreSQL ainda dependem da integração e validação dos módulos existentes em outra branch. Não configure `DATABASE_URL` nesta branch esperando que o backend mude para PostgreSQL.

## Funcionalidades

### Área do cliente
- Apresentação de serviços, preços e portfólio.
- Consulta de disponibilidade e solicitação de agendamentos.
- Cadastro, autenticação e área do cliente.
- Loja on-line, catálogo, carrinho e pedidos.
- Primeiro acesso, alteração e recuperação de senha por e-mail.

### Painel administrativo
- Dashboard operacional e financeiro.
- Gestão de agenda e agendamentos.
- Cadastro e manutenção de clientes e barbeiros.
- Gestão de serviços, preços e duração.
- Gestão de produtos, categorias, estoque e movimentações.
- Administração do portfólio.
- Acompanhamento de pedidos.
- Lançamentos financeiros, comissões, confirmações, estornos e exportação CSV.
- Configurações da barbearia e SMTP.

## Tecnologias

- Python 3.12
- FastAPI e Uvicorn
- Jinja2
- SQLite nesta branch
- Docker e Docker Compose (opcionais)

As versões das dependências estão fixadas em `requirements.txt`.

## Requisitos

- Python 3.12 recomendado.
- Navegador atualizado.
- Docker Engine e Docker Compose, se utilizar contêiner.
- Para produção: domínio, HTTPS, armazenamento persistente e serviço SMTP.

## Instalação local

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```

Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8000
```

Acesse http://127.0.0.1:8000.

## Banco de dados

Nesta branch, a aplicação utiliza SQLite. O arquivo padrão é `barbearia.db`, localizado junto a `database.py`. A variável `DATABASE_PATH` permite definir outro caminho. O banco precisa estar em armazenamento persistente e com permissões adequadas para o processo da aplicação.

O banco é inicializado pela aplicação e o esquema recebe atualizações compatíveis na inicialização. Faça backup antes de qualquer atualização.

**PostgreSQL/Neon:** não está ativo nesta branch. Os arquivos necessários ao backend PostgreSQL e ao utilitário de migração não fazem parte deste snapshot. Consulte o manual completo e aguarde a integração validada antes de utilizar esse modo.

## Configuração

Use `.env.example` como referência e configure variáveis diretamente no ambiente de execução ou no gerenciador de segredos da hospedagem. Não versione credenciais reais.

Variáveis relevantes:
- `DATABASE_PATH`: caminho do banco SQLite.
- `SECRET_KEY`: segredo aleatório persistente, mínimo de 32 caracteres em produção.
- `ENVIRONMENT=production`: ativa verificações de produção.
- `COOKIE_SECURE=1`: cookie seguro para HTTPS.
- `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD`: credenciais de provisionamento inicial, quando aplicável.
- `APP_BASE_URL`: URL pública HTTPS usada nos links de e-mail.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SECURITY`: configuração de e-mail.

Gere um segredo com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Mantenha `SECRET_KEY` estável e protegida. A troca pode invalidar sessões e impedir a descriptografia da senha SMTP já armazenada.

## Docker Compose

Configure as variáveis de ambiente e execute:

```bash
docker compose up --build -d
docker compose logs -f barberflow
```

O Compose mantém o SQLite em um volume persistente chamado `barberflow_data`. O comando `docker compose down -v` remove os volumes e pode apagar o banco; utilize-o somente quando essa remoção for intencional e houver backup.

## Segurança e produção

Antes de publicar:
- Utilize HTTPS e proxy reverso corretamente configurado.
- Defina `ENVIRONMENT=production` e `SECRET_KEY` forte e persistente.
- Garanta persistência do banco e dos arquivos em `uploads/`.
- Configure e teste SMTP e recuperação de senha.
- Revise a conta administrativa e remova credenciais temporárias.
- Configure backups, retenção e testes de restauração.
- Execute testes automatizados e valide permissões por perfil.
- Não exponha credenciais, tokens ou dados pessoais em logs.

O sistema processa dados pessoais, incluindo CPF e endereço. A operação deve estabelecer políticas, bases legais, controles e procedimentos compatíveis com a LGPD. A implementação técnica, isoladamente, não comprova conformidade integral.

## Demonstração

A rotina `seed_demo.py` cria uma base SQLite separada com dados fictícios. Leia [docs/DEMONSTRACAO.md](docs/DEMONSTRACAO.md) antes de executá-la. Nunca aponte o seed para uma base operacional. O parâmetro `--reset` apaga a base de demonstração indicada.

## Testes

Execute localmente:

```bash
python -m compileall -q app.py auth.py database.py security_routes.py
python -m unittest discover -s tests -v
```

O workflow `.github/workflows/validate.yml` executa validação de sintaxe e testes unitários em pushes para `main` e branches `feature/**`, e em pull requests destinados a `main`. Considere testes aprovados somente quando houver execução concluída vinculada ao SHA do commit avaliado.

## Documentação

- [Manual completo do BarberFlow](docs/MANUAL-COMPLETO.md)
- [Implantação e recuperação](docs/IMPLANTACAO-E-RECUPERACAO.md)
- [Ambiente de demonstração](docs/DEMONSTRACAO.md)
- [Plano de melhorias de clientes e senhas](docs/PLANO-MELHORIAS-CLIENTES-SENHAS.md)

## Limitações conhecidas desta branch

- Backend SQLite; PostgreSQL/Neon depende de integração pendente.
- Arquitetura multiempresa Database per Tenant ainda não implementada neste snapshot.
- Não foi confirmada integração com gateway de pagamento ou emissão fiscal.
- O armazenamento local de arquivos e SQLite exige avaliação antes de escalar para múltiplas instâncias.

A documentação deve acompanhar cada alteração de funcionalidade, arquitetura, segurança, persistência e implantação.
