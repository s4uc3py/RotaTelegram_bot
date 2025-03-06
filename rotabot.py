import datetime
import json
import os
import calendar
import random
from telegram import ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, filters
from telegram.ext import MessageFilter
import logging
import pytz  


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

USERS_FILE = 'employees.txt'
SCHEDULE_FILE = 'schedule.json'

class AddedToGroupFilter(MessageFilter):
    def filter(self, message):
        return message.new_chat_members and any(bot.id == member.id for member in message.new_chat_members)

added_to_group_filter = AddedToGroupFilter()

def load_users():
    try:
        with open(USERS_FILE, 'r') as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []

def save_users(users):
    with open(USERS_FILE, 'w') as file:
        file.write('\n'.join(users))

def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, 'r') as file:
                return json.load(file)
        except json.JSONDecodeError:
            return {}
    return {}

def save_schedule(schedule_data):
    with open(SCHEDULE_FILE, 'w') as file:
        json.dump(schedule_data, file)

def get_last_duty_person(schedule_data, users):
    last_date = sorted(schedule_data.keys(), reverse=True)
    if not last_date:
        return None
    last_person = schedule_data[last_date[0]].get('duty_person')
    return users.index(last_person) if last_person in users else None

def send_daily_notification(context: CallbackContext):
    chat_id = context.job.context.get('chat_id')
    if not chat_id:
        logging.error("Chat ID is missing in the context.")
        return

    today = datetime.date.today()
    # Пропускаем праздничные дни и выходные
    if today.weekday() >= 5:
        logging.info(f"Сегодня ({today}) выходной день. Уведомление не отправляется.")
        return

    # Проверяем, является ли сегодня первый день нового месяца
    if today.day == 1:
        monthly_schedule(context, chat_id=chat_id)

    # Определение дежурного сотрудника
    users = load_users()
    if not users:
        context.bot.send_message(chat_id, "Список сотрудников пуст. Пожалуйста, добавьте сотрудников.")
        logging.error("Список сотрудников пуст.")
        return

    schedule_data = load_schedule()
    today_str = today.strftime('%Y-%m-%d')

    if today_str not in schedule_data:
        duty_person = users[today.day % len(users)]
        schedule_data[today_str] = {"duty_person": duty_person}
        save_schedule(schedule_data)
    else:
        duty_person = schedule_data[today_str]["duty_person"]

    # Отправка уведомления в групповой чат в Telegram
    try:
        context.bot.send_message(chat_id, f"Сегодня ({today.strftime('%d.%m.%Y')}) дежурит: {duty_person}")
        logging.info(f"Уведомление отправлено в чат {chat_id}: {duty_person}")
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления: {e}")

def monthly_schedule(context: CallbackContext, chat_id=None):
    if chat_id is None:
        chat_id = context.job.context.get('chat_id') if context.job and context.job.context else None
    if not chat_id:
        logging.error("Chat ID is missing in the context.")
        return

    logging.info(f"Ежемесячное расписание запущено для чата с ID: {chat_id}")

    users = load_users()
    if not users:
        context.bot.send_message(chat_id, "Список сотрудников пуст. Пожалуйста, добавьте сотрудников.")
        return

    today = datetime.date.today()
    _, last_day = calendar.monthrange(today.year, today.month)

    # Загружаем предыдущее расписание
    schedule_data = load_schedule()

    # Начинаем с последнего дежурного
    start_index = get_last_duty_person(schedule_data, users) or 0
    users_rotated = users[start_index:] + users[:start_index]

    new_schedule_data = {}
    users_iterator = iter(users_rotated * ((last_day // len(users)) + 1))  # Создаем достаточно длинный список

    for day in range(1, last_day + 1):
        date = datetime.date(today.year, today.month, day)

        # Пропускаем выходные
        if date.weekday() >= 5:
            continue

        try:
            duty_person = next(users_iterator)
        except StopIteration:
            users_iterator = iter(users_rotated)
            duty_person = next(users_iterator)

        new_schedule_data[date.strftime('%Y-%m-%d')] = {"duty_person": duty_person}

    save_schedule(new_schedule_data)

    # Отправляем новое расписание в чат
    schedule_message = "\n".join(
        f"{date}: Дежурит: {new_schedule_data[date]['duty_person']}" for date in sorted(new_schedule_data.keys())
    )
    context.bot.send_message(chat_id, f"Новое расписание:\n{schedule_message}")

def start(update, context: CallbackContext):
    chat_id = update.message.chat_id

    if 'activated' not in context.chat_data:
        context.chat_data['activated'] = True

        # Укажите вашу временную зону (например, Europe/Moscow)
        local_timezone = pytz.timezone('Europe/Moscow')

        # Запускаем ежедневную проверку
        context.job_queue.run_daily(
            send_daily_notification,
            time=datetime.time(hour=9, minute=0, tzinfo=local_timezone),
            context={'chat_id': chat_id}
        )
        logging.info(f"Ежедневная проверка расписания запланирована для чата с ID: {chat_id}")
        context.bot.send_message(chat_id, "Бот активирован. Начинаю отправку расписания.")
        logging.info(f"Бот активирован для чата с ID: {chat_id}")

def create_new_schedule(update, context: CallbackContext):
    chat_id = update.message.chat_id

    if 'schedule_created' not in context.chat_data:
        context.chat_data['schedule_created'] = True
        monthly_schedule(context, chat_id=chat_id)  # Передаем chat_id явно
        context.bot.send_message(chat_id, "Новое расписание успешно создано.")
        logging.info(f"New schedule created for chat_id: {chat_id}")
    else:
        context.bot.send_message(chat_id, "Расписание уже было создано.")

def support(update, context: CallbackContext):
    chat_id = update.message.chat_id
    schedule_data = load_schedule()
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')

    if today_str in schedule_data:
        duty_person = schedule_data[today_str]['duty_person']
        context.bot.send_message(chat_id, f"Сегодня ({today.strftime('%d.%m.%Y')}) дежурит: {duty_person}")
    else:
        context.bot.send_message(chat_id, "На сегодня дежурных не назначено.")

def main():
    TOKEN = 'ВАШ_ТОКЕН'
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("go", start))
    dp.add_handler(CommandHandler("new", create_new_schedule))
    dp.add_handler(CommandHandler("support", support))
    dp.add_handler(MessageHandler(added_to_group_filter, start))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()