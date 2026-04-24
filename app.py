"""
Loja de Contas Digitais — Flask Web App + Telegram Bot
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import hashlib, hmac, os, json
from database import Database
from payments import PaymentManager

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "mude-isso-em-producao-12345")

db = Database()
pay = PaymentManager()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip()]

# ── Helpers ──────────────────────────────────

def verify_telegram_auth(data: dict) -> bool:
    check_hash = data.pop("hash", "")
    sorted_data = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    computed = hmac.new(secret, sorted_data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, check_hash)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_id") not in ADMIN_IDS:
            return jsonify({"error": "Acesso negado"}), 403
        return f(*args, **kwargs)
    return decorated

# ── Auth ─────────────────────────────────────

@app.route("/login")
def login():
    return render_template("login.html", bot_username=os.getenv("BOT_USERNAME", "seubot"))

@app.route("/auth/telegram", methods=["POST"])
def auth_telegram():
    data = request.json.copy()
    if not verify_telegram_auth(data):
        return jsonify({"error": "Auth inválida"}), 401
    user_id = int(data["id"])
    db.register_user(user_id, data.get("username", data.get("first_name", "")), data.get("first_name", ""))
    session["user_id"] = user_id
    session["username"] = data.get("username", data.get("first_name", ""))
    session["first_name"] = data.get("first_name", "")
    session["is_admin"] = user_id in ADMIN_IDS
    return jsonify({"ok": True})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Páginas públicas ──────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    categories = db.get_categories()
    return render_template("index.html", categories=categories,
                           user=session, is_admin=session.get("is_admin"))

@app.route("/loja")
@login_required
def loja():
    categories = db.get_categories_with_products()
    user = db.get_user(session["user_id"])
    return render_template("loja.html", categories=categories, user=user,
                           is_admin=session.get("is_admin"))

@app.route("/pedidos")
@login_required
def pedidos():
    orders = db.get_user_orders(session["user_id"])
    user = db.get_user(session["user_id"])
    return render_template("pedidos.html", orders=orders, user=user,
                           is_admin=session.get("is_admin"))

@app.route("/saldo")
@login_required
def saldo():
    user = db.get_user(session["user_id"])
    return render_template("saldo.html", user=user, is_admin=session.get("is_admin"))

# ── API: Loja ─────────────────────────────────

@app.route("/api/comprar", methods=["POST"])
@login_required
def api_comprar():
    data = request.json
    product_id = data.get("product_id")
    qty = int(data.get("quantidade", 1))

    product = db.get_product(product_id)
    if not product:
        return jsonify({"error": "Produto não encontrado"}), 404

    stock_count = db.count_available_stock_by_product(product_id)
    if stock_count < qty:
        return jsonify({"error": f"Estoque insuficiente. Disponível: {stock_count}"}), 400

    user = db.get_user(session["user_id"])
    total = product["price"] * qty

    if user["balance"] < total:
        return jsonify({"error": f"Saldo insuficiente. Seu saldo: R${user['balance']:.2f}"}), 400

    # Deduz saldo e entrega contas
    db.deduct_balance(session["user_id"], total)
    accounts = []
    for _ in range(qty):
        order_id = db.create_order(session["user_id"], product_id, "saldo")
        account = db.get_and_reserve_account(product_id, order_id)
        if account:
            accounts.append(account["credentials"])
            db.update_order_status(order_id, "completed")

    return jsonify({"ok": True, "contas": accounts, "total": total})

# ── API: Saldo ────────────────────────────────

@app.route("/api/saldo/pix", methods=["POST"])
@login_required
def api_pix():
    data = request.json
    amount = float(data.get("amount", 0))
    if amount < 5:
        return jsonify({"error": "Valor mínimo é R$5,00"}), 400

    result = pay.create_pix_payment(amount, session["user_id"])
    if not result:
        return jsonify({"error": "Erro ao gerar PIX"}), 500
    return jsonify(result)

@app.route("/api/saldo/check/<payment_id>")
@login_required
def api_check_payment(payment_id):
    result = pay.check_payment(payment_id, session["user_id"])
    return jsonify(result)

@app.route("/webhook/mercadopago", methods=["POST"])
def webhook_mp():
    data = request.json
    pay.process_webhook(data)
    return "", 200

# ── API: Admin ────────────────────────────────

@app.route("/admin")
@login_required
def admin():
    if not session.get("is_admin"):
        return redirect(url_for("loja"))
    stats = db.get_stats()
    return render_template("admin.html", stats=stats, user=session, is_admin=True)

@app.route("/admin/produtos")
@login_required
def admin_produtos():
    if not session.get("is_admin"):
        return redirect(url_for("loja"))
    categories = db.get_categories_with_products()
    return render_template("admin_produtos.html", categories=categories,
                           user=session, is_admin=True)

@app.route("/admin/estoque")
@login_required
def admin_estoque():
    if not session.get("is_admin"):
        return redirect(url_for("loja"))
    products = db.get_all_products()
    return render_template("admin_estoque.html", products=products,
                           user=session, is_admin=True)

@app.route("/admin/pedidos")
@login_required
def admin_pedidos():
    if not session.get("is_admin"):
        return redirect(url_for("loja"))
    orders = db.get_all_orders()
    return render_template("admin_pedidos.html", orders=orders,
                           user=session, is_admin=True)

@app.route("/api/admin/categoria", methods=["POST"])
@login_required
@admin_required
def api_add_category():
    data = request.json
    cat_id = db.add_category(data["name"], data.get("emoji", "📦"))
    return jsonify({"ok": True, "id": cat_id})

@app.route("/api/admin/categoria/<int:cat_id>", methods=["DELETE"])
@login_required
@admin_required
def api_del_category(cat_id):
    db.delete_category(cat_id)
    return jsonify({"ok": True})

@app.route("/api/admin/produto", methods=["POST"])
@login_required
@admin_required
def api_add_product():
    data = request.json
    pid = db.add_product(data["category_id"], data["name"],
                         float(data["price"]), data.get("description", ""))
    return jsonify({"ok": True, "id": pid})

@app.route("/api/admin/produto/<int:pid>", methods=["DELETE"])
@login_required
@admin_required
def api_del_product(pid):
    db.delete_product(pid)
    return jsonify({"ok": True})

@app.route("/api/admin/estoque", methods=["POST"])
@login_required
@admin_required
def api_add_stock():
    data = request.json
    product_id = int(data["product_id"])
    lines = [l.strip() for l in data["credentials"].strip().splitlines() if l.strip()]
    for line in lines:
        db.add_stock(product_id, line)
    return jsonify({"ok": True, "adicionados": len(lines)})

@app.route("/api/admin/saldo", methods=["POST"])
@login_required
@admin_required
def api_add_balance():
    data = request.json
    db.add_balance(int(data["user_id"]), float(data["amount"]))
    return jsonify({"ok": True})

@app.route("/api/admin/stats")
@login_required
@admin_required
def api_stats():
    return jsonify(db.get_stats())

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
