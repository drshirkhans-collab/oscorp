import os
import csv
import io
import sqlite3
import threading
from datetime import datetime, timedelta
from flask import Flask
import telebot
from telebot import types

TOKEN = os.getenv("BOT_TOKEN")
CUR = "₼"
DB = "oscorp.db"

CATS = {
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
state = {}

def db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS exp (id INTEGER PRIMARY KEY, dt TEXT, cat TEXT, amt REAL, comm TEXT, op_type TEXT, target TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS emp (id INTEGER PRIMARY KEY, name TEXT UNIQUE, debt REAL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS firm (id INTEGER PRIMARY KEY, name TEXT UNIQUE, debt REAL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS cstaff (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS misc (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS cfg (k TEXT PRIMARY KEY, v TEXT)')
    c.execute("INSERT OR IGNORE INTO cfg (k, v) VALUES ('limit', '5000')")
    try:
        c.execute("ALTER TABLE exp ADD COLUMN op_type TEXT DEFAULT 'exp'")
        c.execute("ALTER TABLE exp ADD COLUMN target TEXT DEFAULT ''")
    except Exception:
        pass
    conn.commit()
    return conn

def get_limit():
    conn = db()
    res = conn.execute("SELECT v FROM cfg WHERE k='limit'").fetchone()
    conn.close()
    (val,) = res if res else ('5000',)
    return float(val)
def menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("➕ Добавить операцию")
    m.row("📊 Отчеты и аналитика", "💳 Баланс долгов")
    m.row("↩️ Отменить последнюю", "⚙️ Управление и Excel")
    return m

def cancel_kb():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("❌ Отмена")
    return m

def is_cancel(m):
    if not m.text:
        return False
    btns = ("❌ Отмена", "/start", "➕ Добавить операцию", "📊 Отчеты и аналитика", "💳 Баланс долгов", "↩️ Отменить последнюю", "⚙️ Управление и Excel")
    return m.text.strip() in btns

@bot.message_handler(commands=['start'])
def start(m):
    state.pop(m.from_user.id, None)
    db().close()
    bot.send_message(m.chat.id, "🏥 *Oscorp — Умный финансовый учет*\nВыберите нужное действие в меню:", parse_mode="Markdown", reply_markup=menu())

@bot.message_handler(func=lambda m: m.text == "❌ Отмена")
def cancel_btn(m):
    state.pop(m.from_user.id, None)
    bot.send_message(m.chat.id, "❌ Действие отменено.", reply_markup=menu())

def build_cats_kb():
    mk = types.InlineKeyboardMarkup(row_width=1)
    for k, v in CATS.items():
        mk.add(types.InlineKeyboardButton(f"{v} {k}", callback_data=f"cat_{k}"))
    return mk

@bot.message_handler(func=lambda m: m.text == "➕ Добавить операцию")
def choose_cat(m):
    bot.send_message(m.chat.id, "📊 *Выберите раздел расходов или операций:*", parse_mode="Markdown", reply_markup=build_cats_kb())

@bot.callback_query_handler(func=lambda c: c.data == 'back_cats')
def back_to_cats(c):
    bot.edit_message_text("📊 *Выберите раздел расходов или операций:*", c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=build_cats_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith('cat_'))
def cat_sel(c):
    _, _, cat = c.data.partition('cat_')
    cid, mid = c.message.chat.id, c.message.message_id
    if cat == "Зарплаты сотрудников":
        show_debt_list(cid, mid, "emp", "💵 *Сотрудники (зарплаты и долги):*")
    elif cat == "Расходы на фирму":
        show_debt_list(cid, mid, "firm", "🏢 *Фирмы и поставщики:*")
    elif cat == "Расходники (салфетки)":
        show_simple(cid, mid, "cstaff", "💉 *Расходники (выберите сотрудника или общие):*")
    elif cat == "Прочие расходы":
        show_simple(cid, mid, "misc", "⚙️ *Прочие расходы (выберите ячейку):*")
    else:
        fn = f"{CATS.get(cat, '')} {cat}".strip()
        state[c.from_user.id] = {'act': 'exp', 'cat': fn}
        bot.edit_message_text(f"Выбран раздел: *{fn}*", cid, mid, parse_mode="Markdown")
        msg = bot.send_message(cid, f"💰 Введите сумму ({CUR}):", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, step_amt)
def show_debt_list(cid, mid, tbl, title):
    conn = db()
    rows = conn.execute(f"SELECT name, debt FROM {tbl} ORDER BY name").fetchall()
    conn.close()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for n, d in rows:
        inf = f" • Долг: {d:,.0f} {CUR}" if d > 0 else ""
        mk.add(types.InlineKeyboardButton(f"🔹 {n}{inf}", callback_data=f"{tbl}_sel_{n}"))
    mk.add(types.InlineKeyboardButton("➕ Добавить новое имя", callback_data=f"{tbl}_add"))
    mk.add(types.InlineKeyboardButton("⬅️ Назад к разделам", callback_data="back_cats"))
    bot.edit_message_text(title, cid, mid, parse_mode="Markdown", reply_markup=mk)

def show_simple(cid, mid, tbl, title):
    conn = db()
    rows = conn.execute(f"SELECT name FROM {tbl} ORDER BY name").fetchall()
    conn.close()
    mk = types.InlineKeyboardMarkup(row_width=1)
    for (item_name,) in rows:
        mk.add(types.InlineKeyboardButton(f"📌 {item_name}", callback_data=f"{tbl}_sel_{item_name}"))
    if tbl == "cstaff":
        mk.add(types.InlineKeyboardButton("🏥 Общие на клинику", callback_data="cstaff_sel_Общие"))
    mk.add(types.InlineKeyboardButton("➕ Добавить ячейку / имя", callback_data=f"{tbl}_add"))
    mk.add(types.InlineKeyboardButton("⬅️ Назад к разделам", callback_data="back_cats"))
    bot.edit_message_text(title, cid, mid, parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.endswith('_add'))
def ask_add(c):
    tbl, _, _ = c.data.partition('_')
    bot.edit_message_text("✍️ Добавление новой записи...", c.message.chat.id, c.message.message_id)
    msg = bot.send_message(c.message.chat.id, "Введите название или имя:", reply_markup=cancel_kb())
    bot.register_next_step_handler(msg, save_add, tbl)

def save_add(m, tbl):
    if is_cancel(m):
        return bot.send_message(m.chat.id, "❌ Отменено.", reply_markup=menu())
    name = m.text.strip()
    conn = db()
    try:
        conn.execute(f"INSERT INTO {tbl} (name) VALUES (?)", (name,))
        conn.commit()
    except Exception:
        pass
    conn.close()
    bot.send_message(m.chat.id, f"✅ *{name}* добавлено в список! Нажмите «➕ Добавить операцию».", parse_mode="Markdown", reply_markup=menu())

@bot.callback_query_handler(func=lambda c: '_sel_' in c.data)
def item_sel(c):
    tbl, _, name = c.data.partition('_sel_')
    cid, mid = c.message.chat.id, c.message.message_id
    if tbl in ("emp", "firm"):
        conn = db()
        res = conn.execute(f"SELECT debt FROM {tbl} WHERE name=?", (name,)).fetchone()
        (debt,) = res if res else (0.0,)
        conn.close()
        mk = types.InlineKeyboardMarkup(row_width=1)
        if tbl == "emp":
            mk.add(
                types.InlineKeyboardButton("💵 Выдать Зарплату", callback_data=f"op_empsal_{name}"),
                types.InlineKeyboardButton("💳 Выдать в Долг (аванс)", callback_data=f"op_empadd_{name}"),
                types.InlineKeyboardButton("📉 Вернул / Списать долг", callback_data=f"op_emppay_{name}"),
                types.InlineKeyboardButton("📜 История по сотруднику", callback_data=f"hist_{name}"),
                types.InlineKeyboardButton("⬅️ Назад к списку", callback_data="cat_Зарплаты сотрудников")
            )
            txt = f"👤 *{name}*\nТекущий долг клинике: `{debt:,.2f} {CUR}`"
        else:
            mk.add(
                types.InlineKeyboardButton("💸 Оплатить фирме (уменьшить долг)", callback_data=f"op_firmpay_{name}"),
                types.InlineKeyboardButton("📦 Взяли в долг (увеличить долг)", callback_data=f"op_firmadd_{name}"),
                types.InlineKeyboardButton("📜 История по фирме", callback_data=f"hist_{name}"),
                types.InlineKeyboardButton("⬅️ Назад к списку", callback_data="cat_Расходы на фирму")
            )
            txt = f"🏢 *{name}*\nНаш долг фирме: `{debt:,.2f} {CUR}`"
        bot.edit_message_text(txt, cid, mid, parse_mode="Markdown", reply_markup=mk)
    else:
        cat = f"💉 Расходники ({name})" if tbl == "cstaff" else f"⚙️ {name}"
        state[c.from_user.id] = {'act': 'exp', 'cat': cat}
        bot.edit_message_text(f"Выбрано: *{cat}*", cid, mid, parse_mode="Markdown")
        msg = bot.send_message(cid, f"💰 Введите сумму ({CUR}):", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, step_amt)
@bot.callback_query_handler(func=lambda c: c.data.startswith('hist_'))
def show_target_hist(c):
    _, _, name = c.data.partition('hist_')
    conn = db()
    rows = conn.execute("SELECT dt, cat, amt, comm FROM exp WHERE target=? ORDER BY id DESC LIMIT 10", (name,)).fetchall()
    conn.close()
    if not rows:
        return bot.answer_callback_query(c.id, f"По «{name}» еще нет записей", show_alert=True)
    lines = [f"📜 *Последние операции ({name}):*\n"]
    for dt, cat, amt, comm in rows:
        cm = f" ({comm})" if comm else ""
        lines.append(f"• `{dt}` | {cat}: `{amt:,.2f} {CUR}`{cm}")
    bot.send_message(c.message.chat.id, "\n".join(lines), parse_mode="Markdown")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('op_'))
def op_sel(c):
    _, op, name = c.data.split('_', 2)
    state[c.from_user.id] = {'act': op, 'target': name}
    bot.edit_message_text(f"Операция для: *{name}*", c.message.chat.id, c.message.message_id, parse_mode="Markdown")
    msg = bot.send_message(c.message.chat.id, f"💰 Введите сумму ({CUR}):", reply_markup=cancel_kb())
    bot.register_next_step_handler(msg, step_amt)

def step_amt(m):
    if is_cancel(m):
        state.pop(m.from_user.id, None)
        return bot.send_message(m.chat.id, "❌ Ввод отменен.", reply_markup=menu())
    try:
        amt = float(m.text.replace(',', '.'))
        if amt <= 0:
            raise ValueError
        state[m.from_user.id]['amt'] = amt
        msg = bot.send_message(m.chat.id, "📝 Введите комментарий (или отправьте `-` без комментария):", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, finish_op)
    except Exception:
        msg = bot.send_message(m.chat.id, "⚠️ Введите корректное число или нажмите «❌ Отмена»:", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, step_amt)

def finish_op(m):
    if is_cancel(m):
        state.pop(m.from_user.id, None)
        return bot.send_message(m.chat.id, "❌ Операция отменена.", reply_markup=menu())
    st = state.pop(m.from_user.id, None)
    if not st:
        return
    comm = m.text.strip() if m.text.strip() != '-' else ''
    amt, act, dt = st['amt'], st['act'], datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = db()
    c = conn.cursor()
    t = st.get('target', '')

    if act == 'exp':
        c.execute("INSERT INTO exp (dt, cat, amt, comm, op_type, target) VALUES (?,?,?,?,?,?)", (dt, st['cat'], amt, comm, 'exp', ''))
        res = f"✅ Расход записан:\n*{st['cat']}* — `{amt:,.2f} {CUR}`"
    elif act == 'empsal':
        c.execute("INSERT INTO exp (dt, cat, amt, comm, op_type, target) VALUES (?,?,?,?,?,?)", (dt, f"💵 Зарплата ({t})", amt, comm, 'empsal', t))
        res = f"✅ Выдана зарплата:\n*{t}* — `{amt:,.2f} {CUR}`"
    elif act == 'empadd':
        c.execute("UPDATE emp SET debt = debt + ? WHERE name=?", (amt, t))
        c.execute("INSERT INTO exp (dt, cat, amt, comm, op_type, target) VALUES (?,?,?,?,?,?)", (dt, f"💳 Выдано в долг ({t})", amt, comm, 'empadd', t))
        res = f"✅ Выдано в долг:\n*{t}* — `{amt:,.2f} {CUR}`"
    elif act == 'emppay':
        c.execute("UPDATE emp SET debt = MAX(0, debt - ?) WHERE name=?", (amt, t))
        c.execute("INSERT INTO exp (dt, cat, amt, comm, op_type, target) VALUES (?,?,?,?,?,?)", (dt, f"📉 Возврат долга ({t})", amt, comm, 'emppay', t))
        res = f"✅ Долг сотрудника (*{t}*) уменьшен на `{amt:,.2f} {CUR}`"
    elif act == 'firmpay':
        c.execute("UPDATE firm SET debt = MAX(0, debt - ?) WHERE name=?", (amt, t))
        c.execute("INSERT INTO exp (dt, cat, amt, comm, op_type, target) VALUES (?,?,?,?,?,?)", (dt, f"🏢 Оплата фирме ({t})", amt, comm, 'firmpay', t))
        res = f"✅ Оплачено фирме (*{t}*): `{amt:,.2f} {CUR}`"
    elif act == 'firmadd':
        c.execute("UPDATE firm SET debt = debt + ? WHERE name=?", (amt, t))
        c.execute("INSERT INTO exp (dt, cat, amt, comm, op_type, target) VALUES (?,?,?,?,?,?)", (dt, f"📦 Взяли в долг ({t})", amt, comm, 'firmadd', t))
        res = f"✅ Записан долг фирме (*{t}*): `{amt:,.2f} {CUR}`"

    conn.commit()
    conn.close()
    if comm:
        res += f"\n📝 _{comm}_"
    bot.send_message(m.chat.id, res, parse_mode="Markdown", reply_markup=menu())
@bot.message_handler(func=lambda m: m.text == "↩️ Отменить последнюю")
def undo_last(m):
    conn = db()
    c = conn.cursor()
    row = c.execute("SELECT id, cat, amt, op_type, target FROM exp ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        conn.close()
        return bot.send_message(m.chat.id, "⚠️ Нет операций для отмены.", reply_markup=menu())
    rid, cat, amt, op, t = row
    if op == 'empadd':
        c.execute("UPDATE emp SET debt = MAX(0, debt - ?) WHERE name=?", (amt, t))
    elif op == 'emppay':
        c.execute("UPDATE emp SET debt = debt + ? WHERE name=?", (amt, t))
    elif op == 'firmpay':
        c.execute("UPDATE firm SET debt = debt + ? WHERE name=?", (amt, t))
    elif op == 'firmadd':
        c.execute("UPDATE firm SET debt = MAX(0, debt - ?) WHERE name=?", (amt, t))
    c.execute("DELETE FROM exp WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    bot.send_message(m.chat.id, f"🗑 *Операция отменена (баланс восстановлен):*\n{cat} — `{amt:,.2f} {CUR}`", parse_mode="Markdown", reply_markup=menu())

@bot.message_handler(func=lambda m: m.text == "📊 Отчеты и аналитика")
def reports_menu(m):
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("📅 За сегодня (детально)", callback_data="rep_day"),
        types.InlineKeyboardButton("📆 За последние 7 дней", callback_data="rep_week"),
        types.InlineKeyboardButton("🗓 За текущий месяц", callback_data="rep_month")
    )
    bot.send_message(m.chat.id, "📊 *Выберите период отчета:*", parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith('rep_'))
def send_report(c):
    _, _, period = c.data.partition('rep_')
    now = datetime.now()
    conn = db()
    if period == 'day':
        start_dt = now.strftime("%Y-%m-%d 00:00")
        rows = conn.execute("SELECT dt, cat, amt, comm, op_type FROM exp WHERE dt >= ? ORDER BY id DESC", (start_dt,)).fetchall()
        conn.close()
        if not rows:
            return bot.edit_message_text("📅 За сегодня операций еще не было.", c.message.chat.id, c.message.message_id)
        lines = ["📅 *Операции за сегодня:*\n"]
        tot = 0.0
        for dt, cat, amt, comm, op in rows:
            _, _, tm = dt.partition(' ')
            tm = tm if tm else dt
            cm = f" ({comm})" if comm else ""
            lines.append(f"• `{tm}` {cat}: `{amt:,.2f} {CUR}`{cm}")
            if op not in ('emppay', 'firmadd'):
                tot += amt
        lines.append(f"\n💰 *Фактический расход за день:* `{tot:,.2f} {CUR}`")
        bot.edit_message_text("\n".join(lines), c.message.chat.id, c.message.message_id, parse_mode="Markdown")
    else:
        days = 7 if period == 'week' else 30
        title = "📆 *Сводка за последние 7 дней:*" if period == 'week' else "🗓 *Сводка за 30 дней:*"
        start_dt = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        rows = conn.execute("SELECT cat, SUM(amt) FROM exp WHERE dt >= ? AND op_type NOT IN ('emppay', 'firmadd') GROUP BY cat ORDER BY SUM(amt) DESC", (start_dt,)).fetchall()
        conn.close()
        if not rows:
            return bot.edit_message_text("За выбранный период расходов не было.", c.message.chat.id, c.message.message_id)
        tot = sum(s for _, s in rows)
        lim = get_limit()
        txt = "\n".join([f"• {cat}: `{s:,.2f} {CUR}`" for cat, s in rows])
        extra = f" (Лимит: `{lim:,.0f} {CUR}`)" if period == 'week' else ""
        warn = "\n⚠️ *Внимание: превышен недельный лимит!*" if (period == 'week' and tot > lim) else ""
        bot.edit_message_text(f"{title}\n\n{txt}\n\n💰 *Итого расходов:* `{tot:,.2f} {CUR}`{extra}{warn}", c.message.chat.id, c.message.message_id, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "💳 Баланс долгов")
def debts(m):
    conn = db()
    emps = conn.execute("SELECT name, debt FROM emp WHERE debt > 0 ORDER BY debt DESC").fetchall()
    firms = conn.execute("SELECT name, debt FROM firm WHERE debt > 0 ORDER BY debt DESC").fetchall()
    conn.close()
    tot_e = sum(d for _, d in emps)
    tot_f = sum(d for _, d in firms)
    e_txt = "\n".join([f"• {n}: `{d:,.2f} {CUR}`" for n, d in emps]) if emps else "— Нет долгов"
    f_txt = "\n".join([f"• {n}: `{d:,.2f} {CUR}`" for n, d in firms]) if firms else "— Нет долгов"
    bot.send_message(
        m.chat.id,
        f"💳 *Текущий баланс долгов:*\n\n👤 *Сотрудники должны клинике* (Всего: `{tot_e:,.2f} {CUR}`):\n{e_txt}\n\n🏢 *Клиника должна фирмам* (Всего: `{tot_f:,.2f} {CUR}`):\n{f_txt}",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: m.text == "⚙️ Управление и Excel")
def settings_menu(m):
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("📥 Скачать таблицу всех операций (CSV/Excel)", callback_data="cfg_export"),
        types.InlineKeyboardButton(f"🎯 Изменить недельный лимит (сейчас {get_limit():,.0f} {CUR})", callback_data="cfg_limit"),
        types.InlineKeyboardButton("🗑 Удалить сотрудника / фирму / ячейку", callback_data="cfg_delmenu")
    )
    bot.send_message(m.chat.id, "⚙️ *Настройки и экспорт данных:*", parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == 'cfg_export')
def export_csv(c):
    conn = db()
    rows = conn.execute("SELECT id, dt, cat, amt, comm FROM exp ORDER BY id DESC").fetchall()
    conn.close()
    if not rows:
        return bot.answer_callback_query(c.id, "База данных пока пуста", show_alert=True)
    buf = io.StringIO()
    buf.write('\ufeff')
    w = csv.writer(buf, delimiter=';')
    w.writerow(["ID", "Дата и время", "Категория / Операция", f"Сумма ({CUR})", "Комментарий"])
    for r in rows:
        w.writerow(r)
    bio = io.BytesIO(buf.getvalue().encode('utf-8'))
    bio.name = f"oscorp_finance_{datetime.now().strftime('%Y-%m-%d')}.csv"
    bot.send_document(c.message.chat.id, bio, caption="📊 Выгрузка всех финансовых операций **Oscorp** (открывается в Excel).", parse_mode="Markdown")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data == 'cfg_limit')
def ask_limit(c):
    msg = bot.send_message(c.message.chat.id, f"🎯 Введите новый недельный лимит ({CUR}):", reply_markup=cancel_kb())
    bot.register_next_step_handler(msg, save_limit)
    bot.answer_callback_query(c.id)

def save_limit(m):
    if is_cancel(m):
        return bot.send_message(m.chat.id, "❌ Отменено.", reply_markup=menu())
    try:
        val = float(m.text.replace(',', '.'))
        if val <= 0:
            raise ValueError
        conn = db()
        conn.execute("UPDATE cfg SET v=? WHERE k='limit'", (str(val),))
        conn.commit()
        conn.close()
        bot.send_message(m.chat.id, f"✅ Новый недельный лимит: `{val:,.0f} {CUR}`", parse_mode="Markdown", reply_markup=menu())
    except Exception:
        msg = bot.send_message(m.chat.id, "⚠️ Введите число:", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, save_limit)

@bot.callback_query_handler(func=lambda c: c.data == 'cfg_delmenu')
def del_menu(c):
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton("👤 Удалить сотрудника", callback_data="deltbl_emp"),
        types.InlineKeyboardButton("🏢 Удалить фирму", callback_data="deltbl_firm"),
        types.InlineKeyboardButton("💉 Удалить из расходников", callback_data="deltbl_cstaff"),
        types.InlineKeyboardButton("⚙️ Удалить ячейку из прочих", callback_data="deltbl_misc")
    )
    bot.edit_message_text("🗑 *Откуда удалить запись?*", c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith('deltbl_'))
def del_list(c):
    _, _, tbl = c.data.partition('deltbl_')
    conn = db()
    rows = conn.execute(f"SELECT id, name FROM {tbl} ORDER BY name").fetchall()
    conn.close()
    if not rows:
        return bot.answer_callback_query(c.id, "Список пуст", show_alert=True)
    mk = types.InlineKeyboardMarkup(row_width=1)
    for rid, name in rows:
        mk.add(types.InlineKeyboardButton(f"❌ {name}", callback_data=f"rm_{tbl}_{rid}"))
    bot.edit_message_text("Нажмите на имя для удаления из списка:", c.message.chat.id, c.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith('rm_'))
def remove_item(c):
    _, tbl, rid = c.data.split('_', 2)
    conn = db()
    conn.execute(f"DELETE FROM {tbl} WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    bot.edit_message_text("✅ Запись удалена из списка.", c.message.chat.id, c.message.message_id)

app = Flask(__name__)

@app.route('/')
def home():
    return "Oscorp Bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == '__main__':
    db().close()
    threading.Thread(target=run_web, daemon=True).start()
    print("Проверяем токен и подключаемся к Telegram...", flush=True)
    if not TOKEN:
        print("ОШИБКА: Переменная BOT_TOKEN пустая!", flush=True)
    else:
        try:
            me = bot.get_me()
            print(f"УСПЕХ! Бот подключен: @{me.username}", flush=True)
            bot.remove_webhook()
            bot.infinity_polling(skip_pending=True)
        except Exception as e:
            print(f"ОШИБКА TELEGRAM: {e}", flush=True)
