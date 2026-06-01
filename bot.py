import os
import logging
import random
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

db = Database()

# ─── STATI CONVERSAZIONE ────────────────────────────────────
(TITOLO, PRIORITA, GRUPPO, DIFFICOLTA, SCADENZA, RIPETIZIONE) = range(6)
DELETE_ID = 20
DONE_ID = 21
PIANIFICA_SCELTA = 22

GRUPPI = {
    "1": "⚡ Importantissime",
    "2": "💼 Lavoro",
    "3": "🗂 Progetti",
    "4": "🧘 Cura di sé",
    "5": "🎁 Gratifica personale",
    "6": "🚀 Avanzamenti"
}

# ─── FORMULA PRIORITÀ ───────────────────────────────────────

def calcola_score(p, g, d, s, t):
    if g in [4, 5, 6]:
        t_pesato = t * 1.5
    else:
        t_pesato = t * 1.0

    base = (p * 100) / g + t_pesato
    d_map = {1: 0.9, 2: 0.95, 3: 1.0, 4: 1.05, 5: 1.1}
    d_corretto = d_map.get(d, 1.0)
    score = base * d_corretto

    if p >= 4 and d >= 4:
        score += 20

    if s:
        oggi = date.today()
        if isinstance(s, str):
            s = date.fromisoformat(s)
        giorni = (s - oggi).days
        if giorni < 0:
            score += 300
        elif giorni == 0:
            score += 250
        elif giorni == 1:
            score += 200
        elif giorni == 2:
            score += 150
        elif giorni <= 7:
            score += 50

    return round(score, 1)

def urgenza_emoji(task):
    score = task['score']
    s = task.get('scadenza')
    if s:
        oggi = date.today()
        if isinstance(s, str):
            s = date.fromisoformat(s)
        giorni = (s - oggi).days
        if giorni < 0:
            return "🔴"
        elif giorni <= 1:
            return "🔴"
        elif giorni <= 2:
            return "🟠"
        elif giorni <= 7:
            return "🟡"
    if score >= 200:
        return "🔴"
    elif score >= 100:
        return "🟠"
    elif score >= 50:
        return "🟡"
    else:
        return "🟢"

def ricalcola_tasks(tasks):
    oggi = date.today()
    for t in tasks:
        inserimento = date.fromisoformat(t['inserimento'])
        giorni_attesa = (oggi - inserimento).days
        s = date.fromisoformat(t['scadenza']) if t['scadenza'] else None
        nuovo_score = calcola_score(t['priorita'], t['gruppo'], t['difficolta'], s, giorni_attesa)
        if nuovo_score != t['score']:
            db.aggiorna_score(t['id'], nuovo_score)
            t['score'] = nuovo_score
    tasks.sort(key=lambda x: x['score'], reverse=True)
    return tasks

def prossima_scadenza_ripetitiva(frequenza):
    oggi = date.today()
    if frequenza == "giornaliera":
        return oggi + timedelta(days=1)
    elif frequenza == "3gg":
        return oggi + timedelta(days=3)
    elif frequenza == "settimanale":
        return oggi + timedelta(days=7)
    return None

# ─── COMANDI BASE ────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Ciao! Sono il tuo assistente task.\n\n"
        "Comandi disponibili:\n"
        "/aggiungi — Aggiungi una nuova task\n"
        "/lista — Vedi tutte le task ordinate\n"
        "/urgenti — Solo le task urgenti\n"
        "/fatto — Segna una task come completata\n"
        "/cancella — Elimina una task\n"
        "/pianifica — Pianifica le task di domani\n"
        "/aiuto — Mostra questo messaggio"
    )

async def aiuto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ─── AGGIUNGI TASK ──────────────────────────────────────────

async def aggiungi_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "➕ *Nuova task*\n\nQual è il titolo?",
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

    mappa = {"oggi": 0, "domani": 1, "2 gg": 2, "3 gg": 3, "7 gg": 7, "10 gg": 10}
    testo_lower = testo.lower()

    if testo_lower in mappa:
        scadenza = oggi + timedelta(days=mappa[testo_lower])
    elif testo_lower != "nessuna scadenza":
        try:
            scadenza = datetime.strptime(testo, "%d/%m/%Y").date()
        except ValueError:
            await update.message.reply_text("Formato non valido. Usa GG/MM/AAAA.")
            return SCADENZA

    context.user_data['scadenza'] = scadenza

    keyboard = [["No"], ["Giornaliera", "Ogni 3 giorni"], ["Settimanale"]]
    await update.message.reply_text(
        "È una task ripetitiva?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return RIPETIZIONE

async def aggiungi_ripetizione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip().lower()
    mappa = {
        "no": None,
        "giornaliera": "giornaliera",
        "ogni 3 giorni": "3gg",
        "settimanale": "settimanale"
    }
    ripetizione = mappa.get(testo)

    d = context.user_data
    scadenza = d.get('scadenza')
    oggi = date.today()
    score = calcola_score(d['priorita'], d['gruppo'], d['difficolta'], scadenza, 0)

    task_id = db.aggiungi_task(
        titolo=d['titolo'],
        priorita=d['priorita'],
        gruppo=d['gruppo'],
        difficolta=d['difficolta'],
        scadenza=scadenza.isoformat() if scadenza else None,
        inserimento=oggi.isoformat(),
        score=score,
        ripetizione=ripetizione
    )

    ripetizione_str = f"\n🔄 Ripetizione: {testo}" if ripetizione else ""
    await update.message.reply_text(
        f"✅ Task aggiunta!\n📌 {d['titolo']}{ripetizione_str}",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def annulla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Annullato.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─── LISTA ──────────────────────────────────────────────────

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("📭 Nessuna task in lista.")
        return

    tasks = ricalcola_tasks(tasks)
    testo = "📋 *Le tue task*\n\n"
    for i, task in enumerate(tasks, 1):
        emoji = urgenza_emoji(task)
        rip = " 🔄" if task.get('ripetizione') else ""
        testo += f"{i}. {task['titolo']} {emoji}{rip}\n"

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
        if (s and (s - oggi).days <= 7) or score >= 150:
            urgenti_list.append(t)

    urgenti_list.sort(key=lambda x: x['score'], reverse=True)

    if not urgenti_list:
        await update.message.reply_text("✅ Nessuna task urgente.")
        return

    testo = "🚨 *Urgenti*\n\n"
    for i, task in enumerate(urgenti_list, 1):
        emoji = urgenza_emoji(task)
        testo += f"{i}. {task['titolo']} {emoji}\n"

    await update.message.reply_text(testo, parse_mode='Markdown')

# ─── FATTO ──────────────────────────────────────────────────

async def fatto_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("Nessuna task da completare.")
        return ConversationHandler.END

    testo = "✅ Quale task hai completato? Scrivi il numero.\n\n"
    for i, t in enumerate(tasks[:15], 1):
        rip = " 🔄" if t.get('ripetizione') else ""
        testo += f"{i}. {t['titolo']}{rip}\n"

    context.user_data['tasks_lista'] = tasks[:15]
    await update.message.reply_text(testo, reply_markup=ReplyKeyboardRemove())
    return DONE_ID

async def fatto_esegui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip()
    try:
        indice = int(testo) - 1
        tasks = context.user_data.get('tasks_lista', [])
        task = tasks[indice]
    except (ValueError, IndexError):
        await update.message.reply_text("Numero non valido, riprova.")
        return DONE_ID

    # Se ripetitiva, ricrea automaticamente
    if task.get('ripetizione'):
        nuova_scadenza = prossima_scadenza_ripetitiva(task['ripetizione'])
        oggi = date.today()
        score = calcola_score(task['priorita'], task['gruppo'], task['difficolta'], nuova_scadenza, 0)
        db.aggiungi_task(
            titolo=task['titolo'],
            priorita=task['priorita'],
            gruppo=task['gruppo'],
            difficolta=task['difficolta'],
            scadenza=nuova_scadenza.isoformat() if nuova_scadenza else None,
            inserimento=oggi.isoformat(),
            score=score,
            ripetizione=task['ripetizione']
        )

    db.completa_task(task['id'])
    await update.message.reply_text(f"🎉 Fatto: {task['titolo']}")
    return ConversationHandler.END

# ─── CANCELLA ───────────────────────────────────────────────

async def cancella_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("Nessuna task da cancellare.")
        return ConversationHandler.END

    testo = "🗑 Quale task vuoi cancellare? Scrivi il numero.\n\n"
    for i, t in enumerate(tasks[:15], 1):
        testo += f"{i}. {t['titolo']}\n"

    context.user_data['tasks_lista'] = tasks[:15]
    await update.message.reply_text(testo)
    return DELETE_ID

async def cancella_esegui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip()
    try:
        indice = int(testo) - 1
        tasks = context.user_data.get('tasks_lista', [])
        task = tasks[indice]
    except (ValueError, IndexError):
        await update.message.reply_text("Numero non valido, riprova.")
        return DELETE_ID

    db.cancella_task(task['id'])
    await update.message.reply_text(f"🗑 Eliminata: {task['titolo']}")
    return ConversationHandler.END

# ─── PIANIFICA DOMANI ───────────────────────────────────────

async def pianifica_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks_ordinate()
    if not tasks:
        await update.message.reply_text("Nessuna task in lista.")
        return ConversationHandler.END

    tasks = ricalcola_tasks(tasks)
    context.user_data['tasks_pianifica'] = tasks
    context.user_data['selezionate'] = []

    testo = "🌙 *Pianificazione di domani*\n\nQuali task vuoi fare domani?\nRispondi con i numeri separati da virgola (es. 1,3,5)\n\n"
    for i, t in enumerate(tasks[:20], 1):
        emoji = urgenza_emoji(t)
        testo += f"{i}. {t['titolo']} {emoji}\n"

    await update.message.reply_text(testo, parse_mode='Markdown')
    return PIANIFICA_SCELTA

async def pianifica_esegui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text.strip()
    tasks = context.user_data.get('tasks_pianifica', [])

    try:
        numeri = [int(n.strip()) - 1 for n in testo.split(",")]
        selezionate = [tasks[i]['titolo'] for i in numeri if 0 <= i < len(tasks)]
    except (ValueError, IndexError):
        await update.message.reply_text("Formato non valido. Usa numeri separati da virgola (es. 1,3,5)")
        return PIANIFICA_SCELTA

    db.salva_pianificazione(selezionate)

    testo_risposta = "✅ *Pianificazione salvata!*\n\nDomani ti ricorderò di:\n"
    for t in selezionate:
        testo_risposta += f"• {t}\n"
    testo_risposta += "\nBuona notte! 🌙"

    await update.message.reply_text(testo_risposta, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ─── CHECK-IN RIPETITIVE ────────────────────────────────────

async def checkin_risposta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    # formato: checkin_SI_123 / checkin_NO_123 / checkin_RIMANDO_123
    parti = data.split("_")
    azione = parti[1]
    task_id = int(parti[2])

    task = db.get_task_by_id(task_id)
    if not task:
        await query.edit_message_text("Task non trovata.")
        return

    if azione == "SI":
        if task.get('ripetizione'):
            nuova_scadenza = prossima_scadenza_ripetitiva(task['ripetizione'])
            oggi = date.today()
            score = calcola_score(task['priorita'], task['gruppo'], task['difficolta'], nuova_scadenza, 0)
            db.aggiungi_task(
                titolo=task['titolo'],
                priorita=task['priorita'],
                gruppo=task['gruppo'],
                difficolta=task['difficolta'],
                scadenza=nuova_scadenza.isoformat() if nuova_scadenza else None,
                inserimento=oggi.isoformat(),
                score=score,
                ripetizione=task['ripetizione']
            )
        db.completa_task(task_id)
        await query.edit_message_text(f"🎉 Ottimo! {task['titolo']} completata.")

    elif azione == "NO":
        await query.edit_message_text(f"Ok, {task['titolo']} resta in lista.")

    elif azione == "RIMANDO":
        context.job_queue.run_once(
            checkin_reminder,
            when=timedelta(hours=3),
            data={'task': task},
            chat_id=query.message.chat_id
        )
        await query.edit_message_text(f"⏰ Ti ricordo {task['titolo']} tra 3 ore.")

async def checkin_reminder(context: ContextTypes.DEFAULT_TYPE):
    task = context.job.data['task']
    chat_id = context.job.chat_id
    await invia_checkin(context.bot, chat_id, task)

async def invia_checkin(bot, chat_id, task):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sì", callback_data=f"checkin_SI_{task['id']}"),
            InlineKeyboardButton("❌ No", callback_data=f"checkin_NO_{task['id']}"),
            InlineKeyboardButton("⏰ Rimando", callback_data=f"checkin_RIMANDO_{task['id']}")
        ]
    ])
    await bot.send_message(
        chat_id=chat_id,
        text=f"🔄 Hai fatto *{task['titolo']}* oggi?",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

# ─── NOTIFICHE PROGRAMMATE ──────────────────────────────────

async def notifica_recap_mattina(app):
    tasks = db.get_tasks_ordinate()
    chat_id = os.environ.get("CHAT_ID")
    if not chat_id:
        return

    # Task pianificate ieri sera
    pianificate = db.get_pianificazione()

    testo = f"☀️ *Buongiorno! {date.today().strftime('%d/%m/%Y')}*\n\n"

    if pianificate:
        testo += "📌 *Hai pianificato queste task per oggi:*\n"
        for t in pianificate:
            testo += f"• {t}\n"
        testo += "\n"
        db.cancella_pianificazione()

    if tasks:
        tasks = ricalcola_tasks(tasks)
        testo += "📋 *Lista completa:*\n"
        for i, task in enumerate(tasks, 1):
            emoji = urgenza_emoji(task)
            rip = " 🔄" if task.get('ripetizione') else ""
            testo += f"{i}. {task['titolo']} {emoji}{rip}\n"

    await app.bot.send_message(chat_id=chat_id, text=testo, parse_mode='Markdown')

async def notifica_urgenti_periodica(app):
    tasks = db.get_tasks_ordinate()
    chat_id = os.environ.get("CHAT_ID")
    if not chat_id or not tasks:
        return

    tasks = ricalcola_tasks(tasks)
    top = [t for t in tasks if urgenza_emoji(t) == "🔴"][:2]
    if not top:
        top = tasks[:1]

    testo = "⚡ *Task urgenti ora:*\n\n"
    for t in top:
        testo += f"• {t['titolo']} {urgenza_emoji(t)}\n"

    await app.bot.send_message(chat_id=chat_id, text=testo, parse_mode='Markdown')

async def notifica_dimenticate(app):
    tasks = db.get_tasks_ordinate()
    chat_id = os.environ.get("CHAT_ID")
    if not chat_id or not tasks:
        return

    oggi = date.today()
    vecchie = []
    for t in tasks:
        inserimento = date.fromisoformat(t['inserimento'])
        giorni = (oggi - inserimento).days
        if giorni >= 14 and urgenza_emoji(t) in ["🟢", "🟡"]:
            vecchie.append((t, giorni))

    if not vecchie:
        return

    vecchie.sort(key=lambda x: x[1], reverse=True)
    t, giorni = random.choice(vecchie[:5])

    testo = f"💤 *Aspetta da {giorni} giorni...*\n\n{t['titolo']} {urgenza_emoji(t)}\n\nForse è ora di pensarci?"
    await app.bot.send_message(chat_id=chat_id, text=testo, parse_mode='Markdown')

async def notifica_pianifica_sera(app):
    chat_id = os.environ.get("CHAT_ID")
    if not chat_id:
        return

    tasks = db.get_tasks_ordinate()
    if not tasks:
        return

    tasks = ricalcola_tasks(tasks)
    testo = "🌙 *Pianifichiamo domani?*\n\nUsa /pianifica per scegliere le tue task di domani.\n\n"
    testo += "📋 *Lista aggiornata:*\n"
    for i, task in enumerate(tasks, 1):
        emoji = urgenza_emoji(task)
        testo += f"{i}. {task['titolo']} {emoji}\n"

    await app.bot.send_message(chat_id=chat_id, text=testo, parse_mode='Markdown')

async def checkin_ripetitive(app):
    tasks = db.get_tasks_ordinate()
    chat_id = os.environ.get("CHAT_ID")
    if not chat_id or not tasks:
        return

    oggi = date.today()
    for task in tasks:
        if not task.get('ripetizione'):
            continue
        s = task.get('scadenza')
        if s:
            scadenza = date.fromisoformat(s)
            if scadenza <= oggi:
                await invia_checkin(app.bot, chat_id, task)
                
async def test_notifica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await notifica_recap_mattina(context.application)
    await update.message.reply_text("✅ Test notifiche inviato!")

# ─── MAIN ───────────────────────────────────────────────────

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN non trovato nelle variabili d'ambiente")

    app = Application.builder().token(token).build()

    # Conversazioni
    conv_aggiungi = ConversationHandler(
        entry_points=[CommandHandler("aggiungi", aggiungi_start)],
        states={
            TITOLO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_titolo)],
            PRIORITA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_priorita)],
            GRUPPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_gruppo)],
            DIFFICOLTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_difficolta)],
            SCADENZA: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_scadenza)],
            RIPETIZIONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, aggiungi_ripetizione)],
        },
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    conv_fatto = ConversationHandler(
        entry_points=[CommandHandler("fatto", fatto_start)],
        states={DONE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, fatto_esegui)]},
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    conv_cancella = ConversationHandler(
        entry_points=[CommandHandler("cancella", cancella_start)],
        states={DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, cancella_esegui)]},
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    conv_pianifica = ConversationHandler(
        entry_points=[CommandHandler("pianifica", pianifica_start)],
        states={PIANIFICA_SCELTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, pianifica_esegui)]},
        fallbacks=[CommandHandler("annulla", annulla)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("aiuto", aiuto))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("urgenti", urgenti))
    app.add_handler(conv_aggiungi)
    app.add_handler(conv_fatto)
    app.add_handler(conv_cancella)
    app.add_handler(conv_pianifica)
    app.add_handler(CallbackQueryHandler(checkin_risposta, pattern="^checkin_"))
    app.add_handler(CommandHandler("test", test_notifica))

    # Scheduler
    scheduler = AsyncIOScheduler(timezone="Europe/Rome")

    # Recap mattina ore 7
    scheduler.add_job(notifica_recap_mattina, 'cron', hour=7, minute=0, args=[app])

    # Urgenti ogni 4 ore (9, 13, 17, 21)
    for ora in [9, 13, 17, 21]:
        scheduler.add_job(notifica_urgenti_periodica, 'cron', hour=ora, minute=0, args=[app])

    # Dimenticate: 3 volte al giorno a orari random-ish
    scheduler.add_job(notifica_dimenticate, 'cron', hour=10, minute=random.randint(0,59), args=[app])
    scheduler.add_job(notifica_dimenticate, 'cron', hour=15, minute=random.randint(0,59), args=[app])
    scheduler.add_job(notifica_dimenticate, 'cron', hour=20, minute=random.randint(0,59), args=[app])

    # Pianificazione sera ore 23 lun-ven
    scheduler.add_job(notifica_pianifica_sera, 'cron', day_of_week='mon-fri', hour=23, minute=0, args=[app])

    # Check-in ripetitive ogni mattina ore 8
    scheduler.add_job(checkin_ripetitive, 'cron', hour=8, minute=0, args=[app])

    print("✅ Bot avviato!")
    print(f"CHAT_ID configurato: {os.environ.get('CHAT_ID')}")
    print(f"Scheduler jobs: {scheduler.get_jobs()}")
    app.run_polling()

if __name__ == "__main__":
    main()
