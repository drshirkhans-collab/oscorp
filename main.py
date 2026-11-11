import os, sqlite3, threading
from datetime import datetime, timedelta
from flask import Flask
import telebot
from telebot import types

TOKEN = os.getenv("BOT_TOKEN")
CUR = "₼"
LIMIT = 5000
DB = "oscorp.db"

CATS = {
    "Зарплаты сотрудников": "💵", "Расходы на фирму": "🏢",
    "Расходники (салфетки)": "💉", "Аренда": "🔑",
    "Пломбы": "💎", "Стомат. материалы": "🩺",
    "Мобильные расходы": "📱", "Прочие расходы": "⚙️"
}

bot = telebot.TeleBot(TOKEN)
state = {}

def db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS exp (id INTEGER PRIMARY KEY, dt TEXT, cat TEXT, amt REAL, comm TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS emp (id INTEGER PRIMARY KEY, name TEXT UNIQUE, debt REAL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS firm (id INTEGER PRIMARY KEY, name TEXT UNIQUE, debt REAL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS cstaff (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS misc (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    conn.commit()
    return conn

def menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("➕ Добавить расход / Операцию")
    m.row("📊 Отчет за неделю", "💳 Баланс долгов")
    return m

@bot.message_handler(commands=['start'])
def start(m):
    db().close()
    bot.send_message(m.chat.id, "🏥 *Oscorp — Финансовый учет*\nВыберите действие:", parse_mode="Markdown", reply_markup=menu())

@bot.message_handler(func=lambda m: m.text == "➕ Добавить расход / Операцию")
def choose_cat(m):
    mk = types.InlineKeyboardMarkup(row_width=1)
    for k, v in CATS.items():
        mk.add(types.InlineKeyboardButton(f"{v} {k}", callback_data=f"cat_{k}"))
    bot.send_message(m.chat.id, "📊 Выберите раздел:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cat_'))
def cat_sel(c):
    cat = c.data[4:]
    cid, mid = c.message.chat.id, c.message.message_id
    if cat == "Зарплаты сотрудников":
        show_debt_list(cid, mid, "emp", "💵 *Зарплаты и долги:*")
    elif cat == "Расходы на фирму":
        show_debt_list(cid, mid, "firm", "🏢 *Фирмы и долги:*")
    elif cat == "Расходники (салфетки)":
        show_simple(cid, mid, "cstaff", "💉 *Расходники:*")
    elif cat == "Прочие расходы":
        show_simple(cid, mid, "misc", "⚙️ *Прочие расходы:*")
    else:
        fn = f"{CATS.get(cat, '')} {cat}".strip()
        state[c.from_user.id] = {'act': 'exp', 'cat': fn}
        bot.edit_message_text(f"Выбрано: *{fn}*", cid, mid, parse_mode="Markdown")
        msg = bot.send_message(cid, f"💰 Сумма ({CUR}):")
        bot.register_next_step_handler(msg, step_amt)

def show_debt_list(cid, mid, tbl, title):
    conn = db()
    rows = conn.execute(f"SELECT name, debt FROM {tbl} ORDER BY name").fetchall()
    conn.close()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for n, d in rows:
        inf = f" (Долг: {d:,.0f} {CUR})" if d > 0 else ""
        mk.add(types.InlineKeyboardButton(f"🔹 {n}{inf}", callback_data=f"{tbl}_sel_{n}"))
    mk.add(types.InlineKeyboardButton("➕ Добавить имя", callback_data=f"{tbl}_add"))
    bot.edit_message_text(title, cid, mid, parse_mode="Markdown", reply_markup=mk)

def show_simple(cid, mid, tbl, title):
    conn = db()
    rows = conn.execute(f"SELECT name FROM {tbl} ORDER BY name").fetchall()
    conn.close()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        mk.add(types.InlineKeyboardButton(f"📌 {r}", callback_data=f"{tbl}_sel_{r}"))
    mk.add(types.InlineKeyboardButton("➕ Добавить ячейку / имя", callback_data=f"{tbl}_add"))
    if tbl == "cstaff":
        mk.add(types.InlineKeyboardButton("🏥 Общие на клинику", callback_data="cstaff_sel_Общие"))
    bot.edit_message_text(title, cid, mid, parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.endswith('_add'))
def ask_add(c):
    tbl = c.data.split('_')
    bot.edit_message_text("✍️ Введите название / имя:", c.message.chat.id, c.message.message_id)
    bot.register_next_step_handler(c.message, save_add, tbl)

def save_add(m, tbl):
    name = m.text.strip()
    if not name or name.startswith(("➕", "📊", "💳")):
        return bot.send_message(m.chat.id, "⚠️ Отменено.", reply_markup=menu())
    conn = db()
    try:
        conn.execute(f"INSERT INTO {tbl} (name) VALUES (?)", (name,))
        conn.commit()
    except Exception:
        pass
    conn.close()
    bot.send_message(m.chat.id, f"✅ *{name}* добавлено!", parse_mode="Markdown", reply_markup=menu())

@bot.callback_query_handler(func=lambda c: '_sel_' in c.data)
def item_sel(c):
    tbl, name = c.data.split('_sel_', 1)
    cid, mid = c.message.chat.id, c.message.message_id
    if tbl in ("emp", "firm"):
        conn = db()
        res = conn.execute(f"SELECT debt FROM {tbl} WHERE name=?", (name,)).fetchone()
        debt = res if res else 0.0
        conn.close()
        mk = types.InlineKeyboardMarkup(row_width=1)
        if tbl == "emp":
            mk.add(types.InlineKeyboardButton("💵 Выдать Зарплату", callback_data=f"op_empsal_{name}"),
                   types.InlineKeyboardButton("💳 Выдать в Долг", callback_data=f"op_empadd_{name}"),
                   types.InlineKeyboardButton("📉 Вернул / Списать долг", callback_data=f"op_emppay_{name}"))
            txt = f"👤 *{name}*\nДолг клинике: `{debt:,.2f} {CUR}`"
        else:
            mk.add(types.InlineKeyboardButton("💸 Оплатить фирме (уменьшить долг)", callback_data=f"op_firmpay_{name}"),
                   types.InlineKeyboardButton("📦 Взяли в долг (увеличить долг)", callback_data=f"op_firmadd_{name}"))
            txt = f"🏢 *{name}*\nНаш долг фирме: `{debt:,.2f} {CUR}`"
        bot.edit_message_text(txt, cid, mid, parse_mode="Markdown", reply_markup=mk)
    else:
        cat = f"💉 Расходники ({name})" if tbl == "cstaff" else f"⚙️ {name}"
        state[c.from_user.id] = {'act': 'exp', 'cat': cat}
        bot.edit_message_text(f"Выбрано: *{cat}*", cid, mid, parse_mode="Markdown")
        msg = bot.send_message(cid, f"💰 Сумма ({CUR}):")
        bot.register_next_step_handler(msg, step_amt)

@bot.callback_query_handler(func=lambda c: c.data.startswith('op_'))
def op_sel(c):
    _, op, name = c.data.split('_', 2)
    state[c.from_user.id] = {'act': op, 'target': name}
    bot.edit_message_text(f"Операция для *{name}*", c.message.chat.id, c.message.message_id, parse_mode="Markdown")
    msg = bot.send_message(c.message.chat.id, f"💰 Введите сумму ({CUR}):")
    bot.register_next_step_handler(msg, step_amt)

def step_amt(m):
    try:
        amt = float(m.text.replace(',', '.'))
        if amt <= 0:
            raise ValueError
        state[m.from_user.id]['amt'] = amt
        msg = bot.send_message(m.chat.id, "📝 Комментарий (или `-`):")
        bot.register_next_step_handler(msg, finish_op)
    except Exception:
        msg = bot.send_message(m.chat.id, "⚠️ Введите число:")
        bot.register_next_step_handler(msg, step_amt)

def finish_op(m):
    st = state.pop(m.from_user.id, None)
    if not st:
        return
    comm = m.text if m.text != '-' else ''
    amt, act, dt = st['amt'], st['act'], datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = db()
    c = conn.cursor()
    t = st.get('target', '')
    if act == 'exp':
        c.execute("INSERT INTO exp (dt, cat, amt, comm) VALUES (?,?,?,?)", (dt, st['cat'], amt, comm))
        res = f"✅ Расход записан: *{st['cat']}* — `{amt:,.2f} {CUR}`"
    elif act == 'empsal':
        c.execute("INSERT INTO exp (dt, cat, amt, comm) VALUES (?,?,?,?)", (dt, f"💵 Зарплата ({t})", amt, comm))
        res = f"✅ Выдана зарплата (*{t}*): `{amt:,.2f} {CUR}`"
    elif act == 'empadd':
        c.execute("UPDATE emp SET debt = debt + ? WHERE name=?", (amt, t))
        c.execute("INSERT INTO exp (dt, cat, amt, comm) VALUES (?,?,?,?)", (dt, f"💳 Выдано в долг ({t})", amt, comm))
        res = f"✅ Выдано в долг (*{t}*): `{amt:,.2f} {CUR}`"
    elif act == 'emppay':
        c.execute("UPDATE emp SET debt = MAX(0, debt - ?) WHERE name=?", (amt, t))
        res = f"✅ Долг сотрудника (*{t}*) уменьшен на `{amt:,.2f} {CUR}`"
    elif act == 'firmpay':
        c.execute("UPDATE firm SET debt = MAX(0, debt - ?) WHERE name=?", (amt, t))
        c.execute("INSERT INTO exp (dt, cat, amt, comm) VALUES (?,?,?,?)", (dt, f"🏢 Оплата фирме ({t})", amt, comm))
        res = f"✅ Оплачено фирме (*{t}*): `{amt:,.2f} {CUR}`"
    elif act == 'firmadd':
        c.execute("UPDATE firm SET debt = debt + ? WHERE name=?", (amt, t))
        res = f"✅ Записан долг фирме (*{t}*): `{amt:,.2f} {CUR}`"
    conn.commit()
    conn.close()
    bot.send_message(m.chat.id, res, parse_mode="Markdown", reply_markup=menu())

@bot.message_handler(func=lambda m: m.text == "📊 Отчет за неделю")
def weekly(m):
    w_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    conn = db()
    rows = conn.execute("SELECT cat, SUM(amt) FROM exp WHERE dt >= ? GROUP BY cat", (w_ago,)).fetchall()
    conn.close()
    if not rows:
        return bot.send_message(m.chat.id, "📊 За последние 7 дней расходов не было.")
    tot = sum(r for r in rows)
    txt = "\n".join([f"• {cat}: `{s:,.2f} {CUR}`" for cat, s in rows])
    warn = "\n⚠️ *Превышен недельный лимит!*" if tot > LIMIT else ""
    bot.send_message(m.chat.id, f"📊 *Расходы за 7 дней:*\n\n{txt}\n\n💰 *Итого:* `{tot:,.2f} {CUR}` (Лимит: `{LIMIT} {CUR}`){warn}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "💳 Баланс долгов")
def debts(m):
    conn = db()
    emps = conn.execute("SELECT name, debt FROM emp WHERE debt > 0").fetchall()
    firms = conn.execute("SELECT name, debt FROM firm WHERE debt > 0").fetchall()
    conn.close()
    e_txt = "\n".join([f"• {n}: `{d:,.2f} {CUR}`" for n, d in emps]) if emps else "— Нет долгов"
    f_txt = "\n".join([f"• {n}: `{d:,.2f} {CUR}`" for n, d in firms]) if firms else "— Нет долгов"

bot.send_message(m.chat.id, f"💳 Баланс долгов:\n\n👤 Сотрудники клинике:\n{e_txt}\n\n🏢 Мы фирмам:\n{f_txt}", parse_mode="Markdown")
app = Flask(name)
@app.route('/')
def home():
return "Oscorp Bot is running!"
def run_web():
app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
if name == 'main':
db().close()
threading.Thread(target=run_web, daemon=True).start()
bot.remove_webhook()
bot.infinity_polling(skip_pending=True)
