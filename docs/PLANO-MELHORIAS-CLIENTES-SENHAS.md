# Plano de melhorias — BarberFlow

## Objetivo

Adicionar gestão administrativa de clientes, alteração de senha e recuperação de senha sem reescrever o sistema nem remover dados existentes.

## Preparação segura

- [x] Criar a branch isolada `feature/clientes-senhas` a partir de `main`.
- [x] Confirmar que o projeto usa FastAPI, Jinja2, SQLite e hashes PBKDF2.
- [x] Mapear as tabelas existentes: `users`, `barbers`, `appointments` e `orders`.
- [ ] Criar cópia de segurança do banco SQLite no ambiente onde o sistema estiver instalado, antes de executar alterações.
- [ ] Configurar e validar as variáveis de ambiente antes de alterar a chave de sessão ou publicar recuperação de senha.

## Etapa 1 — Gestão de clientes

- Criar uma página administrativa de clientes, acessível somente ao papel `admin`.
- Listar apenas usuários com papel `customer`.
- Permitir pesquisa por nome, e-mail e telefone.
- Permitir edição dos dados cadastrais sem modificar agendamentos ou pedidos.
- Permitir desativação lógica, sem excluir registros relacionados.
- Manter o cadastro público `/cadastro` e o formato atual de contas.

## Etapa 2 — Alteração de senha

- Criar a página “Minha conta / Alterar senha”.
- Exigir a senha atual e confirmação da nova senha.
- Validar a senha no servidor e manter o mecanismo PBKDF2 existente.
- Atualizar a senha apenas da conta autenticada.
- Invalidar a sessão atual e exigir novo login após a alteração.

## Etapa 3 — Recuperação de senha

- Implementar solicitação de recuperação com resposta genérica, sem revelar se um e-mail existe.
- Enviar link por e-mail usando URL base configurada explicitamente, nunca derivada do cabeçalho Host.
- Usar token aleatório de uso único, com expiração curta; armazenar apenas seu hash.
- Configurar SMTP por variáveis de ambiente, limitar solicitações e não registrar tokens em logs.
- Após redefinir, invalidar o token utilizado e exigir login normal.

## Etapa 4 — Testes e revisão

- Testar cadastro público, login de cliente, login administrativo e permissões.
- Testar pesquisa, edição e desativação de clientes.
- Testar senha atual incorreta, nova senha inválida, token expirado e token reutilizado.
- Confirmar que os registros de agendamentos e pedidos permanecem intactos.
- Revisar a configuração de sessão e credenciais administrativas de demonstração antes da produção.

## Restrições de segurança

- Não alterar a branch `main` durante o desenvolvimento.
- Não apagar usuários, barbeiros, agendamentos, pedidos ou dados existentes.
- Não habilitar recuperação de senha em produção sem SMTP configurado e testado.
- Não fazer merge nem publicar em produção sem revisão e testes.

## Observações da auditoria inicial

- O cadastro público existente cria usuários com papel `customer`.
- A tabela `users` já se relaciona com agendamentos e pedidos.
- A conta administrativa de demonstração `admin@barbearia.com` / `admin123` aparece no README, na tela de login e nos dados iniciais; essa credencial deve ser removida ou substituída por configuração segura antes da produção.
- A chave de assinatura da sessão está fixa em `app.py`; a migração para variável de ambiente deve ser coordenada com a implantação, pois mudar a chave invalida cookies de sessão existentes.
