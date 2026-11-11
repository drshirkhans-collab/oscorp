import os
import sqlite3
import threading
from datetime import datetime, timedelta
from flask import Flask
import telebot
from telebot import types

TOKEN = os.getenv("BOT_TOKEN")
CURRENCY = "₼"
WEEKLY_LIMIT = 5000

CATEGORIES = {
    "Зарплаты сотрудников": "💵",
    "Расходы на фирму": "🏢",
    "Расходники (салфетки)": "💉",
    "Аренда": "🔑",
    "Пломбы": "💎",
    "Стомат. материалы": "🩺",
    "Мобильные расходы": "📱",
    "Прочие расходы": "⚙️"
}

bot = telebot.TeleBot(TOKEN)
user_state = {}

def init_db():
    conn = sqlite3.connect('dental.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, amount REAL, comment TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, debt REAL DEFAULT 0.0)')
    c.execute('CREATE TABLE IF NOT EXISTS firms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, debt REAL DEFAULT 0.0)')
    c.execute('CREATE TABLE IF NOT EXISTS cons_staff (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS misc_cells (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)')
    conn.commit()
    conn.close()

def main_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("➕ Добавить расход / Операцию")
    m.row("📊 Отчет за неделю", "💳 Баланс долгов")
    return m

@bot.message_handler(commands=['start'])
def start(m):
    init_db()
    bot.send_message(m.chat.id, "🏥 *Финансовый учет стоматологии*\nВыберите действие:", parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "➕ Добавить расход / Операцию")
def choose_cat(m):
    init_db()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for cat, em in CATEGORIES.items():
        mk.add(types.InlineKeyboardButton(text=f"{em} {cat}", callback_data=f"cat_{cat}"))
    bot.send_message(m.chat.id, "📊 Выберите раздел:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cat_'))
def cat_sel(c):
    cat = c.data.replace('cat_', '')
    cid, mid = c.message.chat.id, c.message.message_id
    if cat == "Зарплаты сотрудников":
        show_list(cid, mid, "employees", "💵 *Зарплаты и долги:*", "emp")
    elif cat == "Расходы на фирму":
        show_list(cid, mid, "firms", "🏢 *Фирмы и долги:*", "firm")
    elif cat == "Расходники (салфетки)":
        show_simple_list(cid, mid, "cons_staff", "💉 *Расходники:*", "cstaff")
    elif cat == "Прочие расходы":
        show_simple_list(cid, mid, "misc_cells", "⚙️ *Прочие расходы:*", "misc")
    else:
        fn = f"{CATEGORIES.get(cat, '')} {cat}".strip()
        user_state[c.from_user.id] = {'act': 'exp', 'cat': fn}
        bot.edit_message_text(f"Выбрано: *{fn}*", cid, mid, parse_mode="Markdown")
        msg = bot.send_message(cid, f"💰 Сумма ({CURRENCY}):")
        bot.register_next_step_handler(msg, step_amount)

def show_list(cid, mid, table, title, prefix):
    conn = sqlite3.connect('dental.db')
    rows = conn.execute(f"SELECT name, debt FROM {table} ORDER BY name ASC").fetchall()
    conn.close()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for name, debt in rows:
        info = f" (Долг: {debt:,.0f} {CURRENCY})" if debt > 0 else ""
        mk.add(types.InlineKeyboardButton(text=f"🔹 {name}{info}", callback_data=f"{prefix}_sel_{name}"))
    mk.add(types.InlineKeyboardButton(text="➕ Добавить новое имя", callback_data=f"{prefix}_add"))
    bot.edit_message_text(title, cid, mid, parse_mode="Markdown", reply_markup=mk)

def show_simple_list(cid, mid, table, title, prefix):
    conn = sqlite3.connect('dental.db')
    rows = conn.execute(f"SELECT name FROM {table} ORDER BY name ASC").fetchall()
    conn.close()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        item_name = r[0]
        mk.add(types.InlineKeyboardButton(text=f"📌 {item_name}", callback_data=f"{prefix}_sel_{item_name}"))
    mk.add(types.InlineKeyboardButton(text="➕ Добавить ячейку / имя", callback_data=f"{prefix}_add"))
    if prefix == "cstaff":
        mk.add(types.InlineKeyboardButton(text="🏥 Общие на клинику", callback_data="cstaff_sel_Общие"))
    bot.edit_message_text(title, cid, mid, parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.endswith('_add'))
def ask_add(c):
    prefix = c.data.split('_')[0]
    bot.edit_message_text("✍️ Введите название / имя:", c.message.chat.id, c.message.message_id)
    bot.register_next_step_handler(c.message, save_add, prefix)

def save_add(m, prefix):
    name = m.text.strip()
    if not name or name.startswith(("➕", "📊", "💳")):
        bot.send_message(m.chat.id, "⚠️ Отменено.", reply_markup=main_menu())
        return
    tbl_map = {"emp": "employees", "firm": "firms", "cstaff": "cons_staff", "misc": "misc_cells"}
    conn = sqlite3.connect('dental.db')
    try:
        conn.execute(f"INSERT INTO {tbl_map[prefix]} (name) VALUES (?)", (name,))
        conn.commit()
    except Exception:
        pass
    conn.close()
    bot.send_message(m.chat.id, f"✅ *{name}* добавлено! Нажмите «➕ Добавить расход» чтобы выбрать.", parse_mode="Markdown", reply_markup=main_menu())

@bot.callback_query_handler(func=lambda c: '_sel_' in c.data)
def item_selected(c):
    prefix, name = c.data.split('_sel_', 1)
    cid, mid = c.message.chat.id, c.message.message_id
    if prefix == "emp":
        conn = sqlite3.connect('dental.db')
        res = conn.execute("SELECT debt FROM employees WHERE name=?", (name,)).fetchone()
        debt = res[0] if res else 0.0
        conn.close()
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(
            types.InlineKeyboardButton(text="💵 Выдать Зарплату", callback_data=f"op_empsal_{name}"),
            types.InlineKeyboardButton(text="💳 Выдать в Долг", callback_data=f"op_empadd_{name}"),
            types.InlineKeyboardButton(text="📉 Вернул / Списать долг", callback_data=f"op_emppay_{name}")
        )
        bot.edit_message_text(f"👤 *{name}*\nДолг клинике: `{debt:,.2f} {CURRENCY}`", cid, mid, parse_mode="Markdown", reply_markup=mk)
    elif prefix == "firm":
        conn = sqlite3.connect('dental.db')
        res = conn.execute("SELECT debt FROM firms WHERE name=?", (name,)).fetchone()
        debt = res[0] if res else 0.0
        conn.close()
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(
            types.InlineKeyboardButton(text="💸 Оплатить фирме (уменьшить долг)", callback_data=f"op_firmpay_{name}"),
            types.InlineKeyboardButton(text="📦 Взяли в долг (увеличить долг)", callback_data=f"op_firmadd_{name}")
        )
        bot.edit_message_text(f"🏢 *{name}*\nНаш долг фирме: `{debt:,.2f} {CURRENCY}`", cid, mid, parse_mode="Markdown", reply_markup=mk)
    else:
        cat = f"💉 Расходники ({name})" if prefix == "cstaff" else f"⚙️ {name}"
        user_state[c.from_user.id] = {'act': 'exp', 'cat': cat}
        bot.edit_message_text(f"Выбрано: *{cat}*", cid, mid, parse_mode="Markdown")
        msg = bot.send_message(cid, f"💰 Сумма ({CURRENCY}):")
        bot.register_next_step_handler(msg, step_amount)

@bot.callback_query_handler(func=lambda c: c.data.startswith('op_'))
def op_selected(c):
    _, op, name = c.data.split('_', 2)
    user_state[c.from_user.id] = {'act': op, 'target': name}
    bot.edit_message_text(f"Операция для *{name}*", c.message.chat.id, c.message.message_id, parse_mode="Markdown")
    msg = bot.send_message(c.message.chat.id, f"💰 Введите сумму ({CURRENCY}):")
    bot.register_next_step_handler(msg, step_amount)

def step_amount(m):
    try:
        amt = float(m.text.replace(',', '.'))
        if amt <= 0:
            raise ValueError
        user_state[m.from_user.id]['amt'] = amt
        msg = bot.send_message(m.chat.id, "📝 Комментарий (или `-`):")
        bot.register_next_step_handler(msg, finish_op)
    except Exception:
        msg = bot.send_message(m.chat.id, "⚠️ Введите число:")
        bot.register_next_step_handler(msg, step_amount)

def finish_op(m):
    uid = m.from_user.id
    st = user_state.get(uid)
    if not st:
        return
    comm = m.text if m.text != '-' else ''
    amt, act = st['amt'], st['act']
    dt = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect('dental.db')
    c = conn.cursor()

    if act == 'exp':
        c.execute("INSERT INTO expenses (date, category, amount, comment) VALUES (?, ?, ?, ?)", (dt, st['cat'], amt, comm))
        res_text = f"✅ Расход записан: *{st['cat']}* — `{amt:,.2f} {CURRENCY}`"
    elif act == 'empsal':
        target = st['target']
        c.execute("INSERT INTO expenses (date, category, amount, comment) VALUES (?, ?, ?, ?)", (dt, f"💵 Зарплата ({target})", amt, comm))
        res_text = f"✅ Выдана зарплата (*{target}*): `{amt:,.2f} {CURRENCY}`"
    elif act == 'empadd':
        target = st['target']
        c.execute("UPDATE employees SET debt = debt + ? WHERE name = ?", (amt, target))
        c.execute("INSERT INTO expenses (date, category, amount, comment) VALUES (?, ?, ?, ?)", (dt, f"💳 Выдано в долг ({target})", amt, comm))
        res_text = f"✅ Выдано в долг (*{target}*): `{amt:,.2f} {CURRENCY}`"
    elif act == 'emppay':
        target = st['target']
        c.execute("UPDATE employees SET debt = MAX(0, debt - ?) WHERE name = ?", (amt, target))
        res_text = f"✅ Долг сотрудника (*{target}*) уменьшен на `{amt:,.2f} {CURRENCY}`"
    elif act == 'firmpay':
        target = st['target']
        c.execute("UPDATE firms SET debt = MAX(0, debt - ?) WHERE name = ?", (amt, target))
        c.execute("INSERT INTO expenses (date, category, amount, comment) VALUES (?, ?, ?, ?)", (dt, f"🏢 Оплата фирме ({target})", amt, comm))
        res_text = f"✅ Оплачено фирме (*{target}*): `{amt:,.2f} {CURRENCY}`"
    elif act == 'firmadd':
        target = st['target']
        c.execute("UPDATE firms SET debt = debt + ? WHERE name = ?", (amt, target))
res_text = f"✅ Записан долг фирме ({target}): {amt:,.2f} {CURRENCY}"
conn.commit()
conn.close()
user_state.pop(uid, None)
bot.send_message(m.chat.id, res_text, parse_mode="Markdown", reply_markup=main_menu())
@bot.message_handler(func=lambda m: m.text == "📊 Отчет за неделю")
def weekly_report(m):
init_db()
week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
conn = sqlite3.connect('dental.db')
rows = conn.execute("SELECT category, SUM(amount) FROM expenses WHERE date >= ? GROUP BY category", (week_ago,)).fetchall()
conn.close()
if not rows:
bot.send_message(m.chat.id, "📊 За последние 7 дней расходов не было.")
return
total = sum(r[1] for r in rows)
lines = ["📊 Расходы за последние 7 дней:\n"]
for cat, s in rows:
lines.append(f"• {cat}: {s:,.2f} {CURRENCY}")
lines.append(f"\n💰 Итого: {total:,.2f} {CURRENCY} (Лимит: {WEEKLY_LIMIT} {CURRENCY})")
if total > WEEKLY_LIMIT:
lines.append("⚠️ Внимание: превышен недельный лимит!")
bot.send_message(m.chat.id, "\n".join(lines), parse_mode="Markdown")
@bot.message_handler(func=lambda m: m.text == "💳 Баланс долгов")
def debt_balance(m):
init_db()
conn = sqlite3.connect('dental.db')
emps = conn.execute("SELECT name, debt FROM employees WHERE debt > 0").fetchall()
firms = conn.execute("SELECT name, debt FROM firms WHERE debt > 0").fetchall()
conn.close()
lines = ["💳 Текущий баланс долгов:\n"]
lines.append("👤 Долги сотрудников клинике:")
if emps:
for name, d in emps:
lines.append(f"• {name}: {d:,.2f} {CURRENCY}")
else:
lines.append("— Нет долгов")
lines.append("\n🏢 Наши долги фирмам:")
if firms:
for name, d in firms:
lines.append(f"• {name}: {d:,.2f} {CURRENCY}")
else:
lines.append("— Нет долгов")
bot.send_message(m.chat.id, "\n".join(lines), parse_mode="Markdown")
app = Flask(name)
@app.route('/')
def home():
return "Dental Bot is running!"
def run_flask():
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
if name == 'main':
init_db()
threading.Thread(target=run_flask, daemon=True).start()
bot.remove_webhook()
bot.infinity_polling(skip_pending=True)
