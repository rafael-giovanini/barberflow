# 🎩 Sistema Completo de Barbearia

Sistema completo para barbearias com: site do cliente, agendamento online, portfólio de cortes, loja online e painel do barbeiro (funciona como app no celular).

## ✨ O que está incluso

### 🌐 Site do Cliente
- **Página inicial** com serviços em destaque, portfólio e produtos
- **Serviços & Preços** — lista completa com valores e duração
- **Portfólio de Cortes** — cada corte com foto + explicação detalhada + filtro por categoria
- **Agendamento Online** — cliente escolhe serviço, barbeiro, dia e vê horários disponíveis em tempo real
- **Cadastro/Login** de clientes
- **Área do Cliente** — acompanha agendamentos e pedidos
- **Loja Online** — produtos (balm, pós-barba, shampoo, pomada, etc.) com carrinho e checkout

### 📱 Painel do Barbeiro (funciona como app no celular)
- **Dashboard** — agendamentos do dia, faturamento, pedidos pendentes
- **Agenda completa** — visualizar por data, marcar como concluído/cancelar
- **Gerenciar Serviços** — adicionar/editar/desativar serviços e preços
- **Gerenciar Produtos** — controle de estoque, preços, categorias
- **Gerenciar Portfólio** — adicionar fotos dos cortes com explicação
- **Pedidos da Loja** — acompanhar vendas online

## 🚀 Como rodar

### 1. Instalar dependências
```bash
pip install -r requirements.txt
```

### 2. Rodar o sistema
```bash
python app.py
```
Ou:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Rodar com Docker Compose

É necessário ter Docker Engine e o plugin Docker Compose instalados. Na primeira execução, crie um arquivo `.env` na raiz do projeto com as credenciais do administrador inicial e uma chave de sessão persistente:

```dotenv
INITIAL_ADMIN_EMAIL=admin@exemplo.com
INITIAL_ADMIN_PASSWORD=defina-uma-senha-forte-com-10-ou-mais-caracteres
SECRET_KEY=cole-aqui-um-segredo-aleatorio
```

Gere o segredo com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. O arquivo `.env` não é incluído na imagem nem versionado.

Inicie o sistema:

```bash
docker compose up --build -d
```

Acesse http://localhost:8000. O banco SQLite fica no volume persistente `barberflow_data`, então os dados permanecem após recriar o contêiner. Para acompanhar os logs use `docker compose logs -f`; para parar use `docker compose down`. O comando `docker compose down -v` também apaga o volume e todos os dados do banco.

Para uso público, configure `ENVIRONMENT=production`, uma `SECRET_KEY` persistente e `COOKIE_SECURE=1` no `.env`, e publique atrás de um proxy HTTPS. O SMTP e a URL pública HTTPS podem ser configurados em `/admin/configuracoes`; também podem ser definidos no ambiente do Docker. O logo, as imagens de produtos e as fotos do portfólio podem ser informados por URL ou enviados como arquivo PNG, JPG ou WebP (até 3 MB por imagem); os arquivos enviados ficam no volume persistente junto ao banco. Não exponha diretamente o contêiner à internet sem HTTPS.

### 3. Acessar
- Site: http://localhost:8000
- **Painel do barbeiro:** http://localhost:8000/admin
  - Em instalações novas, configure `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD` no ambiente para criar a primeira conta administrativa; não existe mais senha padrão no código. Em bancos existentes, revise e troque manualmente qualquer credencial antiga de demonstração antes da produção.

## 🎨 Como personalizar

### Trocar nome da barbearia
Edite `templates/base.html` — procure por `BARBERSHOP` e troque pelo nome da sua marca.

### Trocar cores
Edite `static/style.css` — no topo do arquivo tem as variáveis de cor (`--dourado`, `--preto`, etc.).

### Adicionar/editar serviços, produtos e fotos
Use o próprio painel do barbeiro (`/admin`) — tudo é gerenciável por lá, sem precisar mexer no código.

### Horário de funcionamento
Edite no banco ou adicione uma tela no admin. Por padrão: Seg-Sáb 9h-18h, almoço 12h-13h.

## 💰 Como vender no Kiwify

1. **Zip esta pasta toda** e entregue como "arquivo digital" no Kiwify
2. **Inclua um vídeo** mostrando como instalar (5 minutos no YouTube já ensinam deploy na Vercel/Railway)
3. **Preço sugerido:** R$ 97–197 (sistema completo) ou R$ 47/mês com atualizações
4. **Diferencial:** ofereça "instalação grátis" como bônus — você instala para o cliente e cobra mensalidade de manutenção

### Onde hospedar (opções baratas):
- **Railway.app** — ~$5/mês, deploy com 1 clique
- **Render.com** — plano grátis (dorme após inatividade)
- **VPS na Hostinger/Locaweb** — ~R$20/mês
- **Oracle Cloud** — gratuito para sempre (VM grátis)

## 📁 Estrutura do projeto

```
barbearia/
├── app.py              # Aplicação principal (todas as rotas e API)
├── database.py         # Banco de dados + dados iniciais
├── auth.py             # Criptografia de senha
├── requirements.txt    # Dependências
├── barbearia.db        # Banco SQLite (criado automaticamente)
├── static/
│   └── style.css       # Estilo visual
└── templates/
    ├── base.html       # Template base (menu, rodapé)
    ├── index.html      # Página inicial
    ├── servicos.html   # Lista de serviços
    ├── portfolio.html  # Portfólio de cortes
    ├── agendar.html    # Agendamento
    ├── loja.html       # Loja online
    ├── carrinho.html   # Carrinho
    ├── login.html / cadastro.html
    ├── area_cliente.html
    ├── pedido_confirmado.html
    └── admin/          # Painel do barbeiro
        ├── dashboard.html
        ├── agenda.html
        ├── servicos.html
        ├── produtos.html
        ├── portfolio.html
        └── pedidos.html
```

## Cadastro e primeiro acesso do cliente

- O cadastro administrativo registra nome, CPF, nascimento, e-mail, telefone e endereço; o cliente cria a própria senha.
- No primeiro acesso, o cliente informa o CPF. Para um cadastro encontrado, o sistema envia um link único e temporário para o e-mail já cadastrado. O link expira em 30 minutos.
- Se o CPF não tiver cadastro, o cliente vai ao formulário público para cadastrar os dados. Depois, usa Primeiro acesso para receber o link de criação de senha.
- A conta fica bloqueada para login até a senha ser criada. O CPF é validado e único entre os cadastros.
- Para enviar os links, configure o SMTP e uma URL pública HTTPS na seção **Envio de e-mails** em `/admin/configuracoes`. A tela oferece envio de teste para um endereço informado. O CPF sozinho não libera a criação da senha.

## 🔐 Segurança
- Senhas armazenadas com hash PBKDF2.
- Sessões assinadas e cookies HTTP-only; configure `COOKIE_SECURE=1` quando estiver usando HTTPS.
- Defina `SECRET_KEY` como variável de ambiente persistente antes da implantação. Sem ela, o ambiente de desenvolvimento gera uma chave aleatória a cada inicialização e invalida sessões após reiniciar. Nunca use o fallback de desenvolvimento em produção.
- Em uma instalação nova, configure `INITIAL_ADMIN_EMAIL` e `INITIAL_ADMIN_PASSWORD` antes da primeira inicialização. A aplicação não cria mais uma conta com senha padrão conhecida.
- O plano incremental e os passos de implantação estão em `docs/PLANO-MELHORIAS-CLIENTES-SENHAS.md`.
- O roteiro operacional de implantação, backup SQLite, teste de restauração e checklist de liberação está em `docs/IMPLANTACAO-E-RECUPERACAO.md`.
- A recuperação de senha exige uma URL pública HTTPS e configuração SMTP. Configure pela área administrativa ou use `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, opcionalmente `SMTP_USER`, `SMTP_PASSWORD` e `SMTP_SECURITY` (`starttls`, `ssl` ou `none`) no ambiente.
- A senha SMTP cadastrada no painel é criptografada usando uma chave derivada da `SECRET_KEY`. Mantenha essa chave estável e protegida junto dos backups; se ela for trocada, informe novamente a senha SMTP no painel. O sistema não exibe a senha depois de salva.
- Valide o envio pelo botão de teste antes de usar a recuperação de senha em produção.

## 📞 Suporte
Este sistema foi construído do zero e é totalmente seu. Modifique, venda, use como quiser!
