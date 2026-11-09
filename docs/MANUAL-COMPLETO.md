# Manual completo do BarberFlow

**Documentação técnica e operacional**  
**Escopo:** código disponível na branch feature/clientes-senhas  
**Revisão de referência:** 09/11/2026

> Este manual descreve o comportamento identificado no código-fonte desta branch. Não substitui testes de aceitação em ambiente real. Recursos planejados ou existentes somente em outras branches são identificados como pendentes de integração.

## 1. Apresentação

O BarberFlow é uma aplicação web para gestão de barbearias. Reúne uma área pública para clientes e um painel interno para administrar agenda, serviços, barbeiros, clientes, produtos, estoque, pedidos, configurações e movimentações financeiras.

A aplicação foi construída em Python, com FastAPI, páginas HTML renderizadas por Jinja2 e persistência SQLite nesta branch.

### 1.1 Objetivos funcionais

- Disponibilizar informações da barbearia, serviços e portfólio.
- Permitir cadastro e autenticação de clientes.
- Permitir consulta de horários e solicitação de agendamentos.
- Apoiar a administração de barbeiros, serviços e agenda.
- Controlar catálogo, estoque e pedidos da loja.
- Registrar receitas, despesas, comissões e estornos.
- Permitir configuração visual e de envio de e-mails.
- Oferecer experiência web adaptável a dispositivos móveis.

### 1.2 Limites

Não foi confirmada nesta branch integração com meios de pagamento, emissão fiscal, WhatsApp, aplicativos nativos, sincronização externa de calendários ou arquitetura multiempresa operacional.

## 2. Perfis de acesso

O sistema utiliza o campo role da tabela users. Os perfis identificados são:

| Perfil | Finalidade |
|---|---|
| admin | Administração da barbearia e acesso ao painel administrativo. |
| barber | Perfil profissional de barbeiro, associado a um registro em barbers. |
| customer | Cliente que utiliza cadastro, login, área do cliente e agendamentos. |

As permissões devem ser verificadas no servidor; ocultar links na interface não substitui autorização. Antes de uma implantação comercial, valide por testes de autorização cada rota e cada perfil, inclusive tentativas de acesso direto por URL.

## 3. Funcionalidades

### 3.1 Área pública

- Página inicial: apresenta conteúdo institucional, serviços ativos, portfólio e produtos disponíveis.
- Serviços: lista serviços ativos, descrições, categorias, preços e duração.
- Portfólio: apresenta exemplos de cortes e trabalhos cadastrados.
- Agendamento: permite selecionar serviço, barbeiro e horário.
- Loja: apresenta produtos ativos com estoque disponível.
- Carrinho: permite adicionar, atualizar e remover itens.
- Cadastro e login: permitem criação de conta e autenticação.
- Área do cliente: apresenta informações e funcionalidades vinculadas à conta autenticada.

### 3.2 Agendamentos

O agendamento relaciona cliente, barbeiro e serviço. São armazenados data, horário inicial e final, situação, observações e preço do serviço no momento da contratação.

A disponibilidade é consultada por GET /api/slots; a solicitação é enviada por POST /api/agendar. O painel permite acompanhar a agenda e alterar a situação do agendamento.

A disponibilidade exibida depende dos horários de trabalho, dias configurados, intervalo de almoço e compromissos registrados. A operação deve validar conflitos no servidor; a interface não é fonte definitiva de disponibilidade.

### 3.3 Clientes e credenciais

O cliente pode se cadastrar pela área pública. A administração também dispõe de fluxo para cadastrar clientes e enviar instruções para criação da senha.

O CPF é normalizado para dígitos e validado por seus dígitos verificadores. A base aplica índice único parcial para CPFs preenchidos. O cadastro também contempla data de nascimento e endereço.

O fluxo de primeiro acesso utiliza link temporário enviado por e-mail. A recuperação de senha utiliza token de uso único, com prazo de expiração. A troca ou redefinição da senha incrementa a versão da sessão, invalidando sessões anteriores.

A senha deve ter pelo menos 10 caracteres nos fluxos de criação e redefinição identificados nesta branch. O sistema não deve enviar senha em texto por e-mail.

### 3.4 Barbeiros

O painel permite cadastrar, editar e desativar registros profissionais. O cadastro profissional pode estar associado a uma conta de usuário.

O registro contempla nome, biografia, foto, situação, horário de início e fim de expediente, intervalo de almoço e dias de trabalho.

### 3.5 Serviços

O painel permite manter nome, descrição, preço, duração, categoria, imagem e situação. Serviços inativos deixam de ser oferecidos nos fluxos públicos que consultam somente serviços ativos.

O preço do serviço é preservado no agendamento por meio de um campo de snapshot em centavos, evitando que uma alteração posterior do preço do catálogo modifique o histórico.

### 3.6 Produtos e estoque

O catálogo contém nome, descrição, preço, quantidade em estoque, imagem, categoria, situação e custo unitário.

O sistema registra movimentos de estoque, incluindo abertura, compra, venda, ajuste e devolução. As movimentações guardam quantidade, custo unitário em centavos, observação, pedido relacionado, usuário responsável e data.

As entradas e saídas devem ser conferidas no histórico de movimentações. Não se recomenda alterar diretamente quantidades no banco sem registrar a operação correspondente.

### 3.7 Loja e pedidos

O cliente pode adicionar produtos ao carrinho, alterar quantidades e finalizar um pedido. O carrinho é transportado em cookie e normalizado no servidor: produtos e quantidades são convertidos para inteiros e quantidades inválidas ou excessivas são descartadas.

O total deve ser calculado com base nos preços consultados no banco, nunca confiando em valores enviados pelo navegador. O pedido armazena dados do cliente, endereço, total, situação, forma de pagamento informada e itens com cópia do nome e preço do produto no momento da compra.

A existência do campo de forma de pagamento não significa integração com adquirente ou gateway. A confirmação financeira deve seguir o processo operacional da barbearia.

### 3.8 Financeiro e comissões

O painel financeiro registra receitas e despesas, categoria, descrição, valor, data de ocorrência, forma de pagamento, situação, barbeiro e vínculos com pedido ou agendamento.

Os valores financeiros são armazenados em centavos. O sistema possui configurações de percentual de comissão por barbeiro, lançamento manual, confirmação e estorno. Há exportação de dados financeiros em CSV.

Um estorno deve preservar o histórico da operação original e criar o registro de reversão correspondente, em vez de apagar movimentações históricas. A conciliação com extratos bancários e comprovantes permanece uma atividade administrativa.

### 3.9 Configurações e experiência móvel

O painel disponibiliza configurações da barbearia, incluindo dados de apresentação, logo e parâmetros visuais, além de configuração SMTP e URL pública utilizada nos links de acesso.

A senha SMTP é armazenada criptografada na tabela de configurações. A chave de criptografia deriva da SECRET_KEY; portanto, a troca dessa chave pode impedir a leitura da senha SMTP previamente armazenada, exigindo novo cadastramento.

O repositório contém página e manifesto associados à experiência móvel/PWA. Isso permite acesso pelo navegador e recursos de instalação suportados pelo navegador. Não caracteriza, por si só, aplicativo nativo distribuído em lojas.

## 4. Arquitetura técnica desta branch

### 4.1 Componentes

| Componente | Responsabilidade |
|---|---|
| app.py | Aplicação FastAPI, rotas públicas, agenda, loja, painel, middleware e inicialização. |
| security_routes.py | Rotas de clientes, primeiro acesso, alteração e recuperação de senha. |
| auth.py | Hash/verificação de senha e validação de CPF/data de nascimento. |
| database.py | Conexões SQLite, criação de tabelas e atualizações compatíveis do esquema. |
| smtp_settings.py | Leitura, validação, criptografia e persistência de configuração SMTP. |
| templates/ | Páginas HTML Jinja2. |
| static/ | CSS, favicon e recursos estáticos. |
| tests/ | Testes automatizados de autenticação, rotas, integridade, migração e demonstração. |

### 4.2 Fluxo de requisição

1. O navegador envia uma requisição HTTP.
2. O FastAPI recebe a requisição e executa o middleware global.
3. O middleware carrega configurações e verifica o cabeçalho Origin em requisições de escrita quando ele está presente.
4. A rota aplica autenticação e autorização conforme o perfil.
5. A aplicação consulta ou altera o banco por meio de get_db().
6. A resposta é renderizada por Jinja2 ou devolvida como redirecionamento/JSON.
7. Cabeçalhos defensivos são adicionados à resposta.

### 4.3 Tecnologias

- Python 3.12 no workflow de CI e na imagem Docker.
- FastAPI e Uvicorn para aplicação ASGI.
- Jinja2 para renderização de páginas.
- SQLite para persistência nesta branch.
- ItsDangerous para assinatura de dados de sessão.
- Bibliotecas padrão do Python para hash de senha, e-mail SMTP e operações auxiliares.
- Docker e Docker Compose como alternativa de empacotamento.

As versões exatas das dependências estão em requirements.txt. Consulte esse arquivo antes de atualizar o ambiente.

### 4.4 Persistência e banco de dados

Nesta branch, database.py usa SQLite. O caminho padrão é barbearia.db, no diretório do projeto, podendo ser substituído por DATABASE_PATH.

O SQLite é aberto com chave estrangeira habilitada e timeout de espera para contenção. O inicializador cria tabelas e acrescenta campos ausentes por migrações compatíveis. Qualquer atualização de esquema deve ser precedida de backup e validada em cópia.

**Atenção à divergência entre branches:** este snapshot de feature/clientes-senhas não contém database_postgres.py, db_compat.py nem migrate_sqlite_to_postgres.py. Portanto, não configure DATABASE_URL esperando que esta branch utilize Neon/PostgreSQL. O suporte PostgreSQL existente em outra branch precisa ser integrado, revisado e testado antes de ser considerado disponível nesta versão.

### 4.5 Estrutura de diretórios

    barberflow/
    ├── app.py
    ├── security_routes.py
    ├── auth.py
    ├── database.py
    ├── smtp_settings.py
    ├── seed_demo.py
    ├── requirements.txt
    ├── Dockerfile
    ├── compose.yaml
    ├── .env.example
    ├── docs/
    ├── tests/
    ├── templates/
    │   └── admin/
    └── static/

## 5. Modelo de dados

As tabelas identificadas no inicializador SQLite são:

| Tabela | Finalidade |
|---|---|
| users | Contas de administradores, barbeiros e clientes; perfil, contato, CPF, endereço, senha, situação e versão da sessão. |
| barbers | Dados profissionais, horários, dias de trabalho e vínculo opcional com usuário. |
| services | Catálogo de serviços, preço, duração, categoria e situação. |
| appointments | Agendamentos, cliente, barbeiro, serviço, data, horários, situação e preço histórico. |
| products | Catálogo de produtos, preço, custo, estoque e situação. |
| stock_movements | Trilha de auditoria das entradas, saídas, ajustes e devoluções. |
| portfolio | Itens do portfólio e vínculos opcionais com serviço/barbeiro. |
| orders | Pedidos, dados do comprador, total, situação e forma de pagamento informada. |
| order_items | Itens do pedido com cópia de nome, quantidade e preço. |
| settings | Configurações gerais e de SMTP. |
| auth_login_attempts | Histórico de tentativas de autenticação para controle de força bruta. |
| password_reset_tokens | Hash de tokens de primeiro acesso e recuperação, expiração e consumo. |
| financial_transactions | Receitas, despesas, confirmações, estornos e vínculos operacionais. |
| barber_commission_settings | Percentual de comissão e data de atualização por barbeiro. |

As relações são protegidas por chaves estrangeiras onde definidas no esquema. Índices únicos e índices de consulta protegem, entre outros pontos, e-mail, CPF preenchido, token de recuperação, vínculo financeiro de pedido/agendamento e movimentos de estoque.

## 6. Rotas da aplicação

As rotas abaixo foram identificadas nos módulos de aplicação e segurança. Os métodos HTTP e caminhos podem mudar conforme a evolução do código.

### 6.1 Área pública e cliente

| Método | Caminho | Finalidade |
|---|---|---|
| GET | / | Página inicial. |
| GET | /servicos | Catálogo de serviços. |
| GET | /portfolio | Portfólio. |
| GET | /agendar | Tela de agendamento. |
| GET | /api/slots | Consulta de horários. |
| POST | /api/agendar | Solicitação de agendamento. |
| GET | /loja | Loja. |
| GET | /carrinho | Carrinho. |
| POST | /api/carrinho/add | Adicionar item. |
| POST | /api/carrinho/update | Atualizar quantidade. |
| POST | /api/carrinho/remove | Remover item. |
| POST | /finalizar-pedido | Finalizar pedido. |
| GET | /pedido-confirmado/{order_id} | Confirmação de pedido. |
| GET/POST | /cadastro | Cadastro de cliente. |
| GET/POST | /login | Autenticação. |
| GET | /logout | Encerrar sessão. |
| GET | /area-cliente | Área autenticada do cliente. |
| GET | /feed/agenda.ics | Feed de agenda iCalendar. |

### 6.2 Administração

| Método | Caminho | Finalidade |
|---|---|---|
| GET | /admin | Dashboard administrativo. |
| GET | /admin/agenda | Agenda administrativa. |
| POST | /admin/agenda/status | Alterar situação de agendamento. |
| GET/POST | /admin/servicos e /admin/servicos/salvar | Consultar e salvar serviços. |
| POST | /admin/servicos/excluir | Excluir serviço conforme validações. |
| GET/POST | /admin/barbeiros e /admin/barbeiros/salvar | Consultar e salvar barbeiros. |
| POST | /admin/barbeiros/excluir | Excluir/desativar barbeiro conforme regras. |
| GET/POST | /admin/produtos e /admin/produtos/salvar | Consultar e salvar produtos. |
| POST | /admin/estoque/entrada | Registrar entrada de estoque. |
| POST | /admin/produtos/excluir | Excluir produto conforme validações. |
| GET/POST | /admin/portfolio e /admin/portfolio/salvar | Consultar e salvar portfólio. |
| POST | /admin/portfolio/excluir | Excluir item do portfólio. |
| GET | /admin/pedidos | Consultar pedidos. |
| POST | /admin/pedidos/status | Alterar situação do pedido. |
| GET | /admin/financeiro | Painel financeiro. |
| GET | /admin/financeiro/exportar.csv | Exportar dados financeiros. |
| POST | /admin/financeiro/comissao | Configurar comissão. |
| POST | /admin/financeiro/lancamento | Criar lançamento. |
| POST | /admin/financeiro/confirmar | Confirmar lançamento. |
| POST | /admin/financeiro/estornar | Estornar lançamento. |
| GET/POST | /admin/configuracoes | Consultar e salvar configurações. |
| POST | /admin/configuracoes/smtp/salvar | Salvar SMTP. |
| POST | /admin/configuracoes/smtp/testar | Testar envio SMTP. |

### 6.3 Segurança e conta

| Método | Caminho | Finalidade |
|---|---|---|
| GET/POST | /admin/clientes/novo | Cadastro administrativo de cliente. |
| GET | /admin/clientes | Listagem e pesquisa de clientes. |
| POST | /admin/clientes/salvar | Atualizar dados cadastrais. |
| POST | /admin/clientes/status | Ativar/desativar cliente. |
| GET/POST | /primeiro-acesso | Solicitar link de primeiro acesso. |
| GET/POST | /criar-senha | Definir senha no primeiro acesso. |
| GET | /minha-conta | Dados e opções da conta. |
| POST | /minha-conta/senha | Alterar senha autenticada. |
| GET/POST | /esqueci-senha | Solicitar recuperação. |
| GET/POST | /redefinir-senha | Redefinir senha por token. |

## 7. Segurança

### 7.1 Senhas

O módulo auth.py usa PBKDF2-HMAC-SHA256 com salt aleatório e 600.000 iterações na geração de novos hashes. O hash persistido contém algoritmo, iterações, salt e resumo. A verificação limita o custo máximo aceito e utiliza comparação de tempo constante.

### 7.2 Sessões

A sessão é assinada com SECRET_KEY, armazenada em cookie HttpOnly e SameSite=Lax. A validade máxima configurada é de 30 dias. Em produção, o cookie é Secure. A sessão inclui versão, que é comparada com o registro do usuário; a troca de senha ou desativação invalida sessões anteriores.

### 7.3 Tokens de acesso e recuperação

Os tokens são gerados aleatoriamente. O banco armazena o hash do token, não seu valor original. Os fluxos verificam expiração e uso único. Os links dependem de URL pública HTTPS e SMTP válido.

### 7.4 Proteções HTTP

O middleware verifica Origin em operações de escrita quando o cabeçalho é fornecido e adiciona cabeçalhos defensivos, incluindo:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy
- Cache-Control: no-store
- HSTS em produção.

A documentação não substitui uma avaliação de segurança. Recomenda-se auditoria de autorização por rota, CSRF, limitação de requisições, upload, sessão, exposição de dados pessoais, dependências e configuração do proxy.

### 7.5 Uploads

Os arquivos de imagem aceitos pelo helper da aplicação são PNG, JPEG e WebP, com limite de 3 MiB para o fluxo de upload identificado. Os arquivos são gravados em uploads/ junto ao caminho do banco. O armazenamento precisa ser persistente e incluído na estratégia de backup.

### 7.6 Dados pessoais e LGPD

O sistema pode armazenar nome, e-mail, telefone, CPF, data de nascimento, endereço, histórico de agendamentos e pedidos. A operação comercial deve definir finalidade, base legal, transparência, retenção, controle de acesso, atendimento aos titulares, descarte seguro e resposta a incidentes. A implementação técnica não representa, isoladamente, conformidade integral com a LGPD.

## 8. Instalação e execução local

### 8.1 Pré-requisitos

- Python 3.12 recomendado para reproduzir o ambiente de CI.
- Git para obter o código.
- Terminal com acesso ao diretório do projeto.
- Navegador atualizado.

### 8.2 Preparar ambiente

Windows PowerShell:

    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt

Linux/macOS:

    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt

### 8.3 Variáveis de ambiente

| Variável | Uso |
|---|---|
| DATABASE_PATH | Caminho do arquivo SQLite; padrão barbearia.db. |
| SECRET_KEY | Segredo de assinatura de sessão e derivação de chave SMTP. |
| ENVIRONMENT | Define o ambiente; use production em produção. |
| COOKIE_SECURE | Controle adicional de cookie Secure; produção força segurança. |
| INITIAL_ADMIN_EMAIL | E-mail para provisionamento inicial, quando aplicável. |
| INITIAL_ADMIN_PASSWORD | Senha inicial; deve ser removida do ambiente após o provisionamento. |
| APP_BASE_URL | URL HTTPS pública usada em links de e-mail. |
| SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM | Parâmetros do servidor de e-mail. |
| SMTP_STARTTLS, SMTP_SECURITY | Modo de proteção da conexão SMTP. |

Gere um segredo forte:

    python -c "import secrets; print(secrets.token_urlsafe(48))"

Em produção, SECRET_KEY deve ter pelo menos 32 caracteres aleatórios e permanecer estável entre reinicializações. Não a publique nem a envie em chamados ou capturas de tela.

O carregamento automático de arquivos .env não deve ser presumido: confirme como o ambiente de execução injeta as variáveis.

### 8.4 Iniciar aplicação

    uvicorn app:app --host 127.0.0.1 --port 8000

Acesse http://127.0.0.1:8000. Para disponibilização em rede, ajuste o bind e configure firewall e proxy de acordo com o ambiente. Não exponha diretamente um servidor de desenvolvimento à internet.

## 9. Execução com Docker

O repositório contém Dockerfile e compose.yaml. O contêiner usa Python 3.12, executa com usuário não privilegiado e mantém o banco no volume barberflow_data.

1. Configure as variáveis em um arquivo de ambiente local protegido.
2. Construa e inicie:

    docker compose up --build -d

3. Consulte os logs:

    docker compose logs -f barberflow

4. Pare os serviços:

    docker compose down

**Atenção:** docker compose down -v remove os volumes e pode apagar o banco persistido. Só execute quando a perda desses dados for intencional e houver backup válido.

Nesta branch, o Compose configura DATABASE_PATH=/data/barbearia.db. Ele não transforma o backend SQLite em PostgreSQL.

## 10. E-mail e SMTP

O envio de primeiro acesso e recuperação depende de configuração SMTP válida e de uma URL pública HTTPS.

Procedimento operacional:
1. Acesse o painel administrativo.
2. Abra as configurações de e-mail.
3. Informe host, porta, remetente, usuário e modo de segurança.
4. Informe a URL pública HTTPS.
5. Salve e execute o teste de envio.
6. Confirme a entrega em caixa controlada.
7. Teste primeiro acesso e recuperação, incluindo expiração e reutilização de token.

Não registre senha SMTP, token de recuperação ou conteúdo sensível nos logs. Se SECRET_KEY for alterada e a senha SMTP armazenada não puder ser descriptografada, cadastre-a novamente.

## 11. Demonstração

O script seed_demo.py cria uma base SQLite isolada, com dados fictícios de clientes, barbeiros, agenda, pedidos, produtos e movimentações para demonstração.

Exemplos:

    python seed_demo.py
    python seed_demo.py --db ./barberflow-demo.demo.db

O script exige identificação .demo.db, compara o caminho com o banco configurado e bloqueia a utilização do banco operacional. A senha inicial do administrador é gerada aleatoriamente e exibida uma única vez no terminal, salvo quando DEMO_ADMIN_PASSWORD é fornecida com o tamanho mínimo exigido.

Para recriar uma base já existente, o parâmetro --reset remove o arquivo indicado e seus arquivos auxiliares SQLite. **Esse comando destrói a base de demonstração indicada.** Nunca use --reset em arquivo operacional ou em caminho compartilhado com produção.

Consulte também DEMONSTRACAO.md.

## 12. Backup e recuperação

### 12.1 O que precisa ser protegido

- Arquivo SQLite configurado por DATABASE_PATH.
- Diretório uploads/ associado ao ambiente.
- SECRET_KEY e credenciais de operação, guardadas em cofre/gerenciador de segredos.
- Configurações externas necessárias para reconstruir o serviço.

O banco e os uploads devem ser copiados de forma coordenada. Uma cópia do banco não inclui imagens armazenadas no sistema de arquivos.

### 12.2 Backup consistente

Use a API de backup do SQLite ou pare a aplicação antes de copiar o arquivo. Uma simples cópia de um banco em uso pode não representar uma cópia consistente em todos os cenários.

Exemplo:

    import sqlite3

    with sqlite3.connect("barbearia.db") as origem:
        with sqlite3.connect("backup-barberflow.db") as destino:
            origem.backup(destino)

Restrinja o acesso aos backups, criptografe o armazenamento e mantenha cópia separada. Defina periodicidade, retenção e responsáveis.

### 12.3 Verificação e restauração

Execute PRAGMA integrity_check em uma cópia isolada. Teste restauração em ambiente separado e confira login, clientes, agenda, pedidos, estoque, financeiro e imagens. Não faça o primeiro teste de restauração sobre a base de produção.

## 13. Testes e integração contínua

O workflow .github/workflows/validate.yml é acionado em push para main e branches feature/**, além de pull requests destinados a main.

As etapas declaradas são:
1. Checkout do código.
2. Configuração do Python 3.12.
3. Instalação de requirements.txt.
4. Compilação/verificação de sintaxe dos módulos principais.
5. Execução de python -m unittest discover -s tests -v.

Arquivos de teste identificados:
- tests/test_auth.py: utilitários de autenticação.
- tests/test_security_routes.py: fluxos e controles das rotas de segurança.
- tests/test_data_preservation.py: preservação de dados.
- tests/test_database_migration.py: testes de migração presentes no repositório; confirmar que correspondem ao backend desta branch antes de interpretá-los como teste de migração SQLite→PostgreSQL.
- tests/test_demo_seed.py: isolamento e preparação da base de demonstração.

A existência de um teste não comprova sua execução. Para declarar aprovação, consulte uma execução do GitHub Actions vinculada ao SHA exato do commit, confira conclusão do job e etapa de testes. Para falhas, preserve o log e identifique teste, mensagem e commit.

### 13.1 Execução local

    python -m compileall -q app.py auth.py database.py security_routes.py
    python -m unittest discover -s tests -v

Execute os testes em ambiente isolado. Não aponte testes, seeds ou rotinas de limpeza para bancos com dados reais.

## 14. Implantação em produção

Antes de liberar uma instalação:
- Configure HTTPS válido e proxy reverso corretamente.
- Defina ENVIRONMENT=production.
- Configure SECRET_KEY forte e persistente.
- Garanta armazenamento persistente para SQLite e uploads.
- Configure SMTP e valide os links de e-mail.
- Crie e revise a conta administrativa inicial.
- Remova credenciais temporárias do ambiente.
- Configure backups e teste restauração.
- Execute a suíte de testes vinculada ao commit candidato.
- Valide permissões por perfil e fluxos críticos manualmente.
- Monitore erros, espaço em disco, disponibilidade e integridade do banco.
- Documente versão implantada, responsáveis e plano de reversão.

Não use o banco de demonstração como banco operacional. Não compartilhe a mesma base entre clientes distintos.

## 15. Solução de problemas

| Sintoma | Verificações |
|---|---|
| Aplicação não inicia | Versão do Python, dependências, variáveis obrigatórias e logs de inicialização. |
| Erro de banco bloqueado | Concorrência de escrita, espaço em disco, permissões e timeout SQLite. |
| Dados somem após reinício | Persistência do caminho DATABASE_PATH ou volume Docker. |
| Sessão deixa de funcionar | SECRET_KEY alterada, cookie removido/expirado, conta desativada ou versão de sessão incrementada. |
| E-mail não chega | SMTP, porta, TLS, credenciais, remetente, URL HTTPS e logs do provedor. |
| Link de senha inválido | Expiração, uso anterior, token consumido ou conta inativa. |
| Imagens não aparecem | Diretório uploads/, permissões, volume persistente e cópia dos arquivos. |
| CI falha | SHA executado, versão Python, dependências, primeiro teste com erro e log completo. |
| Divergência SQLite/PostgreSQL | Confirmar branch e presença real dos módulos de backend PostgreSQL antes de configurar a conexão. |

## 16. Limitações e itens que exigem validação

1. PostgreSQL/Neon: não está implementado no código desta branch. A integração presente em outra branch precisa ser incorporada e validada antes de uso.
2. Multiempresa / Database per Tenant: é a arquitetura pretendida para comercialização, mas não está implementada neste snapshot. Não cadastrar diferentes empresas no mesmo banco esperando isolamento automático.
3. Pagamentos: não foi confirmada integração com gateway; a forma de pagamento registrada não comprova liquidação.
4. LGPD: controles técnicos não substituem políticas, contratos, processos e avaliação jurídica.
5. Segurança: a suíte automatizada deve ser complementada por revisão de autorização, CSRF, uploads, configuração de produção, dependências e testes de invasão autorizados.
6. Escalabilidade: SQLite e armazenamento local de arquivos exigem avaliação antes de múltiplas instâncias concorrentes.
7. Testes de migração: verificar a implementação e o ambiente de destino antes de declarar uma migração suportada.

## 17. Glossário

- Agendamento: compromisso entre cliente, barbeiro e serviço em data e horário.
- Barbeiro: profissional associado à agenda da barbearia.
- Cookie HttpOnly: cookie que não fica acessível diretamente ao JavaScript do navegador.
- Hash de senha: representação derivada da senha, armazenada em vez da senha original.
- PWA: aplicação web com recursos de instalação e experiência móvel suportados pelo navegador.
- SMTP: protocolo utilizado para envio de e-mails.
- Token de uso único: credencial temporária que deixa de ser válida após consumo.
- Seed de demonstração: rotina que prepara dados fictícios para apresentação e testes.
- Snapshot de preço: cópia do valor praticado no momento do agendamento ou pedido.
- Database per Tenant: arquitetura na qual cada empresa possui banco de dados independente; ainda pendente nesta branch.

## 18. Histórico e manutenção da documentação

Esta documentação deve ser revisada sempre que houver alteração em:
- perfis, permissões ou fluxos de autenticação;
- rotas e funcionalidades de clientes, agenda, loja ou administração;
- esquema, migrações ou mecanismo de persistência;
- infraestrutura, variáveis de ambiente ou implantação;
- segurança, backups, recuperação e testes.

Toda funcionalidade nova deve atualizar o manual e incluir testes correspondentes. A documentação deve indicar a branch e o commit de referência para que o conteúdo não seja confundido com o estado de outra versão.
