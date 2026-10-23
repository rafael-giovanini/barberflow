"""
Banco de dados SQLite do Sistema de Barbearia
Um único arquivo, sem necessidade de instalar servidor de banco.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "barbearia.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Usuários (clientes e barbeiros/admin)
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'customer',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Barbeiros (dados profissionais)
    c.execute("""
    CREATE TABLE IF NOT EXISTS barbers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        name TEXT NOT NULL,
        bio TEXT,
        photo_url TEXT,
        active INTEGER DEFAULT 1,
        work_start TEXT DEFAULT '09:00',
        work_end TEXT DEFAULT '18:00',
        lunch_start TEXT DEFAULT '12:00',
        lunch_end TEXT DEFAULT '13:00',
        work_days TEXT DEFAULT '[1,2,3,4,5,6]',
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # Serviços (corte, barba, etc.)
    c.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        duration_min INTEGER DEFAULT 30,
        category TEXT DEFAULT 'Cabelo',
        active INTEGER DEFAULT 1,
        image_url TEXT
    )
    """)

    # Agendamentos
    c.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        barber_id INTEGER NOT NULL,
        service_id INTEGER NOT NULL,
        appointment_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT DEFAULT 'scheduled',
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (barber_id) REFERENCES barbers(id),
        FOREIGN KEY (service_id) REFERENCES services(id)
    )
    """)

    # Produtos da loja online
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        stock INTEGER DEFAULT 0,
        image_url TEXT,
        category TEXT DEFAULT 'Geral',
        active INTEGER DEFAULT 1
    )
    """)

    # Portfólio (modelos de corte com explicação)
    c.execute("""
    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        image_url TEXT,
        category TEXT DEFAULT 'Corte',
        service_id INTEGER,
        barber_id INTEGER,
        FOREIGN KEY (service_id) REFERENCES services(id),
        FOREIGN KEY (barber_id) REFERENCES barbers(id)
    )
    """)

    # Pedidos da loja
    c.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        customer_name TEXT NOT NULL,
        customer_phone TEXT,
        address TEXT,
        total REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        payment_method TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # Itens do pedido
    c.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)

    # Configurações da barbearia (nome, logo, cores)
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Migração compatível: acrescenta campos sem remover ou recriar registros.
    user_columns = {row["name"] for row in c.execute("PRAGMA table_info(users)").fetchall()}
    if "active" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    if "session_version" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")

    # Tentativas de autenticação para limitação de força bruta, persistentes entre reinicializações.
    c.execute("""
    CREATE TABLE IF NOT EXISTS auth_login_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        client_ip TEXT NOT NULL,
        attempted_at TEXT NOT NULL,
        succeeded INTEGER NOT NULL DEFAULT 0
    )
    """)
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_lookup
    ON auth_login_attempts(email, client_ip, attempted_at, succeeded)
    """)

    # Tokens de recuperação: apenas o hash é armazenado; o token em claro só vai por e-mail.
    c.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        email TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        used_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_password_reset_email_created
    ON password_reset_tokens(email, created_at)
    """)


    # Financeiro: lançamentos manuais e configuração de comissão por barbeiro.
    # Valores monetários são armazenados em centavos para evitar erros de ponto flutuante.
    c.execute("""
    CREATE TABLE IF NOT EXISTS financial_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income', 'expense')),
        category TEXT NOT NULL,
        description TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
        occurred_on TEXT NOT NULL,
        payment_method TEXT,
        status TEXT NOT NULL DEFAULT 'paid'
            CHECK (status IN ('pending', 'paid', 'cancelled')),
        barber_id INTEGER,
        order_id INTEGER,
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (barber_id) REFERENCES barbers(id),
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    """)
    c.execute("""
    CREATE INDEX IF NOT EXISTS idx_financial_transactions_date_status
    ON financial_transactions(occurred_on, status, transaction_type)
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS barber_commission_settings (
        barber_id INTEGER PRIMARY KEY,
        commission_percent REAL NOT NULL DEFAULT 0
            CHECK (commission_percent >= 0 AND commission_percent <= 100),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (barber_id) REFERENCES barbers(id)
    )
    """)

    conn.commit()

    # Sempre garante configurações padrão
    seed_settings(conn)

    # Seed: dados iniciais se o banco estiver vazio
    c.execute("SELECT COUNT(*) FROM services")
    if c.fetchone()[0] == 0:
        seed_data(conn)

    conn.close()


DEFAULT_SETTINGS = {
    "shop_name": "BARBERSHOP",
    "shop_slogan": "Corte de qualidade, atendimento de excelência.",
    "logo_url": "",
    "color_primary": "#c9a227",
    "color_primary_light": "#e8c547",
    "color_bg": "#0f0f0f",
    "color_card": "#1a1a1a",
    "color_text": "#f5f5f5",
    "whatsapp": "",
    "instagram": "",
    "address": "",
    "calendar_token": "",
    "whatsapp_notify": "",
    "whatsapp_api_url": "",
}


def seed_settings(conn):
    """Insere configurações padrão caso não existam."""
    c = conn.cursor()
    for key, value in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def get_settings(conn=None):
    """Retorna todas as configurações como dicionário (com defaults)."""
    import secrets as _secrets
    close = False
    if conn is None:
        conn = get_db()
        close = True
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    for r in rows:
        settings[r["key"]] = r["value"]
    # Gera token do calendário se não existir
    if not settings.get("calendar_token"):
        token = _secrets.token_hex(16)
        conn.execute("INSERT INTO settings (key, value) VALUES ('calendar_token', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (token,))
        conn.commit()
        settings["calendar_token"] = token
    if close:
        conn.close()
    return settings


def seed_data(conn):
    """Insere dados de exemplo para o sistema funcionar logo de cara."""
    c = conn.cursor()

    # Serviços
    services = [
        ("Corte Masculino", "Corte tradicional com máquina e tesoura, finalização com pomada.", 35.00, 30, "Cabelo"),
        ("Corte Degradê", "Corte com degradê (fade) nas laterais, topo modelado.", 45.00, 45, "Cabelo"),
        ("Barba Completa", "Barba feita com navalha, toalha quente e óleo pós-barba.", 30.00, 30, "Barba"),
        ("Corte + Barba", "Combo completo: corte e barba com finalização premium.", 65.00, 60, "Combo"),
        ("Pezinho", "Apenas acabamento nas laterais e nuca.", 15.00, 15, "Acabamento"),
        ("Sobrancelha", "Design e acabamento de sobrancelha.", 10.00, 10, "Acabamento"),
        ("Hidratação Capilar", "Tratamento hidratante para cabelo e barba.", 50.00, 40, "Tratamento"),
        ("Corte Infantil", "Corte para crianças até 10 anos.", 30.00, 25, "Cabelo"),
    ]
    for s in services:
        c.execute("INSERT INTO services (name, description, price, duration_min, category) VALUES (?,?,?,?,?)", s)

    # Produtos da loja
    products = [
        ("Pomada Modeladora Matte", "Pomada de fixação média, efeito matte, 80g. Ideal para cortes modernos.", 49.90, 20, "Modelagem", "https://images.unsplash.com/photo-1599351431202-1e0f0137899a?w=400"),
        ("Balm Pós-Barba", "Balm hidratante com tea tree, acalma a pele após o barbear. 100ml.", 39.90, 15, "Barba", "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=400"),
        ("Loção Pós-Barba", "Loção refrescante com álcool minimizado, previne irritações. 120ml.", 34.90, 18, "Barba", "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?w=400"),
        ("Shampoo para Barba", "Shampoo específico para barba, limpa e hidrata os fios. 250ml.", 29.90, 25, "Barba", "https://images.unsplash.com/photo-1585232004423-244e0e6904e3?w=400"),
        ("Óleo para Barba", "Óleo nutritivo com argan e jojoba, deixa a barba macia e com brilho. 30ml.", 44.90, 12, "Barba", "https://images.unsplash.com/photo-1599351431202-1e0f0137899a?w=400"),
        ("Shampoo Antiqueda", "Shampoo fortalecedor com cafeína, combate a queda. 300ml.", 54.90, 10, "Cabelo", "https://images.unsplash.com/photo-1535585209827-a15fcdbc4c2d?w=400"),
        ("Cera Modeladora", "Cera de fixação forte para penteados ousados. 75g.", 42.90, 14, "Modelagem", "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=400"),
        ("Kit Barba Completo", "Shampoo + óleo + balm para barba. Kit presenteável.", 99.90, 8, "Kit", "https://images.unsplash.com/photo-1621607512214-68297480165e?w=400"),
    ]
    for p in products:
        c.execute("INSERT INTO products (name, description, price, stock, category, image_url) VALUES (?,?,?,?,?,?)", p)

    # Portfólio (modelos de corte com explicação)
    portfolio = [
        ("Degradê Clássico (Low Fade)", "Degradê baixo, começando rente à pele na altura da orelha. Versátil, combina com qualquer tipo de cabelo e formato de rosto. Fácil de manter no dia a dia.", "https://images.unsplash.com/photo-1503951914875-cd3a8d62d94c?w=600", "Degradê", 2),
        ("Degradê Alto (High Fade)", "Degradê que começa acima da têmpora, com laterais bem curtas. Visual mais marcante e moderno, ideal para quem gosta de um corte cheio de atitude.", "https://images.unsplash.com/photo-1622286342621-4bd786c2447c?w=600", "Degradê", 2),
        ("Corte Social", "Corte clássico, laterais médias e topo penteado para o lado. Perfeito para ambientes profissionais e ocasiões formais.", "https://images.unsplash.com/photo-1599351431202-1e0f0137899a?w=600", "Clássico", 1),
        ("Corte Militar (Crew Cut)", "Corte bem curto por igual, praticidade máxima. Não precisa de produto e seca rápido. Ideal para quem não quer trabalho.", "https://images.unsplash.com/photo-1593702288056-7927b4998df2?w=600", "Curto", 1),
        ("Pompadour Moderno", "Topo volumoso penteado para trás, laterais degradê. Requer pomada e secador. Visual retrô-moderno cheio de personalidade.", "https://images.unsplash.com/photo-1605497788044-5a32c7078486?w=600", "Moderno", 2),
        ("Barba Feita com Navalha", "Barba desenhada com navalha, linhas marcadas e acabamento rente. Acompanha toalha quente e balm pós-barba.", "https://images.unsplash.com/photo-1621607512214-68297480165e?w=600", "Barba", 3),
        ("Corte com Textura (Textured Crop)", "Topo com textura e franja desconectada, laterais curtas. Estilo europeu, moderno e de baixa manutenção.", "https://images.unsplash.com/photo-1622288432450-277d0fef5ed6?w=600", "Moderno", 2),
        ("Corte Afro com Degradê", "Valoriza o volume natural do cabelo afro com degradê nas laterais. Estilo autêntico e cheio de personalidade.", "https://images.unsplash.com/photo-1519699047748-de8e457a634e?w=600", "Afro", 2),
    ]
    for p in portfolio:
        c.execute("INSERT INTO portfolio (name, description, image_url, category, service_id) VALUES (?,?,?,?,?)", p)

    # Cria conta administrativa somente quando credenciais são configuradas no ambiente.
    # Nunca inserir uma senha padrão conhecida em uma instalação nova.
    import os
    admin_email = os.getenv("INITIAL_ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    if admin_email and admin_password:
        from auth import hash_password
        existing_admin = c.execute(
            "SELECT id FROM users WHERE role='admin' LIMIT 1"
        ).fetchone()
        if not existing_admin:
            admin_hash = hash_password(admin_password)
            c.execute(
                "INSERT INTO users (name, email, phone, password_hash, role) VALUES (?,?,?,?,?)",
                ("Administrador", admin_email, "", admin_hash, "admin")
            )
            admin_id = c.lastrowid
            c.execute(
                "INSERT INTO barbers (user_id, name, bio, active) VALUES (?,?,?,?)",
                (admin_id, "Administrador", "", 1)
            )

    conn.commit()
    print("Dados iniciais inseridos.")
    if not (admin_email and admin_password):
        print("Configure INITIAL_ADMIN_EMAIL e INITIAL_ADMIN_PASSWORD para criar o administrador inicial.")


if __name__ == "__main__":
    init_db()
    print("Banco de dados inicializado em:", DB_PATH)
