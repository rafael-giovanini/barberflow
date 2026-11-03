# Plano de migração PostgreSQL (Neon)

## Objetivo

Manter SQLite como backend padrão para desenvolvimento local e testes existentes, adicionando PostgreSQL via `DATABASE_URL` para implantação no Render/Neon. Quando solicitado, permitir uma cópia única dos dados SQLite para uma base PostgreSQL exclusiva e vazia. A origem SQLite nunca é alterada ou apagada.

## Auditoria inicial do branch main

A inspeção do código identificou dependências SQLite que impedem uma simples troca de driver:

- `database.py`: criação de schema com `AUTOINCREMENT`, introspecção por `PRAGMA table_info`, `sqlite3.Row`, configuração de chaves estrangeiras e timeout; migrações incrementais e seed inicial.
- `app.py`: transações `BEGIN IMMEDIATE`, uso de `cursor.lastrowid`, `date('now', 'localtime')`, índices parciais em cláusulas `ON CONFLICT` e tratamento de `sqlite3.IntegrityError`.
- `seed_demo.py`: `lastrowid`, `last_insert_rowid()`, `INSERT OR REPLACE`, `INSERT OR IGNORE`, `BEGIN IMMEDIATE` e dependência direta do schema SQLite.
- `security_routes.py`: tratamento direto de `sqlite3.IntegrityError`.
- `smtp_settings.py`: UPSERT com `ON CONFLICT`, que pode ser mantido com sintaxe PostgreSQL após validar os índices/constraints.
- Testes atuais verificam especificamente comportamento SQLite (PRAGMA e migrações SQLite); devem continuar válidos e receber uma suíte separada para PostgreSQL.

## Inventário ampliado de incompatibilidades (segunda auditoria)

A varredura por trechos de `app.py`, `database.py` e `seed_demo.py` confirmou que a migração atinge fluxos críticos, não apenas a inicialização:

- Agendamento: `BEGIN IMMEDIATE` protege a verificação de conflito e a criação do horário. No PostgreSQL, essa proteção precisa ser redesenhada com transação e bloqueio/constraint apropriados para evitar dupla reserva concorrente.
- Loja: criação de pedido, baixa de estoque e movimentações dependem de `lastrowid` e transações explícitas.
- Estoque: cadastro/ajuste de produto registra movimentos e precisa preservar atomicidade.
- Financeiro: estornos e recebimentos usam `date('now', 'localtime')`, índices únicos parciais e tratamento de conflito.
- Cadastro/autenticação: há captura direta de `sqlite3.IntegrityError` em fluxos de cadastro e edição.
- Barbeiros: criação encadeada de usuário e barbeiro recupera IDs com `lastrowid`.
- Seed: usa `last_insert_rowid()`, `INSERT OR REPLACE` e `INSERT OR IGNORE`; não é portável como está.

Outras consultas comuns usam `?` como placeholder e `COLLATE NOCASE`. A solução deve tratar placeholders de forma consistente e substituir ordenação case-insensitive por expressão/colação compatível, sem alterar a semântica de busca.

## Estratégia técnica

1. Introduzir uma camada de conexão/compatibilidade com seleção explícita por ambiente: `DATABASE_URL` para PostgreSQL e `DATABASE_PATH` para SQLite.
2. Usar psycopg 3 com parâmetros nomeados/posicionais devidamente adaptados e resultados compatíveis com acesso por nome de coluna.
3. Criar schema PostgreSQL próprio, com tipos, chaves estrangeiras, índices e constraints equivalentes; não tentar executar o DDL SQLite no PostgreSQL.
4. Substituir dependências de `lastrowid` por `INSERT ... RETURNING id` nos pontos de escrita que necessitam do identificador.
5. Remover construções SQLite específicas das operações compartilhadas, incluindo `BEGIN IMMEDIATE`, `last_insert_rowid()`, `INSERT OR REPLACE/IGNORE` e funções de data SQLite.
6. Normalizar exceções de integridade para que a aplicação não dependa de `sqlite3.IntegrityError` quando o backend for PostgreSQL.
7. Adaptar o seed demonstrativo para criar dados fictícios diretamente no banco selecionado, com proteção contra execução acidental em banco operacional e idempotência.
8. Disponibilizar um importador SQLite → PostgreSQL em modo de auditoria por padrão, com transação atômica, validação de integridade/relacionamentos, preservação de IDs e sequências e recusa a destinos com dados.
9. Executar testes unitários SQLite existentes e testes de integração PostgreSQL antes de configurar Render.

## Segurança e implantação

- Nunca versionar `.env`, connection strings, senhas ou arquivos de banco.
- Armazenar `DATABASE_URL` e credenciais iniciais exclusivamente em variáveis de ambiente do Render.
- Usar uma base/projeto Neon exclusivo para demonstração; não reutilizar banco operacional.
- Não configurar o Render nem fazer merge no `main` até que os testes de ambos os backends passem e a revisão seja concluída.

## Riscos identificados

- O arquivo `.env` aparece versionado no histórico do repositório. A cópia será removida do branch de migração, mas a remoção não apaga versões anteriores do histórico. Todos os segredos que já estiveram nesse arquivo devem ser considerados potencialmente expostos e rotacionados.
- A compatibilidade PostgreSQL envolve vários módulos e consultas. Um adaptador superficial de placeholders não é suficiente e pode causar falhas em transações, inserções, migrações e constraints.
- Render Free não oferece disco persistente; SQLite no filesystem do serviço não deve ser usado como banco persistente de demonstração.

## Estado

- [x] Branch de trabalho criada a partir de `main`.
- [x] Auditoria inicial dos pontos SQLite concluída.
- [x] Segunda varredura dos fluxos críticos (agenda, pedidos, estoque, financeiro, autenticação e seed) concluída.
- [x] Primeira etapa da camada de conexão Psycopg 3, schema PostgreSQL e tradução compatível de SQL implementada.
- [x] Seed demonstrativo habilitado para PostgreSQL com proteção contra bancos não vazios, idempotência e sem opção de reset para PostgreSQL.
- [x] Testes smoke de integração aprovados em PostgreSQL 16 local temporário (schema, seed, parâmetros, linhas híbridas, transação e erro de integridade).
- [x] Importador SQLite → PostgreSQL implementado com auditoria somente leitura, destino vazio, transação atômica, preservação de relacionamentos/IDs e validação por testes em fixture isolada.
- [x] Concorrência de agendamento por barbeiro e checkout disputando a última unidade validada em PostgreSQL.
- [ ] Compatibilidade de todas as rotas e cenários de concorrência verificada em PostgreSQL.
- [ ] Suíte SQLite completa repetida após as alterações.
- [ ] Execução real do workflow CI confirmada no GitHub.
- [ ] Revisão e PR para `main`.
- [ ] Configuração de variáveis no Render e validação do deploy.


## Implementação incremental em andamento

A primeira etapa adiciona `psycopg[binary]` 3.3.6, seleção de backend por `DATABASE_URL`, schema PostgreSQL próprio e um adaptador lexical que converte placeholders `?` sem alterar interrogações dentro de strings/comentários. As linhas PostgreSQL permitem acesso por nome e índice, e violações de integridade são normalizadas para preservar os `except sqlite3.IntegrityError` existentes.

Os inserts que precisam de ID usam `RETURNING id`. O agendamento bloqueia a linha do barbeiro no PostgreSQL antes de verificar conflitos; compras/ajustes de estoque bloqueiam a linha do produto e vendas mantêm baixa condicional de estoque. O seed de demonstração aceita `--database-url` somente para banco com nome contendo `demo`, exige banco vazio ou previamente marcado e rejeita `--reset` em PostgreSQL.

A validação feita até aqui ocorreu em um contêiner PostgreSQL 16 local. Os testes do importador usam um SQLite temporário com dados ligados por chaves estrangeiras; verificam contagens, valores, sequências e a recusa de um segundo import sobre destino preenchido. Nenhuma conexão foi feita ao Neon ou Render. Para efetivar a cópia do ambiente real, ainda são necessários o caminho de um SQLite válido e uma `DATABASE_URL` de destino exclusiva e vazia.
