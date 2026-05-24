import os
import json
import logging
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

db = Database()

# Stati conversazione
(TITOLO, PRIORITA, GRUPPO, DIFFICOLTA, SCADENZA) = range(5)
DELETE_ID = 10
DONE_ID = 11

GRUPPI = {
    "1": "⚡ Importantissime",
    "2": "💼 Lavoro",
    "3": "🗂 Progetti",
    "4": "🧘 Cura di sé",
    "5": "🎁 Gratifica personale",
    "6": "🚀 Avanzamenti"
}

def calcola_score(p, g, d, s, t):
    """
    Formula: X = ((P×100)/G + T_pesato) × D_corretto + S_bonus

    - P (1-5): priorità
    - G (1-6): gruppo (1=importantissime, valore più alto)
    - D (1-5): difficoltà, fattore smorzato
    - S: scadenza, bonus soglia
    - T: giorni di attesa, accelerato per gruppi 4/5/6
    """

    # T_pesato: gruppi morbidi (4,5,6) salgono più veloce
    if g in [4, 5, 6]:
        t_pesato = t * 1.5
    else:
        t_pesato = t * 1.0

    # Base
    base = (p * 100) / g + t_pesato

    # D_corretto: fattore smorzato intorno a 1.0
    d_map = {1: 0.9, 2: 0.95, 3: 1.0, 4: 1.05, 5: 1.1}
    d_corretto = d_map.get(d, 1.0)

    score = base * d_corretto

    # Bonus extra: alta priorità + alta difficoltà
    if p >= 4 and d >= 4:
        score += 20

    # S_bonus: override scadenza
    if s:
        oggi = date.today()
        if isinstance(s, str):
            s = date.fromisoformat(s)
        giorni = (s - oggi).days
        if giorni < 0:
            score += 300   # scaduta
        elif giorni == 0:
            score += 250   # oggi
        elif giorni == 1:
            score += 200   # domani
        elif giorni == 2:
            score += 150   # dopodomani
        elif giorni <= 7:
            score += 50    # entro la settimana

    return round(score, 1)

def urgenza_label(task):
    score = task['score']
    s = task.get('scadenza')
    if s:
        oggi = date.today()
        if isinstance(s, str):
            s = date.fromisoformat(s)
        giorni = (s - oggi).days
        if giorni < 0:
            return "🔴 SCADUTA"
        elif giorni <= 1:
            return "🔴 URGENTE"
        elif giorni <= 2:
            return "🟠 Molto urgente"
        elif giorni <= 7:
            return "🟡 In scadenza"
    if score >= 200:
        return "🔴 Alta"
    elif score >= 100:
        return "🟠 Media-alta"
    elif score >= 50:
        return "🟡 Media"
    else:
        return "🟢 Bassa"

def formatta_task(task, numero=None):
    label = urgenza_label(task)
    numero_str = f"{numero}. " if numero else ""
    return f"{numero_str}{task['titolo']} {label}"


# ─── COMANDI ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Ciao! Sono il tuo assistente task.\n\n"
        "Comandi disponibili:\n"
        "/aggiungi — Aggiungi una nuova task\n"
        "/lista — Vedi tutte le task ordinate\n"
        "/urgenti — Solo le task urgenti\n"
        "/fatto — Segna una task come completata\n"
        "/cancella — Elimina una task\n"
        "/aiuto — Mostra questo messaggio"
    )

async def aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ─── AGGIUNGI TASK ──────────────────────────────────────────

async def aggiungi_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "➕ *Nuova task*\n\nQual è il titolo della task?",
        parse_mode='Markdown'
    )
    return TITOLO

async def aggiungi_titolo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['titolo'] = update.message.text.strip()
    keyboard = [["1", "2", "3"], ["4", "5"]]
    await update.message.reply_text(
        "Priorità? (1=bassa, 5=alta)",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return PRIORITA

async def aggiungi_priorita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val not in ["1","2","3","4","5"]:
        await update.message.reply_text("Scegli un numero da 1 a 5.")
        return PRIORITA
    context.user_data['priorita'] = int(val)
    keyboard = [["1","2","3"],["4","5","6"]]
    gruppi_testo = "\n".join([f"{k}: {v}" for k, v in GRUPPI.items()])
    await update.message.reply_text(
        f"Gruppo?\n{gruppi_testo}",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return GRUPPO

async def aggiungi_gruppo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val not in ["1","2","3","4","5","6"]:
        await update.message.reply_text("Scegli un numero da 1 a 6.")
        return GRUPPO
    context.user_data['gruppo'] = int(val)
    keyboard = [["1", "2", "3"], ["4", "5"]]
    await update.message.reply_text(
        "Difficoltà? (1=facilissima, 5=molto difficile)",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return DIFFICOLTA

async def aggiungi_difficolta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if val not in ["1","2","3","4","5"]:
        await update.message.reply_text("Scegli un numero da 1 a 5.")
        return DIFFICOLTA
    context.user_data['difficolta'] = int(val)
    keyboard = [
        ["Oggi", "Domani"],
        ["2 gg", "3 gg"],
        ["7 gg", "10 gg"],
        ["Nessuna scadenza"]
    ]
    await update.message.reply_text(
        "Scadenza?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return SCADENZA


async def aggiungi_scadenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip()
    scadenza = None
    oggi = date.today()

    if testo.lower() == "oggi":
        scadenza = oggi
    elif testo.lower() == "domani":
        scadenza = oggi + timedelta(days=1)
    elif testo.lower() == "2 gg":
        scadenza = oggi + timedelta(days=2)
    elif testo.lower() == "3 gg":
        scadenza = oggi + timedelta(days=3)
    elif testo.lower() == "7 gg":
        scadenza = oggi + timedelta(days=7)
    elif testo.lower() == "10 gg":
        scadenza = oggi + timedelta(days=10)
    elif testo.lower() != "nessuna scadenza":
        try:
            scadenza = datetime.strptime(testo, "%d/%m/%Y").date()
        except ValueError:
            await update.message.reply_text("Formato non valido. Usa GG/MM/AAAA.")
            return SCADENZA

    d = context.user_data
    t = 0
    score = calcola_score(d['priorita'], d['gruppo'], d['difficolta'], scadenza, t)

    task_id = db.aggiungi_task(
        titolo=d['titolo'],
        priorita=d['priorita'],
        gruppo=d['gruppo'],
        difficolta=d['difficolta'],
        scadenza=scadenza.isoformat() if scadenza else None,
        inserimento=oggi.isoformat(),
        score=score
    )

    await update.message.reply_text(
        f"✅ Task aggiunta!\n\n"
        f"📌 {d['titolo']}\n"
        f"Score: {score} | ID: #{task_id}",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operazione annullata.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─── LISTA ──────────────────────────────────────────────────

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("📭 Nessuna task in lista.")
        return

    # Ricalcola score aggiornato
    for t in tasks:
        inserimento = date.fromisoformat(t['inserimento'])
        giorni_attesa = (date.today() - inserimento).days
        s = date.fromisoformat(t['scadenza']) if t['scadenza'] else None
        nuovo_score = calcola_score(t['priorita'], t['gruppo'], t['difficolta'], s, giorni_attesa)
        if nuovo_score != t['score']:
            db.aggiorna_score(t['id'], nuovo_score)
            t['score'] = nuovo_score

    tasks.sort(key=lambda x: x['score'], reverse=True)

   testo = f"📋 *Le tue task*\n\n"
    for i, task in enumerate(tasks, 1):
        testo += formatta_task(task, numero=i) + "\n"


    await update.message.reply_text(testo, parse_mode='Markdown')

# ─── URGENTI ────────────────────────────────────────────────

async def urgenti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    oggi = date.today()
    urgenti_list = []

    for t in tasks:
        s = date.fromisoformat(t['scadenza']) if t['scadenza'] else None
        inserimento = date.fromisoformat(t['inserimento'])
        giorni_attesa = (oggi - inserimento).days
        score = calcola_score(t['priorita'], t['gruppo'], t['difficolta'], s, giorni_attesa)
        t['score'] = score

        if s and (s - oggi).days <= 7:
            urgenti_list.append(t)
        elif score >= 150:
            urgenti_list.append(t)

    urgenti_list.sort(key=lambda x: x['score'], reverse=True)

    if not urgenti_list:
        await update.message.reply_text("✅ Nessuna task urgente al momento.")
        return

    testo = f"🚨 *Task urgenti* ({len(urgenti_list)})\n\n"
    for task in urgenti_list:
        testo += formatta_task(task) + "\n\n"

    await update.message.reply_text(testo, parse_mode='Markdown')

# ─── FATTO ──────────────────────────────────────────────────

async def fatto_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("Nessuna task da completare.")
        return ConversationHandler.END

    testo = "✅ Quale task hai completato? Scrivi il numero ID.\n\n"
    for t in tasks[:10]:
        testo += f"#{t['id']} — {t['titolo']}\n"

    await update.message.reply_text(testo, reply_markup=ReplyKeyboardRemove())
    return DONE_ID

async def fatto_esegui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip().replace("#", "")
    try:
        task_id = int(testo)
    except ValueError:
        await update.message.reply_text("Scrivi solo il numero ID.")
        return DONE_ID

    task = db.get_task_by_id(task_id)
    if not task:
        await update.message.reply_text(f"Task #{task_id} non trovata.")
        return DONE_ID

    db.completa_task(task_id)
    await update.message.reply_text(f"🎉 Task completata: {task['titolo']}")
    return ConversationHandler.END

# ─── CANCELLA ───────────────────────────────────────────────

async def cancella_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("Nessuna task da cancellare.")
        return ConversationHandler.END

    testo = "🗑 Quale task vuoi cancellare? Scrivi il numero ID.\n\n"
    for t in tasks[:10]:
        testo += f"#{t['id']} — {t['titolo']}\n"

    await update.message.reply_text(testo)
    return DELETE_ID

async def cancella_esegui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip().replace("#", "")
    try:
        task_id = int(testo)
    except ValueError:
        await update.message.reply_text("Scrivi solo il numero ID.")
        return DELETE_ID

    task = db.get_task_by_id(task_id)
    if not task:
        await update.message.reply_text(f"Task #{task_id} non trovata.")
        return DELETE_ID

    db.cancella_task(task_id)
    await update.message.reply_text(f"🗑 Task eliminata: {task['titolo']}")
    return ConversationHandler.END

# ─── NOTIFICHE PROGRAMMATE ──────────────────────────────────

async def notifica_mattina(app):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        return

    oggi = date.today()
    for t in tasks:
        s = date.fromisoformat(t['scadenza']) if t['scadenza'] else None
        inserimento = date.fromisoformat(t['inserimento'])
        giorni_attesa = (oggi - inserimento).days
        score = calcola_score(t['priorita'], t['gruppo'], t['difficolta'], s, giorni_attesa)
        t['score'] = score

    tasks.sort(key=lambda x: x['score'], reverse=True)
    top5 = tasks[:5]

    testo = f"☀️ *Buongiorno! Le tue top 5 task di oggi:*\n\n"
    for task in top5:
        testo += formatta_task(task) + "\n\n"

    chat_id = os.environ.get("CHAT_ID")
    if chat_id:
        await app.bot.send_message(chat_id=chat_id, text=testo, parse_mode='Markdown')

async def notifica_scadenze(app):
    tasks = db.get_tasks_ordinate()
    oggi = date.today()
    urgenti_list = []

    for t in tasks:
        s = t.get('scadenza')
        if s:
            s = date.fromisoformat(s)
            giorni = (s - oggi).days
            if 0 <= giorni <= 2:
                urgenti_list.append((t, giorni))

    if not urgenti_list:
        return

    testo = "⚠️ *Alert scadenze imminenti:*\n\n"
    for task, giorni in urgenti_list:
        if giorni == 0:
            quando = "OGGI"
        elif giorni == 1:
            quando = "domani"
        else:
            quando = f"tra {giorni} giorni"
        testo += f"🔴 {task['titolo']} — scade *{quando}*\n"

    chat_id = os.environ.get("CHAT_ID")
    if chat_id:
        await app.bot.send_message(chat_id=chat_id, text=testo, parse_mode='Markdown')

async def test_notifica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await notifica_mattina(context.application)
    await notifica_scadenze(context.application)

# ─── MAIN ───────────────────────────────────────────────────

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN non trovato nelle variabili d'ambiente")

    app = Application.builder().token(token).build()

    # Handler aggiungi
    conv_aggiungi = ConversationHandler(
        entry_points=[CommandHandler("aggiungi", aggiungi_start)],
        states={
            TITOLO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_titolo)],
            PRIORITA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_priorita)],
            GRUPPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_gruppo)],
            DIFFICOLTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_difficolta)],
            SCADENZA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_scadenza)],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    # Handler fatto
    conv_fatto = ConversationHandler(
        entry_points=[CommandHandler("fatto", fatto_start)],
        states={
            DONE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, fatto_esegui)],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    # Handler cancella
    conv_cancella = ConversationHandler(
        entry_points=[CommandHandler("cancella", cancella_start)],
        states={
            DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, cancella_esegui)],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test_notifica))
    app.add_handler(CommandHandler("aiuto", aiuto))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("urgenti", urgenti))
    app.add_handler(conv_aggiungi)
    app.add_handler(conv_fatto)
    app.add_handler(conv_cancella)

    # Scheduler notifiche
    scheduler = AsyncIOScheduler(timezone="Europe/Rome")
    scheduler.add_job(notifica_mattina, 'cron', hour=8, minute=0, args=[app])
    scheduler.add_job(notifica_scadenze, 'cron', hour=9, minute=0, args=[app])
    scheduler.add_job(notifica_scadenze, 'cron', hour=18, minute=0, args=[app])

    print("✅ Bot avviato!")
    app.run_polling()

if __name__ == "__main__":
    main()
