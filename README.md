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

### 3. Acessar
- Site: http://localhost:8000
- **Painel do barbeiro:** http://localhost:8000/admin
  - A base de demonstração pode criar uma conta administrativa inicial. **Não publique nem utilize credenciais de demonstração em produção.** Configure uma senha exclusiva e forte antes de disponibilizar o sistema.

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

## 🔐 Segurança
- Senhas armazenadas com hash PBKDF2.
- Sessões assinadas e cookies HTTP-only; configure `COOKIE_SECURE=1` quando estiver usando HTTPS.
- Defina `SECRET_KEY` como variável de ambiente persistente antes da implantação. Sem ela, o ambiente de desenvolvimento gera uma chave aleatória a cada inicialização e invalida sessões após reiniciar. Nunca use o fallback de desenvolvimento em produção.
- O plano incremental e os passos de implantação estão em `docs/PLANO-MELHORIAS-CLIENTES-SENHAS.md`.
- A recuperação de senha exige HTTPS em `APP_BASE_URL` e configuração SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, opcionalmente `SMTP_USER`, `SMTP_PASSWORD` e `SMTP_STARTTLS`). Sem isso, nenhum link de recuperação é enviado.
- Configure `APP_BASE_URL` com a URL pública HTTPS correta; não use o sistema em produção sem validar envio de e-mail e política de cookies.

## 📞 Suporte
Este sistema foi construído do zero e é totalmente seu. Modifique, venda, use como quiser!
