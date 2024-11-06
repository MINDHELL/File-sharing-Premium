# line number 160-169 check for changes - token
from pymongo import MongoClient
import asyncio
import base64
import logging
import os
import random
import re
import string
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from pyrogram import Client, filters, __version__
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated

from bot import Bot
from config import (
    ADMINS,
    BAN,
    FORCE_MSG,
    START_MSG,
    CUSTOM_CAPTION,
    IS_VERIFY,
    VERIFY_EXPIRE,
    SHORTLINK_API,
    SHORTLINK_URL,
    DISABLE_CHANNEL_BUTTON,
    PROTECT_CONTENT,
    TUT_VID,
    OWNER_ID,
    DB_NAME,
    DB_URI,
)
from helper_func import subscribed, encode, decode, get_messages, get_shortlink, get_verify_status, update_verify_status, get_exp_time
from database.database import add_user, del_user, full_userbase, present_user
from shortzy import Shortzy
from asyncio import sleep


delete_after = 600

client = MongoClient(DB_URI)  # Replace with your MongoDB URI
db = client[DB_NAME]  # Database name
pusers = db["pusers"]  # Collection for users



# MongoDB Helper Functions
async def add_premium_user(user_id, duration_in_days):
    expiry_time = time.time() + (duration_in_days * 86400)  # Calculate expiry time in seconds
    pusers.update_one(
        {"user_id": user_id},
        {"$set": {"is_premium": True, "expiry_time": expiry_time}},
        upsert=True
    )

async def remove_premium_user(user_id):
    pusers.update_one(
        {"user_id": user_id},
        {"$set": {"is_premium": False, "expiry_time": None}}
    )

async def get_user_subscription(user_id):
    user = pusers.find_one({"user_id": user_id})
    if user:
        return user.get("is_premium", False), user.get("expiry_time", None)
    return False, None

async def is_premium_user(user_id):
    is_premium, expiry_time = await get_user_subscription(user_id)
    if is_premium and expiry_time > time.time():
        return True
    return False

# Function to schedule deletion of a message
async def schedule_auto_delete(client, chat_id, message_id, delay):
    await sleep(delay)  # Delay in seconds
    await client.delete_messages(chat_id=chat_id, message_ids=message_id)
    logger.info(f"Deleted message with ID {message_id} from chat {chat_id}")

@Bot.on_message(filters.command('start') & filters.private & subscribed)
async def start_command(client: Client, message: Message):
    id = message.from_user.id
    UBAN = BAN  # Fetch the owner's ID from config
    
    # Schedule the initial message for deletion after 10 minutes
    delete_time = datetime.now() + timedelta(minutes=10)  # Schedule for 10 minutes later
    await schedule_auto_delete(client, message.chat.id, message.id, delay=600)
    await message.reply("Your message will be auto-deleted after 10 minutes.")

    # Check if the user is the owner
    if id == UBAN:
        sent_message = await message.reply("You are the U-BAN! Additional actions can be added here.")
        #await schedule_auto_delete(client, sent_message.chat.id, sent_message.id, delay=600)

    else:
        if not await present_user(id):
            try:
                await add_user(id)
            except Exception as e:
                print(f"Error adding user: {e}")

        premium_status = await is_premium_user(id)
        verify_status = await get_verify_status(id)
        
        # Check verification status
        if verify_status['is_verified'] and VERIFY_EXPIRE < (time.time() - verify_status['verified_time']):
            await update_verify_status(id, is_verified=False)

        # Handle token verification link
        if "verify_" in message.text:
            _, token = message.text.split("_", 1)
            if verify_status['verify_token'] != token:
                sent_message = await message.reply("Your token is invalid or expired. Try again by clicking /start.")
                #await schedule_auto_delete(client, sent_message.chat.id, sent_message.id, delay=600)
                return
            await update_verify_status(id, is_verified=True, verified_time=time.time())
            sent_message = await message.reply("Your token was successfully verified and is valid for 24 hours.")
            #await schedule_auto_delete(client, sent_message.chat.id, sent_message.id, delay=600)

        elif len(message.text) > 7 and (verify_status['is_verified'] or premium_status):
            try:
                base64_string = message.text.split(" ", 1)[1]
            except:
                return
            _string = await decode(base64_string)
            argument = _string.split("-")
            ids = []

            if len(argument) == 3:
                start = int(int(argument[1]) / abs(client.db_channel.id))
                end = int(int(argument[2]) / abs(client.db_channel.id))
                ids = range(start, end+1) if start <= end else []
            elif len(argument) == 2:
                ids = [int(int(argument[1]) / abs(client.db_channel.id))]

            temp_msg = await message.reply("Please wait...")
            #await schedule_auto_delete(client, temp_msg.chat.id, temp_msg.id, delay=600)

            try:
                messages = await get_messages(client, ids)
            except:
                error_msg = await message.reply_text("Something went wrong..!")
                #await schedule_auto_delete(client, error_msg.chat.id, error_msg.id, delay=600)
                return

            snt_msgs = []
            
            # Send and auto-delete messages for each document
            for msg in messages:
                caption = (CUSTOM_CAPTION.format(previouscaption=msg.caption.html, filename=msg.document.file_name)
                           if CUSTOM_CAPTION and msg.document else msg.caption.html or "")
                reply_markup = None if DISABLE_CHANNEL_BUTTON else msg.reply_markup

                try:
                    snt_msg = await msg.copy(chat_id=message.from_user.id, caption=caption, reply_markup=reply_markup)
                    snt_msgs.append(snt_msg)
                    await schedule_auto_delete(client, snt_msg.chat.id, snt_msg.id, delay=3600)
                    await sleep(0.5)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    snt_msg = await msg.copy(chat_id=message.from_user.id, caption=caption, reply_markup=reply_markup)
                    snt_msgs.append(snt_msg)
                    #await schedule_auto_delete(client, snt_msg.chat.id, snt_msg.id, delay=3600)

        # Display user information if verified or premium
        elif verify_status['is_verified'] or premium_status:
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("About Me", callback_data="about"),
                        InlineKeyboardButton("Close", callback_data="close")
                    ],
                    [
                        InlineKeyboardButton("✨ Premium", callback_data="upi_info")
                    ]
                ]
            )
            welcome_message = await message.reply_text(
                text=START_MSG.format(
                    first=message.from_user.first_name,
                    last=message.from_user.last_name,
                    username=None if not message.from_user.username else '@' + message.from_user.username,
                    mention=message.from_user.mention,
                    id=message.from_user.id
                ),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                quote=True
            )
            #await schedule_auto_delete(client, welcome_message.chat.id, welcome_message.id, delay=600)

        else:
            # If not verified, send verification message with link
            verify_status = await get_verify_status(id)
            if IS_VERIFY and not verify_status['is_verified']:
                token = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                await update_verify_status(id, verify_token=token, link="")
                link = await get_shortlink(SHORTLINK_URL, SHORTLINK_API, f'https://telegram.dog/{client.username}?start=verify_{token}')
                btn = [
                    [InlineKeyboardButton("Click here", url=link)],
                    [InlineKeyboardButton("How to use the bot", url=TUT_VID)],
                    [InlineKeyboardButton("✨ Premium", callback_data="upi_info")]
                ]
                verification_message = await message.reply(
                    f"Your token has expired. Refresh your token to continue.\nToken Timeout: {get_exp_time(VERIFY_EXPIRE)}",
                    reply_markup=InlineKeyboardMarkup(btn),
                    protect_content=False,
                    quote=True
                )
                await schedule_auto_delete(client, verification_message.chat.id, verification_message.id, delay=600)


    
#=====================================================================================##

WAIT_MSG = """"<b>Processing ...</b>"""

REPLY_ERROR = """<code>Use this command as a replay to any telegram message with out any spaces.</code>"""

#=====================================================================================##

    
    
@Bot.on_message(filters.command('start') & filters.private)
async def not_joined(client: Client, message: Message):
    buttons = [
        [
            InlineKeyboardButton(text="Join Channel", url=client.invitelink),
            InlineKeyboardButton(text="Join Channel", url=client.invitelink2),
        ],
        [
            InlineKeyboardButton(text="Join Channel", url=client.invitelink3),
            #InlineKeyboardButton(text="Join Channel", url=client.invitelink4),
        ]
    ]
    try:
        buttons.append(
            [
                InlineKeyboardButton(
                    text = 'Try Again',
                    url = f"https://t.me/{client.username}?start={message.command[1]}"
                )
            ]
        )
    except IndexError:
        pass

    await message.reply(
        text = FORCE_MSG.format(
                first = message.from_user.first_name,
                last = message.from_user.last_name,
                username = None if not message.from_user.username else '@' + message.from_user.username,
                mention = message.from_user.mention,
                id = message.from_user.id
            ),
        reply_markup = InlineKeyboardMarkup(buttons),
        quote = True,
        disable_web_page_preview = True
    )



@Bot.on_message(filters.command('users') & filters.private & filters.user(ADMINS))
async def get_users(client: Bot, message: Message):
    msg = await client.send_message(chat_id=message.chat.id, text=WAIT_MSG)
    users = await full_userbase()
    await msg.edit(f"{len(users)} users are using this bot")

@Bot.on_message(filters.private & filters.command('broadcast') & filters.user(ADMINS))
async def send_text(client: Bot, message: Message):
    if message.reply_to_message:
        query = await full_userbase()
        broadcast_msg = message.reply_to_message
        total = 0
        successful = 0
        blocked = 0
        deleted = 0
        unsuccessful = 0
        
        pls_wait = await message.reply("<i>Broadcasting Message.. This will Take Some Time</i>")
        for chat_id in query:
            try:
                await broadcast_msg.copy(chat_id)
                successful += 1
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await broadcast_msg.copy(chat_id)
                successful += 1
            except UserIsBlocked:
                await del_user(chat_id)
                blocked += 1
            except InputUserDeactivated:
                await del_user(chat_id)
                deleted += 1
            except:
                unsuccessful += 1
                pass
            total += 1
        
        status = f"""<b><u>Broadcast Completed</u>

Total Users: <code>{total}</code>
Successful: <code>{successful}</code>
Blocked Users: <code>{blocked}</code>
Deleted Accounts: <code>{deleted}</code>
Unsuccessful: <code>{unsuccessful}</code></b>"""
        
        return await pls_wait.edit(status)

    else:
        msg = await message.reply(REPLY_ERROR)
        await asyncio.sleep(8)
        await msg.delete()
"""
# Add /addpr command for admins to add premium subscription
@Bot.on_message(filters.command('addpr') & filters.private)
async def add_premium(client: Client, message: Message):
    if message.from_user.id != ADMINS:
        return await message.reply("You don't have permission to add premium users.")

    try:
        command_parts = message.text.split()
        target_user_id = int(command_parts[1])
        duration_in_days = int(command_parts[2])
        await add_premium_user(target_user_id, duration_in_days)
        await message.reply(f"User {target_user_id} added to premium for {duration_in_days} days.")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")

# Add /removepr command for admins to remove premium subscription
@Bot.on_message(filters.command('removepr') & filters.private)
async def remove_premium(client: Client, message: Message):
    if message.from_user.id != ADMINS:
        return await message.reply("You don't have permission to remove premium users.")

    try:
        command_parts = message.text.split()
        target_user_id = int(command_parts[1])
        await remove_premium_user(target_user_id)
        await message.reply(f"User {target_user_id} removed from premium.")
    except Exception as e:
        await message.reply(f"Error: {str(e)}")
"""
'''
# Add /myplan command for users to check their premium subscription status
@Bot.on_message(filters.command('myplan') & filters.private)
async def my_plan(client: Client, message: Message):
    is_premium, expiry_time = await get_user_subscription(message.from_user.id)
    if is_premium:
        time_left = expiry_time - time.time()
        days_left = int(time_left / 86400)
        await message.reply(f"Your premium subscription is active. Time left: {days_left} days.")
    else:
        await message.reply("You are not a premium user.")

# Add /plans command to show available subscription plans
@Bot.on_message(filters.command('plans') & filters.private)
async def show_plans(client: Client, message: Message):
    plans_text = """
Available Subscription Plans:

1. 7 Days Premium - $5
2. 30 Days Premium - $15
3. 90 Days Premium - $35

Use /upi to make the payment.
"""
    await message.reply(plans_text)

# Add /upi command to provide UPI payment details
@Bot.on_message(filters.command('upi') & filters.private)
async def upi_info(client: Client, message: Message):
    upi_text = """
To subscribe to premium, please make the payment via UPI.

UPI ID: your-upi-id@bank

After payment, contact the bot admin to activate your premium subscription.
"""
    await message.reply(upi_text)

'''
