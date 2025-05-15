import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from config import BOT_TOKEN
from models.db import init_db, SessionLocal, User, Note, Reminder, ScheduleEntry
from datetime import datetime


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    chat_id = data["chat_id"]
    title = data["title"]
    message = data["message"]
    text = f"⏰ *{title}*\n{message}"
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user = update.message.from_user
    text = update.message.text

    note_stage = context.user_data.get("add_note_stage")
    rem_stage = context.user_data.get("add_reminder_stage")

    sched_stage = context.user_data.get("sched_stage")

    if sched_stage == "title_add":
        context.user_data["sched_title"] = text
        context.user_data["sched_stage"] = "time_add"
        await update.message.reply_text("Теперь введите время (HH:MM):")
        return

    if sched_stage == "time_add":
        day = context.user_data["sched_chosen_day"]
        title = context.user_data["sched_title"]
        time_ = text

        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=telegram_user.id).first()
        entry = ScheduleEntry(user_id=user.id, day=day, title=title, time=time_)
        session.add(entry)
        session.commit()
        session.close()

        await update.message.reply_text(f"✅ Добавлено: {day} — {time_} {title}")
        context.user_data.clear()
        return

    if note_stage == "title":
        context.user_data["note_title"] = text
        context.user_data["add_note_stage"] = "content"
        await update.message.reply_text("📝 Теперь введи содержание заметки:")
        return

    if note_stage == "content":
        title = context.user_data.get("note_title")
        content = text

        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=telegram_user.id).first()
        if not user:
            await update.message.reply_text("❗ Пользователь не найден в БД.")
            session.close()
            context.user_data.clear()
            return

        note = Note(title=title, content=content, user=user)
        session.add(note)
        session.commit()
        session.close()

        await update.message.reply_text(f"✅ Заметка '{title}' добавлена.")
        context.user_data.clear()
        return

    if rem_stage == "title":
        context.user_data["reminder_title"] = text
        context.user_data["add_reminder_stage"] = "message"
        await update.message.reply_text("⏰ Теперь введи сообщение для напоминания:")
        return

    if rem_stage == "message":
        context.user_data["reminder_message"] = text
        context.user_data["add_reminder_stage"] = "time"
        await update.message.reply_text("⏰ Когда нужно напомнить? (формат: YYYY-MM-DD HH:MM)")
        return

    if rem_stage == "time":
        try:
            reminder_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text("❗ Неверный формат. Попробуй: YYYY-MM-DD HH:MM")
            return

        title = context.user_data["reminder_title"]
        message = context.user_data["reminder_message"]

        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=telegram_user.id).first()
        if not user:
            await update.message.reply_text("❗ Пользователь не найден в БД.")
            session.close()
            context.user_data.clear()
            return

        rem = Reminder(title=title, message=message, reminder_time=reminder_time, user=user)
        session.add(rem)
        session.commit()

        rem_id = rem.id
        chat_id = user.telegram_id

        session.close()

        await update.message.reply_text(
            f"✅ Напоминание '{title}' добавлено на {reminder_time.strftime('%Y-%m-%d %H:%M')}."
        )

        now = datetime.now()
        delay = (reminder_time - now).total_seconds()
        if delay > 0:
            context.application.job_queue.run_once(
                callback=send_reminder,
                when=delay,
                data={"chat_id": chat_id, "title": title, "message": message},
                name=f"reminder_{rem_id}")
        else:
            await send_reminder(context)

        context.user_data.clear()
        return

    await update.message.reply_text("❗ Пожалуйста, сначала выбери действие в меню (например, «✍️ Добавить заметку»).")


async def send_main_menu(chat_or_message, context: ContextTypes.DEFAULT_TYPE):
    telegram_user = chat_or_message.from_user
    session = SessionLocal()

    try:
        user = session.query(User).filter_by(telegram_id=telegram_user.id).first()
        if not user:
            user = User(
                telegram_id=telegram_user.id,
                username=telegram_user.username
            )
            session.add(user)
            session.commit()
            logging.info(f"Новый пользователь зарегистрирован: {telegram_user.id}")

    except Exception as e:
        logging.error(f"Ошибка при регистрации пользователя: {e}")
        session.rollback()
    finally:
        session.close()

    keyboard = [
        [InlineKeyboardButton("📓 Заметки", callback_data="notes")],
        [InlineKeyboardButton("⏰ Напоминания", callback_data="reminders")],
        [InlineKeyboardButton("📅 Расписание", callback_data="shedules")],
        [InlineKeyboardButton("🖼 Главное", callback_data="main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption = (
        "👋 Добро пожаловать!\n\n"
        "Этот бот поможет тебе:\n"
        "📓 Создавать и хранить заметки\n"
        "⏰ Настраивать напоминания\n"
        "📅 Планировать расписание\n\n"
        "Выбери, с чего хочешь начать:"
    )

    with open("images/main.png", "rb") as photo:
        await chat_or_message.reply_photo(photo=photo, caption=caption, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_main_menu(update.message, context)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main":
        await query.message.delete()
        await send_main_menu(query.message, context)


    elif query.data == "notes":
        await query.message.delete()
        note_keyboard = [
            [InlineKeyboardButton("✍️ Добавить", callback_data="add_note")],
            [InlineKeyboardButton("👁 Посмотреть", callback_data="view_notes")],
            [InlineKeyboardButton("❌ Удалить", callback_data="delete_note")],
            [InlineKeyboardButton("📤 Экспортировать", callback_data="export_notes")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main")]]
        with open("images/notes.png", "rb") as img:
            await query.message.reply_photo(
                photo=img,
                caption="📓 Управление заметками:\n\nВыбери, что хочешь сделать:",
                reply_markup=InlineKeyboardMarkup(note_keyboard))

    elif query.data == "view_notes":
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        notes = user.notes if user else []
        session.close()

        if not notes:
            await query.message.reply_text("У тебя пока нет заметок.")
        else:
            text = "\n\n".join([f"📝 *{n.title}*\n{n.content}" for n in notes])
            await query.message.reply_markdown(text[:4000])

    elif query.data == "add_note":
        context.user_data["add_note_stage"] = "title"
        await query.message.reply_text("✍️ Введи заголовок заметки:")

    elif query.data == "delete_note":
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        notes = user.notes if user else []
        session.close()

        if not notes:
            await query.message.reply_text("У тебя нет заметок для удаления.")
        else:
            buttons = [[InlineKeyboardButton(n.title, callback_data=f"delete_note_{n.id}")] for n in notes]
            buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="notes")])
            await query.message.reply_text("Выбери заметку для удаления:", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data.startswith("delete_note_"):
        note_id = int(query.data.split("_")[-1])
        session = SessionLocal()
        note = session.query(Note).filter_by(id=note_id).first()
        if note:
            session.delete(note)
            session.commit()
            await query.message.reply_text("❌ Заметка удалена.")
        else:
            await query.message.reply_text("❗ Заметка не найдена.")
        session.close()

    elif query.data == "export_notes":
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        notes = user.notes if user else []
        session.close()

        if not notes:
            await query.message.reply_text("У тебя нет заметок для экспорта.")
        else:
            file_name = "notes_export.txt"
            with open(file_name, "w", encoding="utf-8") as f:
                for note in notes:
                    f.write(f"📝 {note.title}\n{note.content}\n\n")

            with open(file_name, "rb") as file:
                await query.message.reply_document(
                    document=file,
                    caption="Вот твои заметки в формате .txt.")
    elif query.data == "reminders":
        await query.message.delete()

        reminder_keyboard = [
            [InlineKeyboardButton("⏰ Добавить напоминание", callback_data="add_reminder")],
            [InlineKeyboardButton("👁 Посмотреть напоминания", callback_data="view_reminders")],
            [InlineKeyboardButton("❌ Удалить напоминание", callback_data="delete_reminder")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main")]]

        with open("images/remind.png", "rb") as img:
            await query.message.reply_photo(
                photo=img,
                caption="⏰ Управление напоминаниями:\n\nВыбери, что хочешь сделать:",
                reply_markup=InlineKeyboardMarkup(reminder_keyboard))
    elif query.data == "add_reminder":
        context.user_data["add_reminder_stage"] = "title"
        await query.message.reply_text("⏰ Введи название напоминания:")

    elif query.data == "view_reminders":
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        reminders = user.reminders if user else []
        session.close()

        if not reminders:
            await query.message.reply_text("У тебя нет напоминаний.")
        else:
            reminder_text = "\n\n".join([f"⏰ *{r.title}*\n{r.message}\n{r.reminder_time}" for r in reminders])
            await query.message.reply_markdown(reminder_text[:4000])
    elif query.data == "delete_reminder":
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        reminders = user.reminders if user else []
        session.close()

        if not reminders:
            await query.message.reply_text("У тебя нет напоминаний для удаления.")
        else:
            buttons = [[InlineKeyboardButton(r.title, callback_data=f"delete_reminder_{r.id}")] for r in reminders]
            buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="reminders")])
            await query.message.reply_text("Выбери напоминание для удаления:",
                                           reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data.startswith("delete_reminder_"):
        reminder_id = int(query.data.split("_")[-1])
        session = SessionLocal()
        reminder = session.query(Reminder).filter_by(id=reminder_id).first()
        if reminder:
            session.delete(reminder)
            session.commit()
            await query.message.reply_text("❌ Напоминание удалено.")
        else:
            await query.message.reply_text("❗ Напоминание не найдено.")
        session.close()

    elif query.data == "shedules":
        await query.message.delete()
        schedule_kb = [
            [InlineKeyboardButton("➕ Добавить расписание", callback_data="add_sched")],
            [InlineKeyboardButton("🗑 Удалить расписание", callback_data="del_sched")],
            [InlineKeyboardButton("📋 Посмотреть расписание", callback_data="view_sched")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main")]]

        with open("images/shedules.png", "rb") as img:
            await query.message.reply_photo(
                photo=img,
                caption="📅 Управление расписанием:\n\nВыбери, что хочешь сделать:",
                reply_markup=InlineKeyboardMarkup(schedule_kb))

    elif query.data == "add_sched":
        context.user_data["sched_stage"] = "day_add"
        days = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(d, callback_data=f"sched_day_{d}")] for d in days])
        await query.message.reply_text("Выберите день недели:", reply_markup=kb)

    elif query.data.startswith("sched_day_") and context.user_data.get("sched_stage") == "day_add":
        day = query.data.split("_")[-1]
        context.user_data["sched_chosen_day"] = day
        context.user_data["sched_stage"] = "title_add"
        await query.message.reply_text(f"День: {day}\nВведите название дела:")

    elif context.user_data.get("sched_stage") == "title_add" and query.data is None:
        pass

    elif query.data == "del_sched":
        context.user_data["sched_stage"] = "day_del"
        days = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(d, callback_data=f"del_day_{d}")] for d in days])
        await query.message.reply_text("Выберите день для удаления:", reply_markup=kb)

    elif query.data.startswith("del_day_") and context.user_data.get("sched_stage") == "day_del":
        day = query.data.split("_")[-1]
        context.user_data["sched_chosen_day"] = day
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        entries = session.query(ScheduleEntry).filter_by(user_id=user.id, day=day).all()
        session.close()
        if not entries:
            await query.message.reply_text("В этот день нет дел.")
            context.user_data.clear()
            return
        buttons = []
        text = f"Дела в {day}:\n"
        for i, e in enumerate(entries, start=1):
            text += f"{i}. {e.time} — {e.title}\n"
            buttons.append([InlineKeyboardButton(str(i), callback_data=f"del_entry_{i}")])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="shedules")])
        context.user_data["sched_entries"] = entries
        context.user_data["sched_stage"] = "entry_del"
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data.startswith("del_entry_") and context.user_data.get("sched_stage") == "entry_del":
        idx = int(query.data.split("_")[-1]) - 1
        entries = context.user_data["sched_entries"]
        if 0 <= idx < len(entries):
            session = SessionLocal()
            session.delete(entries[idx])
            session.commit()
            session.close()
            await query.message.reply_text("🗑 Дело удалено.")
        else:
            await query.message.reply_text("❗ Неверный номер.")
        context.user_data.clear()

    elif query.data == "view_sched":
        session = SessionLocal()
        user = session.query(User).filter_by(telegram_id=query.from_user.id).first()
        days = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
        text = "📅 Ваше расписание:\n"
        for d in days:
            entries = session.query(ScheduleEntry).filter_by(user_id=user.id, day=d).order_by(ScheduleEntry.time).all()
            if entries:
                text += f"\n<b>{d}</b>\n"
                for e in entries:
                    text += f"• {e.time} — {e.title}\n"
        session.close()
        await query.message.reply_text(text, parse_mode="HTML")
        context.user_data.clear()


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    session = SessionLocal()
    now = datetime.now()
    entries = session.query(Reminder).filter(Reminder.reminder_time > now).all()
    for r in entries:
        rem_id = r.id
        chat_id = r.user.telegram_id
        title = r.title
        message = r.message
        remind_time = r.reminder_time

        delay = (remind_time - now).total_seconds()
        if delay > 0:
            app.job_queue.run_once(
                callback=send_reminder,
                when=delay,
                data={"chat_id": chat_id, "title": title, "message": message},
                name=f"reminder_{rem_id}"
            )
    session.close()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
