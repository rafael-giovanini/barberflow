#!/usr/bin/env python3
"""
Cria uma base SQLite isolada para demonstração do BarberFlow.

Uso:
  python seed_demo.py
  python seed_demo.py --db /caminho/barberflow-demo.demo.db
  python seed_demo.py --db /caminho/barberflow-demo.demo.db --reset

O script nunca deve apontar para o banco operacional. A senha inicial do
administrador é gerada aleatoriamente e exibida uma única vez no terminal.
"""
import argparse
import calendar
import os
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "barberflow-demo.demo.db"
MARKER_KEY = "demo_seed_version"
MARKER_VERSION = "1"


def month_date(month_offset: int, day: int) -> date:
    today = date.today().replace(day=1)
    month_index = today.year * 12 + today.month - 1 + month_offset
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def parse_args():
    parser = argparse.ArgumentParser(description="Preenche uma base isolada de demonstração.")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--db", type=Path, help="Arquivo SQLite exclusivo da demonstração.")
    destination.add_argument(
        "--database-url",
        default=os.getenv("BARBERFLOW_DEMO_DATABASE_URL", "").strip(),
        help=(
            "URL de um banco PostgreSQL dedicado à demonstração (nome deve "
            "conter demo); também pode vir de BARBERFLOW_DEMO_DATABASE_URL."
        ),
    )
    parser.add_argument("--admin-email", default="admin@barberflow.teste")
    parser.add_argument("--reset", action="store_true", help="Apaga somente o arquivo de demonstração indicado antes de recriá-lo.")
    return parser.parse_args()


def main():
    args = parse_args()
    demo_db = args.db.expanduser().resolve() if args.db else DEFAULT_DB
    postgres_demo = bool(args.database_url)
    if postgres_demo:
        from urllib.parse import urlparse
        parsed_url = urlparse(args.database_url)
        database_name = parsed_url.path.rstrip("/").split("/")[-1].lower()
        if "demo" not in database_name:
            raise SystemExit("ERRO: o nome do banco PostgreSQL dedicado deve conter 'demo'.")
        if args.reset:
            raise SystemExit("ERRO: --reset não é permitido para PostgreSQL.")
        # A inicialização só é autorizada em um banco público vazio ou já marcado
        # por este script; assim, a carga padrão nunca toca um banco existente.
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(args.database_url, connect_timeout=10, row_factory=dict_row) as probe:
            settings_table = probe.execute("SELECT to_regclass('public.settings') AS table_name").fetchone()["table_name"]
            if settings_table:
                marker = probe.execute("SELECT value FROM settings WHERE key=%s", (MARKER_KEY,)).fetchone()
                if marker and marker["value"] == MARKER_VERSION:
                    print("Base de demonstração PostgreSQL já preenchida; nenhuma duplicação realizada.")
                    return
                raise SystemExit("ERRO: PostgreSQL informado já contém tabelas sem o marcador da demonstração.")
            existing_tables = probe.execute(
                "SELECT COUNT(*) AS total FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
            ).fetchone()["total"]
            if existing_tables:
                raise SystemExit("ERRO: PostgreSQL informado não está vazio; use um banco exclusivo de demonstração.")
    elif os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("ERRO: DATABASE_URL está definida. Informe um PostgreSQL demo dedicado por --database-url ou remova a variável para usar SQLite.")
    else:
        configured_db = Path(os.getenv("DATABASE_PATH", ROOT / "barbearia.db")).expanduser().resolve()
        if demo_db == configured_db or demo_db == ROOT / "barbearia.db":
            raise SystemExit("ERRO: o banco operacional não pode ser usado como demonstração.")
        if demo_db.suffixes[-2:] != [".demo", ".db"]:
            raise SystemExit("ERRO: use um nome terminado em .demo.db para identificar a base isolada.")
    if not args.admin_email.strip() or "@" not in args.admin_email:
        raise SystemExit("ERRO: informe um e-mail válido para o administrador.")

    if not postgres_demo and demo_db.exists():
        if not args.reset:
            os.environ["DATABASE_PATH"] = str(demo_db)
            from database import get_db
            conn = get_db()
            marker = conn.execute("SELECT value FROM settings WHERE key=?", (MARKER_KEY,)).fetchone()
            conn.close()
            if marker and marker["value"] == MARKER_VERSION:
                print(f"Base de demonstração já preenchida; nenhuma duplicação realizada: {demo_db}")
                return
            raise SystemExit("ERRO: o arquivo já existe e não possui o marcador desta demonstração. Use outro caminho ou --reset.")
        for suffix in ("", "-wal", "-shm"):
            Path(str(demo_db) + suffix).unlink(missing_ok=True)

    if not postgres_demo:
        demo_db.parent.mkdir(parents=True, exist_ok=True)
    supplied_password = os.getenv("DEMO_ADMIN_PASSWORD", "")
    if supplied_password and len(supplied_password) < 10:
        raise SystemExit("ERRO: DEMO_ADMIN_PASSWORD deve ter pelo menos 10 caracteres.")
    admin_password = supplied_password or (secrets.token_urlsafe(18) + "A9!")
    if postgres_demo:
        os.environ["DATABASE_URL"] = args.database_url
    else:
        os.environ["DATABASE_PATH"] = str(demo_db)
    os.environ["INITIAL_ADMIN_EMAIL"] = args.admin_email.strip().lower()
    os.environ["INITIAL_ADMIN_PASSWORD"] = admin_password

    # Importação posterior à definição de DATABASE_PATH garante isolamento.
    from database import init_db, get_db
    from auth import hash_password

    init_db()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        admin = conn.execute("SELECT id FROM users WHERE email=? AND role='admin'",
                             (args.admin_email.strip().lower(),)).fetchone()
        if not admin:
            raise RuntimeError("Não foi possível provisionar o administrador da demonstração.")
        admin_id = admin["id"]
        admin_barber = conn.execute("SELECT id FROM barbers WHERE user_id=?", (admin_id,)).fetchone()
        if not admin_barber:
            cur = conn.execute("INSERT INTO barbers (user_id, name, bio, active) VALUES (?, ?, ?, 1) RETURNING id",
                               (admin_id, "Alexandre Costa", "Barbeiro responsável pela unidade demonstrativa."))
            admin_barber_id = cur.fetchone()["id"]
        else:
            admin_barber_id = admin_barber["id"]

        # Dados fictícios: nenhuma pessoa real ou dado de produção é copiado.
        barber_user_id = conn.execute("SELECT id FROM users WHERE email='barbeiro.demo@barberflow.local'").fetchone()
        if not barber_user_id:
            cur = conn.execute("""
                INSERT INTO users (name,email,phone,password_hash,role,first_access_required)
                VALUES (?,?,?,?, 'barber',1) RETURNING id
            """, ("Bruno Almeida", "barbeiro.demo@barberflow.local", "(11) 90000-0002",
                  hash_password(secrets.token_urlsafe(32))))
            barber_user_id = cur.fetchone()["id"]
        else:
            barber_user_id = barber_user_id["id"]
        second_barber = conn.execute("SELECT id FROM barbers WHERE user_id=?", (barber_user_id,)).fetchone()
        if not second_barber:
            second_barber_id = conn.execute("""
                INSERT INTO barbers (user_id,name,bio,active,work_start,work_end,lunch_start,lunch_end,work_days)
                VALUES (?,?,?,1,'09:00','19:00','12:00','13:00','[1,2,3,4,5,6]') RETURNING id
            """, (barber_user_id, "Bruno Almeida", "Especialista em degradê e barba.")).fetchone()["id"]
        else:
            second_barber_id = second_barber["id"]

        conn.execute("INSERT INTO barber_commission_settings (barber_id,commission_percent) VALUES (?,?) ON CONFLICT(barber_id) DO UPDATE SET commission_percent=excluded.commission_percent",
                     (admin_barber_id, 50))
        conn.execute("INSERT INTO barber_commission_settings (barber_id,commission_percent) VALUES (?,?) ON CONFLICT(barber_id) DO UPDATE SET commission_percent=excluded.commission_percent",
                     (second_barber_id, 45))

        customers = [
            ("Lucas Martins", "lucas.martins.demo@barberflow.local", "(11) 90000-0101"),
            ("Gabriel Oliveira", "gabriel.oliveira.demo@barberflow.local", "(11) 90000-0102"),
            ("Pedro Henrique", "pedro.henrique.demo@barberflow.local", "(11) 90000-0103"),
            ("Matheus Souza", "matheus.souza.demo@barberflow.local", "(11) 90000-0104"),
            ("Felipe Rodrigues", "felipe.rodrigues.demo@barberflow.local", "(11) 90000-0105"),
            ("Rafael Lima", "rafael.lima.demo@barberflow.local", "(11) 90000-0106"),
            ("João Pedro", "joao.pedro.demo@barberflow.local", "(11) 90000-0107"),
            ("André Carvalho", "andre.carvalho.demo@barberflow.local", "(11) 90000-0108"),
            ("Thiago Ferreira", "thiago.ferreira.demo@barberflow.local", "(11) 90000-0109"),
            ("Eduardo Santos", "eduardo.santos.demo@barberflow.local", "(11) 90000-0110"),
        ]
        customer_ids = []
        for name, email, phone in customers:
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                customer_ids.append(row["id"])
            else:
                cur = conn.execute("""
                    INSERT INTO users (name,email,phone,password_hash,role,first_access_required)
                    VALUES (?,?,?,?, 'customer',1) RETURNING id
                """, (name,email,phone,hash_password(secrets.token_urlsafe(32))))
                customer_ids.append(cur.fetchone()["id"])

        services = conn.execute("SELECT id,name,price,duration_min FROM services ORDER BY id").fetchall()
        products = conn.execute("SELECT id,name,price FROM products ORDER BY id").fetchall()
        if len(services) < 4 or len(products) < 4:
            raise RuntimeError("Catálogo inicial insuficiente para montar a demonstração.")

        # Custos plausíveis para que o relatório de margem não fique zerado.
        for product in products:
            cost = round(float(product["price"]) * 0.48, 2)
            conn.execute("UPDATE products SET cost_price=? WHERE id=?", (cost, product["id"]))
            stock = conn.execute("SELECT stock FROM products WHERE id=?", (product["id"],)).fetchone()["stock"]
            if stock > 0:
                conn.execute("""
                    INSERT INTO stock_movements (product_id,movement_type,quantity,unit_cost_cents,note,created_by)
                    VALUES (?,'opening',?,?,?,?)
                """, (product["id"], stock, round(cost * 100), "Estoque inicial fictício da demonstração", admin_id))

        # Compras e vendas distribuídas pelos últimos seis meses.
        order_count = 0
        for month_offset in range(-6, 0):
            # Entrada de estoque e saída de caixa explícitas em cada mês.
            # Não dependemos de o saldo inicial acabar para que a demonstração
            # tenha histórico realista de reposição de produtos.
            purchase_product = products[abs(month_offset) % len(products)]
            purchase_quantity = 8
            purchase_cost_cents = round(float(purchase_product["price"]) * 0.48 * 100)
            purchase_day = month_date(month_offset, 3)
            conn.execute(
                "UPDATE products SET stock=stock+? WHERE id=?",
                (purchase_quantity, purchase_product["id"]),
            )
            conn.execute("""
                INSERT INTO stock_movements
                    (product_id,movement_type,quantity,unit_cost_cents,note,created_by,created_at)
                VALUES (?,'purchase',?,?,?,?,?)
            """, (
                purchase_product["id"], purchase_quantity, purchase_cost_cents,
                "Reposição fictícia mensal de estoque", admin_id,
                datetime.combine(purchase_day, datetime.min.time()).isoformat(sep=" "),
            ))
            conn.execute("""
                INSERT INTO financial_transactions
                    (transaction_type,category,description,amount_cents,occurred_on,
                     payment_method,status,created_by,created_at)
                VALUES ('expense','Estoque',?,?,?,'pix','paid',?,?)
            """, (
                f"Compra demonstrativa de {purchase_product['name']}",
                purchase_cost_cents * purchase_quantity, purchase_day.isoformat(), admin_id,
                datetime.combine(purchase_day, datetime.min.time()).isoformat(sep=" "),
            ))

            for batch in range(4):
                day = 4 + batch * 6
                occurred = month_date(month_offset, day)
                customer_id = customer_ids[(abs(month_offset) * 3 + batch) % len(customer_ids)]
                product_a = products[(abs(month_offset) + batch) % len(products)]
                product_b = products[(abs(month_offset) + batch + 2) % len(products)]
                qty_a = 1 + (batch % 2)
                qty_b = 1 if batch % 3 == 0 else 0
                items = [(product_a, qty_a)]
                if qty_b and product_b["id"] != product_a["id"]:
                    items.append((product_b, qty_b))
                total = sum(float(p["price"]) * qty for p, qty in items)
                status = ("paid", "paid", "pending", "cancelled")[batch]
                cur = conn.execute("""
                    INSERT INTO orders (user_id,customer_name,customer_phone,address,total,status,payment_method,created_at)
                    VALUES (?,?,?,?,?,?,?,?) RETURNING id
                """, (customer_id, customers[customer_ids.index(customer_id)][0],
                      customers[customer_ids.index(customer_id)][2], "Endereço fictício - unidade demo",
                      round(total, 2), status, ("pix","cartao","dinheiro","pix")[batch],
                      datetime.combine(occurred, datetime.min.time()).isoformat(sep=" ")))
                order_id = cur.fetchone()["id"]
                order_count += 1
                for product, qty in items:
                    current_stock = conn.execute("SELECT stock FROM products WHERE id=?", (product["id"],)).fetchone()["stock"]
                    if current_stock < qty:
                        conn.execute("UPDATE products SET stock=stock+20 WHERE id=?", (product["id"],))
                        conn.execute("""
                            INSERT INTO stock_movements (product_id,movement_type,quantity,unit_cost_cents,note,created_by,created_at)
                            VALUES (?,'purchase',20,?,?,?,?)
                        """, (product["id"], round(float(product["price"]) * 0.48 * 100),
                              "Reposição fictícia para demonstração", admin_id,
                              datetime.combine(occurred - timedelta(days=2), datetime.min.time()).isoformat(sep=" ")))
                    cost_cents = round(float(product["price"]) * 0.48 * 100)
                    conn.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, product["id"]))
                    conn.execute("""
                        INSERT INTO order_items (order_id,product_id,product_name,quantity,price)
                        VALUES (?,?,?,?,?)
                    """, (order_id, product["id"], product["name"], qty, product["price"]))
                    conn.execute("""
                        INSERT INTO stock_movements (product_id,movement_type,quantity,unit_cost_cents,note,order_id,created_by,created_at)
                        VALUES (?,'sale',?,?,?,?,?,?)
                    """, (product["id"], -qty, cost_cents, f"Venda fictícia do pedido #{order_id}",
                          order_id, admin_id, datetime.combine(occurred, datetime.min.time()).isoformat(sep=" ")))
                    if status == "cancelled":
                        conn.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, product["id"]))
                        conn.execute("""
                            INSERT INTO stock_movements (product_id,movement_type,quantity,unit_cost_cents,note,order_id,created_by,created_at)
                            VALUES (?,'return',?,?,?,?,?,?)
                        """, (product["id"], qty, cost_cents, f"Devolução fictícia do pedido #{order_id}",
                              order_id, admin_id, datetime.combine(occurred, datetime.min.time()).isoformat(sep=" ")))
                if status in ("paid", "pending"):
                    conn.execute("""
                        INSERT INTO financial_transactions
                            (transaction_type,category,description,amount_cents,occurred_on,payment_method,status,order_id,created_by)
                        VALUES ('income','Loja',?,?,?,?,?,?,?)
                    """, (f"Pedido demonstrativo #{order_id}", round(total * 100), occurred.isoformat(),
                          ("pix","cartao","dinheiro","pix")[batch], status, order_id, admin_id))
                else:
                    conn.execute("""
                        INSERT INTO financial_transactions
                            (transaction_type,category,description,amount_cents,occurred_on,payment_method,status,order_id,created_by)
                        VALUES ('income','Loja',?,?,?,?, 'cancelled',?,?)
                    """, (f"Pedido cancelado demonstrativo #{order_id}", round(total * 100),
                          occurred.isoformat(), "pix", order_id, admin_id))

            # Despesas operacionais mensais e reposição de estoque fictícia.
            for category, description, amount in (
                ("Operacional", "Aluguel e estrutura - demonstrativo", 120000),
                ("Insumos", "Materiais de consumo - demonstrativo", 28500),
                ("Marketing", "Divulgação local - demonstrativo", 15000),
            ):
                conn.execute("""
                    INSERT INTO financial_transactions
                        (transaction_type,category,description,amount_cents,occurred_on,payment_method,status,created_by)
                    VALUES ('expense',?,?,?,?, 'pix','paid',?)
                """, (category, description, amount, month_date(month_offset, 2).isoformat(), admin_id))

            # Serviços concluídos geram produção e receitas pendentes, conforme o fluxo real.
            for index in range(6):
                service = services[(index + abs(month_offset)) % len(services)]
                barber_id = admin_barber_id if index % 2 == 0 else second_barber_id
                customer_id = customer_ids[(index + abs(month_offset)) % len(customer_ids)]
                service_day = month_date(month_offset, 5 + index * 3)
                start_hour = 9 + (index % 5)
                start_time = f"{start_hour:02d}:00"
                end_dt = datetime.combine(service_day, datetime.strptime(start_time, "%H:%M").time()) + timedelta(minutes=service["duration_min"])
                cur = conn.execute("""
                    INSERT INTO appointments
                        (user_id,barber_id,service_id,appointment_date,start_time,end_time,status,notes,service_price_cents)
                    VALUES (?,?,?,?,?,?,'completed',?,?) RETURNING id
                """, (customer_id, barber_id, service["id"], service_day.isoformat(), start_time,
                      end_dt.strftime("%H:%M"), "Atendimento fictício para demonstração.",
                      round(float(service["price"]) * 100)))
                appointment_id = cur.fetchone()["id"]
                conn.execute("""
                    INSERT INTO financial_transactions
                        (transaction_type,category,description,amount_cents,occurred_on,status,barber_id,appointment_id,created_by)
                    VALUES ('income','Serviços',?,?,?,'pending',?,?,?)
                """, (f"Atendimento demonstrativo #{appointment_id}", round(float(service["price"]) * 100),
                      service_day.isoformat(), barber_id, appointment_id, admin_id))

        # Alguns horários futuros tornam a agenda visualmente útil na apresentação.
        next_week = date.today() + timedelta(days=7)
        for index in range(4):
            service = services[index % len(services)]
            barber_id = admin_barber_id if index % 2 == 0 else second_barber_id
            start = datetime.combine(next_week + timedelta(days=index), datetime.strptime("10:00", "%H:%M").time())
            conn.execute("""
                INSERT INTO appointments
                    (user_id,barber_id,service_id,appointment_date,start_time,end_time,status,notes,service_price_cents)
                VALUES (?,?,?,?,?,?,'scheduled',?,?)
            """, (customer_ids[index], barber_id, service["id"], start.date().isoformat(),
                  start.strftime("%H:%M"), (start + timedelta(minutes=service["duration_min"])).strftime("%H:%M"),
                  "Agendamento futuro fictício.", round(float(service["price"]) * 100)))

        conn.execute("UPDATE settings SET value='BARBERFLOW DEMONSTRAÇÃO' WHERE key='shop_name'")
        conn.execute("INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (MARKER_KEY, MARKER_VERSION))
        conn.commit()

        summary = {
            "clientes": conn.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
            "barbeiros": conn.execute("SELECT COUNT(*) FROM barbers WHERE active=1").fetchone()[0],
            "pedidos": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "atendimentos": conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
            "lancamentos_financeiros": conn.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0],
            "movimentacoes_estoque": conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0],
            "entradas_compra_estoque": conn.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE movement_type='purchase'"
            ).fetchone()[0],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("\nBASE DE DEMONSTRAÇÃO CRIADA")
    print("Banco: PostgreSQL dedicado" if postgres_demo else f"Banco: {demo_db}")
    print(f"Administrador: {args.admin_email.strip().lower()}")
    if supplied_password:
        print("Senha administrativa definida por DEMO_ADMIN_PASSWORD (não exibida por segurança).")
    else:
        print(f"Senha inicial (guarde agora): {admin_password}")
    print("A conta é exclusiva desta base. Altere a senha após o primeiro acesso.")
    print("Resumo: " + ", ".join(f"{key}={value}" for key, value in summary.items()))
    print("Para iniciar a aplicação com esta base, configure DATABASE_URL para o banco demo." if postgres_demo else "Para iniciar a aplicação com esta base, defina DATABASE_PATH para o caminho acima antes de iniciar o servidor.")


if __name__ == "__main__":
    main()
