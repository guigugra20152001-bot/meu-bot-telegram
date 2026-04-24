import sqlite3, os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "loja.db")

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._seed()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0.0,
                registered_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                emoji TEXT DEFAULT '📦',
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER REFERENCES categories(id),
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                price REAL NOT NULL,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER REFERENCES products(id),
                credentials TEXT NOT NULL,
                status TEXT DEFAULT 'available',
                order_id INTEGER,
                added_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER REFERENCES products(id),
                payment_method TEXT,
                status TEXT DEFAULT 'pending',
                proof_file_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                payment_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    def _seed(self):
        if self.conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0:
            return
        self.conn.executescript("""
            INSERT INTO categories (name, emoji) VALUES
                ('Instagram', '📸'),
                ('TikTok', '🎵'),
                ('Facebook', '👤'),
                ('Twitter/X', '🐦'),
                ('YouTube', '▶️'),
                ('Outros', '🌐');
        """)
        self.conn.commit()

    # Users
    def register_user(self, uid, username, first_name=""):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (id, username, first_name) VALUES (?,?,?)",
            (uid, username, first_name))
        self.conn.commit()

    def get_user(self, uid):
        return self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def add_balance(self, uid, amount):
        self.conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
        self.conn.commit()

    def deduct_balance(self, uid, amount):
        self.conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))
        self.conn.commit()

    def get_all_users(self):
        return self.conn.execute("SELECT * FROM users ORDER BY registered_at DESC").fetchall()

    # Categories
    def get_categories(self):
        return self.conn.execute("SELECT * FROM categories WHERE active=1").fetchall()

    def get_categories_with_products(self):
        cats = self.get_categories()
        result = []
        for c in cats:
            products = self.get_products_by_category(c["id"])
            result.append({"id": c["id"], "name": c["name"], "emoji": c["emoji"],
                           "products": [dict(p) for p in products]})
        return result

    def add_category(self, name, emoji="📦"):
        cur = self.conn.execute("INSERT INTO categories (name, emoji) VALUES (?,?)", (name, emoji))
        self.conn.commit()
        return cur.lastrowid

    def delete_category(self, cat_id):
        self.conn.execute("UPDATE categories SET active=0 WHERE id=?", (cat_id,))
        self.conn.commit()

    # Products
    def get_products_by_category(self, cat_id):
        rows = self.conn.execute(
            "SELECT * FROM products WHERE category_id=? AND active=1", (cat_id,)).fetchall()
        result = []
        for r in rows:
            p = dict(r)
            p["stock"] = self.count_available_stock_by_product(r["id"])
            result.append(p)
        return result

    def get_all_products(self):
        rows = self.conn.execute("""
            SELECT p.*, c.name as category_name FROM products p
            JOIN categories c ON c.id=p.category_id
            WHERE p.active=1 ORDER BY c.name, p.name
        """).fetchall()
        result = []
        for r in rows:
            p = dict(r)
            p["stock"] = self.count_available_stock_by_product(r["id"])
            result.append(p)
        return result

    def get_product(self, pid):
        return self.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()

    def add_product(self, cat_id, name, price, description=""):
        cur = self.conn.execute(
            "INSERT INTO products (category_id, name, price, description) VALUES (?,?,?,?)",
            (cat_id, name, price, description))
        self.conn.commit()
        return cur.lastrowid

    def delete_product(self, pid):
        self.conn.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        self.conn.commit()

    # Stock
    def count_available_stock_by_product(self, pid):
        return self.conn.execute(
            "SELECT COUNT(*) FROM stock WHERE product_id=? AND status='available'",
            (pid,)).fetchone()[0]

    def add_stock(self, product_id, credentials):
        self.conn.execute(
            "INSERT INTO stock (product_id, credentials) VALUES (?,?)",
            (product_id, credentials))
        self.conn.commit()

    def get_and_reserve_account(self, product_id, order_id):
        acc = self.conn.execute(
            "SELECT * FROM stock WHERE product_id=? AND status='available' LIMIT 1",
            (product_id,)).fetchone()
        if not acc:
            return None
        self.conn.execute(
            "UPDATE stock SET status='sold', order_id=? WHERE id=?",
            (order_id, acc["id"]))
        self.conn.commit()
        return acc

    # Orders
    def create_order(self, user_id, product_id, payment_method):
        cur = self.conn.execute(
            "INSERT INTO orders (user_id, product_id, payment_method) VALUES (?,?,?)",
            (user_id, product_id, payment_method))
        self.conn.commit()
        return cur.lastrowid

    def get_order(self, oid):
        return self.conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()

    def get_user_orders(self, uid):
        return self.conn.execute("""
            SELECT o.*, p.name as product_name, p.price,
                   s.credentials
            FROM orders o
            JOIN products p ON p.id=o.product_id
            LEFT JOIN stock s ON s.order_id=o.id
            WHERE o.user_id=? ORDER BY o.created_at DESC
        """, (uid,)).fetchall()

    def get_all_orders(self):
        return self.conn.execute("""
            SELECT o.*, p.name as product_name, p.price,
                   u.username, u.first_name
            FROM orders o
            JOIN products p ON p.id=o.product_id
            LEFT JOIN users u ON u.id=o.user_id
            ORDER BY o.created_at DESC LIMIT 200
        """).fetchall()

    def update_order_status(self, oid, status):
        self.conn.execute(
            "UPDATE orders SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, oid))
        self.conn.commit()

    def update_order_proof(self, oid, file_id):
        self.conn.execute("UPDATE orders SET proof_file_id=? WHERE id=?", (file_id, oid))
        self.conn.commit()

    # Payments
    def create_payment(self, uid, amount, payment_id):
        cur = self.conn.execute(
            "INSERT INTO payments (user_id, amount, payment_id) VALUES (?,?,?)",
            (uid, amount, payment_id))
        self.conn.commit()
        return cur.lastrowid

    def get_payment_by_external_id(self, payment_id):
        return self.conn.execute(
            "SELECT * FROM payments WHERE payment_id=?", (payment_id,)).fetchone()

    def complete_payment(self, payment_id):
        pay = self.get_payment_by_external_id(payment_id)
        if pay and pay["status"] == "pending":
            self.conn.execute(
                "UPDATE payments SET status='completed' WHERE payment_id=?", (payment_id,))
            self.add_balance(pay["user_id"], pay["amount"])
            self.conn.commit()
            return pay
        return None

    # Stats
    def get_stats(self):
        users = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        orders = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        completed = self.conn.execute("SELECT COUNT(*) FROM orders WHERE status='completed'").fetchone()[0]
        pending = self.conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
        revenue = self.conn.execute("""
            SELECT COALESCE(SUM(p.price),0) FROM orders o
            JOIN products p ON p.id=o.product_id WHERE o.status='completed'
        """).fetchone()[0]
        stock_total = self.conn.execute(
            "SELECT COUNT(*) FROM stock WHERE status='available'").fetchone()[0]
        return {"users": users, "orders": orders, "completed": completed,
                "pending": pending, "revenue": revenue, "stock": stock_total}
