# Ambiente de demonstração do BarberFlow

## Objetivo e isolamento

A demonstração utiliza um arquivo SQLite próprio (`barberflow-demo.demo.db`). Ela não lê, copia, altera ou apaga o banco operacional. Todos os clientes, pedidos, atendimentos, valores e movimentações gerados são fictícios.

O script `seed_demo.py`:
- cria a estrutura do banco e o catálogo inicial;
- cria uma conta administrativa exclusiva da demonstração;
- gera clientes e um segundo barbeiro fictícios;
- gera vendas, pedidos pagos/pendentes/cancelados, despesas, atendimentos concluídos e agendamentos futuros;
- registra movimentações de estoque correspondentes a vendas, devoluções e reposições;
- distribui o histórico por seis meses fechados;
- registra pelo menos uma compra de estoque e a respectiva despesa de caixa em cada mês, além das saídas por vendas e devoluções;
- grava um marcador para impedir duplicação ao executar novamente.

## Criar a base

Na raiz do projeto, com as dependências instaladas:

```bash
python seed_demo.py
```

O terminal exibirá o caminho do banco, o e-mail e uma senha administrativa aleatória. **Guarde a senha nesse momento**: ela não é armazenada em arquivo de configuração nem exibida novamente.

Para escolher outro caminho:

```bash
python seed_demo.py --db ./dados/barberflow-demo.demo.db
```

A conta padrão é `admin@barberflow.teste`. Ela só existe no banco de demonstração. Os demais usuários fictícios são criados sem senha de acesso (primeiro acesso obrigatório). Para definir a senha administrativa sem gravá-la no repositório, use a variável `DEMO_ADMIN_PASSWORD` antes de executar o gerador. A senha precisa ter pelo menos 10 caracteres.

## Iniciar o sistema usando a base demo

O caminho do banco precisa ser definido antes de iniciar a aplicação.

### Windows PowerShell

```powershell
$env:DATABASE_PATH = "$PWD\barberflow-demo.demo.db"
$env:ENVIRONMENT = "development"
python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

### Linux / macOS

```bash
DATABASE_PATH="$PWD/barberflow-demo.demo.db" ENVIRONMENT=development \
  python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

Acesse `http://127.0.0.1:8001/login` e entre com as credenciais exibidas durante a criação. Altere a senha após o primeiro acesso.

**Importante:** não publique esse ambiente na internet sem uma implantação isolada, HTTPS e revisão das configurações. A senha administrativa é uma credencial real, mesmo sendo uma base fictícia.

## Reexecutar ou recriar

Executar o script novamente sobre uma base já marcada é seguro: ele não duplica registros.

Para apagar e recriar somente a base de demonstração:

```bash
python seed_demo.py --reset
```

`--reset` é destrutivo para o arquivo demo indicado. O script exige a extensão `.demo.db` e recusa explicitamente o caminho configurado como banco operacional. Não use caminhos de produção.

## Verificações

O teste automatizado `tests/test_demo_seed.py` verifica:
- separação entre banco operacional e banco demo;
- provisionamento e validação do hash da senha administrativa;
- existência de pedidos pagos, pendentes e cancelados;
- consistência entre saldo de produtos e soma das movimentações de estoque;
- histórico distribuído em seis meses;
- idempotência da segunda execução.
