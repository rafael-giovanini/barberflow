# Implantação e recuperação — BarberFlow

Este documento é um roteiro operacional. Ele não substitui uma implantação de teste nem confirma que um provedor específico atende aos requisitos do sistema.

## 1. Pré-requisitos

- Python compatível com as dependências fixadas em `requirements.txt`.
- Ambiente virtual e dependências instaladas com `pip install -r requirements.txt`.
- Diretório da aplicação com permissão de escrita para o processo, pois o SQLite cria/atualiza o arquivo do banco.
- Armazenamento persistente para o banco de dados. O arquivo padrão é `barbearia.db`, no mesmo diretório de `database.py`; armazenamento efêmero pode apagar os dados quando a instância reinicia ou é substituída.
- HTTPS válido na URL pública. Não exponha a aplicação diretamente à internet sem proxy/servidor web e controles de acesso adequados.

## 2. Variáveis de ambiente

Use `.env.example` como referência, mas configure as variáveis no gerenciador de ambiente do servidor. Não versione arquivos `.env`, senhas ou chaves reais.

- `ENVIRONMENT=production`: ativa as verificações de produção. Configure somente no ambiente de produção.
- `SECRET_KEY`: segredo aleatório persistente, com pelo menos 32 caracteres. Gere um valor com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Guarde-o em um gerenciador de segredos e mantenha uma cópia de recuperação protegida.
- `COOKIE_SECURE=1`: mantenha habilitado com HTTPS. Em produção, a aplicação força cookies seguros.
- `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD`: configure credenciais fortes do primeiro administrador antes da primeira inicialização de um banco novo. Não presuma que essa configuração alterará automaticamente uma conta existente; revise as contas existentes e troque credenciais antigas separadamente.
- `APP_BASE_URL`: URL pública completa começando por `https://`, sem apontar para localhost. Também pode ser configurada na seção de e-mail do painel administrativo.
- SMTP pode ser configurado em `/admin/configuracoes` e testado com envio para um endereço escolhido. Como alternativa, use `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, opcionalmente `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS` e `SMTP_SECURITY` (`starttls`, `ssl` ou `none`) no ambiente. Os campos configurados no painel ficam no SQLite; a senha é criptografada com uma chave derivada da `SECRET_KEY`. Mantenha essa chave persistente e protegida: ao trocá-la, será necessário cadastrar novamente a senha SMTP.

A alteração de `SECRET_KEY` invalida os cookies de sessão assinados existentes. Planeje essa troca e não gere uma chave nova a cada reinicialização.

## 3. Inicialização e verificação

1. Faça backup antes da primeira implantação ou atualização.
2. Instale as dependências em um ambiente virtual isolado.
3. Configure as variáveis acima no ambiente do serviço.
4. Inicie com um servidor ASGI adequado, por exemplo `uvicorn app:app --host 127.0.0.1 --port 8000`, atrás de um proxy HTTPS configurado corretamente. Ajuste o bind e o processo conforme a arquitetura real do host.
5. Verifique a página inicial, login/logout, permissões administrativas, cadastro e agendamento.
6. Confirme nos cabeçalhos HTTP que os cookies de sessão são `HttpOnly`, `Secure` em HTTPS e `SameSite=Lax`; confirme também que a URL pública redireciona/serve exclusivamente por HTTPS.
7. Salve os dados SMTP no painel, envie o e-mail de teste para uma conta controlada e confirme o recebimento. Depois valide recuperação, expiração e uso único do link. Não inclua tokens ou senhas em logs.

## 4. Backup do SQLite

O banco padrão fica em `barbearia.db`, junto a `database.py`. Se o ambiente usar outro caminho, confirme-o no código e no volume antes de automatizar o backup.

### Método preferencial: backup consistente pelo SQLite

Execute no servidor, com o mesmo Python/ambiente da aplicação. O exemplo abaixo usa a API de backup do SQLite e cria uma cópia consistente mesmo quando há conexões abertas:

```bash
python - <<'PY'
import sqlite3
from pathlib import Path

source = Path("barbearia.db")
destination = Path("backups") / "barberflow-backup.db"
destination.parent.mkdir(parents=True, exist_ok=True)

if not source.is_file():
    raise SystemExit(f"Banco não encontrado: {source.resolve()}")

with sqlite3.connect(str(source)) as src:
    with sqlite3.connect(str(destination)) as dst:
        src.backup(dst)

print(f"Backup criado: {destination.resolve()}")
PY
```

Execute a partir do diretório correto ou ajuste os caminhos para absolutos. Restrinja o acesso ao diretório de backup: ele contém dados pessoais e operacionais. Copie uma segunda versão para armazenamento separado, criptografado e com acesso controlado. Defina periodicidade e retenção conforme o volume de alterações e as exigências da operação.

Não considere o backup válido apenas porque o arquivo foi criado. Faça verificações periódicas de integridade e teste a restauração em uma cópia isolada.

## 5. Teste de integridade e restauração

Para verificar a integridade de uma cópia sem afetar a produção:

```bash
python - <<'PY'
import sqlite3
from pathlib import Path

backup = Path("backups/barberflow-backup.db")
if not backup.is_file():
    raise SystemExit(f"Backup não encontrado: {backup.resolve()}")

with sqlite3.connect(f"file:{backup.resolve()}?mode=ro", uri=True) as db:
    result = db.execute("PRAGMA integrity_check").fetchone()[0]
    print(result)
    if result != "ok":
        raise SystemExit("Falha na verificação de integridade")
PY
```

Para um exercício de restauração, pare a aplicação, preserve uma cópia do banco atual e restaure o backup em um ambiente de teste. Inicie a aplicação apontando para a cópia restaurada e confira login, clientes, agendamentos, pedidos, financeiro e estoque. Não teste restauração diretamente sobre o único banco de produção. Documente a duração do procedimento e qualquer dado perdido desde o último backup.

## 6. Atualizações e reversão

- Registre o commit implantado e faça backup antes de cada atualização.
- Teste a atualização e os testes automatizados em ambiente isolado antes de produção.
- Não reverta apenas o código se a versão nova tiver aplicado migrações incompatíveis: confirme previamente a compatibilidade do esquema e a estratégia de retorno.
- Preserve o banco original e o backup até que a validação pós-atualização termine.

## 7. Checklist de liberação

- [ ] Segredos configurados fora do Git e protegidos.
- [ ] `ENVIRONMENT=production` e `SECRET_KEY` persistente e forte.
- [ ] HTTPS funcional; cookies seguros confirmados.
- [ ] Banco em armazenamento persistente com permissões mínimas.
- [ ] Backup automático configurado, cópia separada protegida e restauração testada.
- [ ] SMTP salvo no painel ou no ambiente, teste de entrega concluído e recuperação de senha validada.
- [ ] Conta administrativa revisada; nenhuma senha de demonstração ativa.
- [ ] Testes automatizados aprovados e fluxos críticos validados manualmente.
- [ ] Logs e monitoramento sem senhas, tokens ou dados pessoais desnecessários.
- [ ] Responsável, periodicidade de backup, retenção e procedimento de incidente documentados.

**Limite atual:** este roteiro não comprova que um deploy real, o SMTP ou a restauração foram executados. Esses itens precisam ser validados no ambiente de destino antes de declarar o BarberFlow pronto para produção.
