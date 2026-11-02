# Plano de migração PostgreSQL (Neon)

## Objetivo

Manter SQLite como backend padrão para desenvolvimento local e testes existentes, adicionando PostgreSQL via `DATABASE_URL` para a implantação demonstrativa no Render/Neon. A migração não deve copiar dados operacionais nem executar alterações destrutivas no banco existente.

## Auditoria inicial do branch main

A inspeção do código identificou dependências SQLite que impedem uma simples troca de driver:

- `database.py`: criação de schema com `AUTOINCREMENT`, introspecção por `PRAGMA table_info`, `sqlite3.Row`, configuração de chaves estrangeiras e timeout; migrações incrementais e seed inicial.
- `app.py`: transações `BEGIN IMMEDIATE`, uso de `cursor.lastrowid`, `date('now', 'localtime')`, índices parciais em cláusulas `ON CONFLICT` e tratamento de `sqlite3.IntegrityError`.
- `seed_demo.py`: `lastrowid`, `last_insert_rowid()`, `INSERT OR REPLACE`, `INSERT OR IGNORE`, `BEGIN IMMEDIATE` e dependência direta do schema SQLite.
- `security_routes.py`: tratamento direto de `sqlite3.IntegrityError`.
- `smtp_settings.py`: UPSERT com `ON CONFLICT`, que pode ser mantido com sintaxe PostgreSQL após validar os índices/constraints.
- Testes atuais verificam especificamente comportamento SQLite (PRAGMA e migrações SQLite); devem continuar válidos e receber uma suíte separada para PostgreSQL.

## Estratégia técnica

1. Introduzir uma camada de conexão/compatibilidade com seleção explícita por ambiente: `DATABASE_URL` para PostgreSQL e `DATABASE_PATH` para SQLite.
2. Usar psycopg 3 com parâmetros nomeados/posicionais devidamente adaptados e resultados compatíveis com acesso por nome de coluna.
3. Criar schema PostgreSQL próprio, com tipos, chaves estrangeiras, índices e constraints equivalentes; não tentar executar o DDL SQLite no PostgreSQL.
4. Substituir dependências de `lastrowid` por `INSERT ... RETURNING id` nos pontos de escrita que necessitam do identificador.
5. Remover construções SQLite específicas das operações compartilhadas, incluindo `BEGIN IMMEDIATE`, `last_insert_rowid()`, `INSERT OR REPLACE/IGNORE` e funções de data SQLite.
6. Normalizar exceções de integridade para que a aplicação não dependa de `sqlite3.IntegrityError` quando o backend for PostgreSQL.
7. Adaptar o seed demonstrativo para criar dados fictícios diretamente no banco selecionado, com proteção contra execução acidental em banco operacional e idempotência.
8. Executar testes unitários SQLite existentes e testes de integração PostgreSQL antes de configurar Render.

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
- [ ] Camada de conexão e schema PostgreSQL implementados.
- [ ] Seed PostgreSQL implementado.
- [ ] Testes de integração PostgreSQL aprovados.
- [ ] Revisão e PR para `main`.
- [ ] Configuração de variáveis no Render e validação do deploy.
