import telegram
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters as Filters, CallbackContext
import google.generativeai as genai
import re
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
import base64
import random
import logging
import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY_1 = os.environ.get('GEMINI_API_KEY_1')
GEMINI_API_KEY_2 = os.environ.get('GEMINI_API_KEY_2')
GEMINI_API_KEY_3 = os.environ.get('GEMINI_API_KEY_3')
GOOGLE_CREDENTIALS_BASE64 = os.environ.get('GOOGLE_CREDENTIALS_BASE64')
GROUP_ID_STR = os.environ.get('TELEGRAM_GROUP_ID')
SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')  # 显式读取 SHEET_ID 环境变量
SHEET_RANGE = os.environ.get('SHEET_RANGE')  # 显式读取 SHEET_RANGE 环境变量

credentials_json_str = base64.b64decode(GOOGLE_CREDENTIALS_BASE64).decode('utf-8') if GOOGLE_CREDENTIALS_BASE64 else None

CREDENTIALS = json.loads(credentials_json_str) if credentials_json_str else None

if CREDENTIALS:
    logging.info("成功加载凭据。")
else:
    logging.warning("GOOGLE_CREDENTIALS 未加载。")

# 确保将获取到的 GROUP_ID 转换为整数
try:
    GROUP_ID = int(GROUP_ID_STR) if GROUP_ID_STR else None
except (ValueError, TypeError):
    print("Error: TELEGRAM_GROUP_ID 环境变量未正确设置或不是有效的整数。")
    GROUP_ID = None

API_CONFIGS = [
    {'api_key': GEMINI_API_KEY_1},
    {'api_key': GEMINI_API_KEY_2},
    {'api_key': GEMINI_API_KEY_3}
]
GEMINI_MODELS = ['gemini-2.0-flash-exp-image-generation', 'gemini-2.0-pro','gemma-3-27b-it']
current_api_index = 0
current_model_index = 0
user_daily_limit_status = {}
user_remaining_days_status = {}
sent_vocabulary = []
user_translation_status = {}
main_keyboard_buttons = ['账号出售', '网站搭建', 'AI创业','网赚资源', '常用工具', '技术指导']
ADMIN_IDS = [7137722967] # 替换为你的 Telegram ID

def get_current_api_config():
    return API_CONFIGS[current_api_index]

def get_current_model():
    return GEMINI_MODELS[current_model_index]

def switch_to_next_model():
    global current_model_index
    current_model_index = (current_model_index + 1) % len(GEMINI_MODELS)
    print(f"Switched to model: {get_current_model()}")

def switch_to_next_api():
    global current_api_index, current_model_index
    current_api_index = (current_api_index + 1) % len(API_CONFIGS)
    current_model_index = 0
    print(f"Switched to API: {get_current_api_config()['api_key']}, model: {get_current_model()}")

def clean_text(text):
    text = text.replace('*', '')
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()

def get_sheets_service():
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    global CREDENTIALS
    if CREDENTIALS:
        creds = service_account.Credentials.from_service_account_info(CREDENTIALS, scopes=scopes)
        logging.debug("使用环境变量中的凭据创建 Google Sheets 服务。")
        return build('sheets', 'v4', credentials=creds)
    else:
        logging.warning("无法创建 Google Sheets 服务，因为凭据未加载。")
        return None

async def save_translation_history(user_id, original_text, translated_text):
    service = get_sheets_service()
    if service:
        history_sheet_name = 'TranslationHistory'
        timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime('%Y-%m-%d %H:%M:%S') # 老挝时间
        new_record = [str(user_id), timestamp, original_text, translated_text]
        body = {
            'values': [new_record]
        }
        try:
            response = service.spreadsheets().values().append(
                spreadsheetId=SHEET_ID,
                range=history_sheet_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            logging.info(f"保存翻译历史到 Google Sheets: {response}")
        except Exception as e:
            logging.error(f"保存翻译历史时出错: {e}")
            print(f"保存翻译历史时出错: {e}")

def get_user_info(user_id, username='default_user'):
    service = get_sheets_service()
    user_data = None
    logging.info(f"get_user_info called for user_id: {user_id}")
    if service:
        logging.info(f"SHEET_ID 的值: {SHEET_ID}")
        logging.info(f"SHEET_RANGE 的值 (在 get_user_info 中): {SHEET_RANGE}")
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values:
                for row in values: # 注意：这里不再跳过第一行，因为 SHEET_RANGE 从 A2 开始
                    if row and row[0] == str(user_id):
                        user_data = {
                            'user_id': row[0],
                            'username': row[1],
                            'daily_limit': int(row[2]),
                            'remaining_days': int(row[3]),
                            'join_date': row[4] if len(row) > 4 else datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime('%Y-%m-%d') # 获取加入日期，如果不存在则设置当前日期
                        }
                        logging.info(f"get_user_info found existing user: {user_data}")
                        return user_data
        except Exception as e:
            logging.error(f"get_user_info API error: {e}")
            print(f"get_user_info API error: {e}")

    # 如果完全没有找到用户信息，则写入新用户
    if not user_data:
        new_user_data = [str(user_id), username, '3', '3', datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime('%Y-%m-%d')] # 添加加入日期
        body = {
            'values': [new_user_data]
        }
        try:
            response = service.spreadsheets().values().append(
                spreadsheetId=SHEET_ID,
                range=SHEET_RANGE.split('!')[0],  # 只使用工作表名称
                valueInputOption='RAW',
                body=body
            ).execute()
            logging.info(f"get_user_info added new user {user_id} to Google Sheets: {response}")
            time.sleep(2) # 添加 2 秒延迟

            # 立即再次读取数据进行验证并打印
            verification_result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            verification_values = verification_result.get('values', [])
            logging.info(f"get_user_info - Verification read after append: {verification_values}")
            print(f"get_user_info - Verification read after append: {verification_values}") # 打印验证结果

            return {'user_id': str(user_id), 'username': username, 'daily_limit': 3, 'remaining_days': 3, 'join_date': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime('%Y-%m-%d')}
        except Exception as e:
            logging.error(f"get_user_info error writing new user: {e}")
            print(f"向 Google Sheets 写入新用户信息时出错: {e}")
            return {'user_id': str(user_id), 'username': username, 'daily_limit': 3, 'remaining_days': 3, 'join_date': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime('%Y-%m-%d')}
    logging.info(f"get_user_info returning user_data: {user_data}")
    return user_data

def get_all_user_ids():
    service = get_sheets_service()
    if service:
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values:
                return [int(row[0]) for row in values]
        except Exception as e:
            print(f"get_all_user_ids API error: {e}")
    return []

def update_user_daily_limit(user_id, daily_limit):
    service = get_sheets_service()
    if service:
        logging.info(f"update_user_daily_limit - SHEET_ID: {SHEET_ID}")
        logging.info(f"update_user_daily_limit - SHEET_RANGE: {SHEET_RANGE}")
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values: # 确保有数据
                for i, row in enumerate(values): # 从 values 的第一个元素开始遍历
                    if row[0] == str(user_id):
                        body = {
                            'value_input_option': 'RAW',
                            'data': [
                                {
                                    'range': f'UserStats!C{i + 2}', # 行号应该是 i + 2
                                    'values': [[str(daily_limit)]]
                                }
                            ]
                        }
                        update_result = service.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
                        print(f"update_user_daily_limit API response: {update_result}")
                        return  # 找到并更新后就返回
                print(f"警告：找不到用户 ID {user_id} 来更新每日限制。") # 如果遍历完没有找到匹配的 ID
        except Exception as e:
            print(f"update_user_daily_limit API error: {e}")

def update_user_remaining_days(user_id, remaining_days):
    service = get_sheets_service()
    if service:
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values:
                for i, row in enumerate(values):
                    if row[0] == str(user_id):
                        body = {
                            'value_input_option': 'RAW',
                            'data': [
                                {
                                    'range': f'UserStats!D{i + 2}',
                                    'values': [[str(remaining_days)]]
                                }
                            ]
                        }
                        update_result = service.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
                        print(f"update_user_remaining_days API response: {update_result}")
                        return
                print(f"警告：找不到用户 ID {user_id} 来更新剩余天数。")
        except Exception as e:
            print(f"update_user_remaining_days API error: {e}")

async def history(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    service = get_sheets_service()
    if service:
        history_sheet_name = 'TranslationHistory'
        range_name = f'{history_sheet_name}!A:D'
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=range_name).execute()
            values = result.get('values', [])
            history_records = []
            if values:
                # 跳过标题行（如果存在）
                for row in values:
                    if row and row[0] == str(user_id):
                        history_records.append(f"时间: {row[1]}\n原文: {row[2]}\n译文: {row[3]}\n------------------")
            if history_records:
                history_text = "\n".join(history_records[-10:]) # 显示最近 10 条
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"您的最近翻译历史 (最多 10 条):\n\n{history_text}")
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="您还没有任何翻译历史记录。")
        except Exception as e:
            logging.error(f"/history 命令出错: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="获取翻译历史时出错，请稍后再试。")

async def profile(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    user_info = get_user_info(user_id)
    if user_info:
        profile_text = f"**您的个人资料**\n\n用户ID: `{user_info['user_id']}`\n用户名: `{user_info['username']}`\n今日剩余翻译次数: `{user_info['daily_limit']}`\n加入日期: `{user_info['join_date']}`"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=profile_text, parse_mode=telegram.constants.ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="无法获取您的个人资料。")

async def feedback(update: Update, context: CallbackContext):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="请发送您的反馈或建议。")
    context.user_data['expecting_feedback'] = True

async def handle_feedback_message(update: Update, context: CallbackContext):
    if context.user_data.get('expecting_feedback'):
        user = update.effective_user
        feedback_text = update.message.text
        # 这里可以将反馈发送给管理员或者保存到 Google Sheets
        admin_chat_id = GROUP_ID # 假设将反馈发送到你的群组
        feedback_message = f"**新反馈：**\n用户ID: `{user.id}`\n用户名: `{user.username}`\n内容:\n{feedback_text}"
        try:
            await context.bot.send_message(chat_id=admin_chat_id, text=feedback_message, parse_mode=telegram.constants.ParseMode.MARKDOWN)
            await context.bot.send_message(chat_id=update.effective_chat.id, text="感谢您的反馈！")
        except Exception as e:
            logging.error(f"发送反馈给管理员时出错: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="发送反馈时出错，请稍后再试。")
        finally:
            context.user_data['expecting_feedback'] = False

async def admin_stats(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        service = get_sheets_service()
        if service:
            range_name = f'{SHEET_RANGE.split("!")[0]}!A:C' # 获取用户 ID
            try:
                result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=range_name).execute()
                values = result.get('values', [])
                if values:
                    stats_text = "**用户统计：**\n"
                    for row in values:
                        if row:
                            user_id = row[0]
                            translations_left = row[2] if len(row) > 2 else 'N/A'
                            stats_text += f"用户ID: `{user_id}`, 剩余次数: `{translations_left}`\n"
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=stats_text, parse_mode=telegram.constants.ParseMode.MARKDOWN)
                else:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text="没有找到任何用户数据。")
            except Exception as e:
                logging.error(f"/admin_stats 命令出错: {e}")
                await context.bot.send_message(chat_id=update.effective_chat.id, text="获取用户统计时出错。")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="无法连接到 Google Sheets。")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="您没有权限执行此命令。")

async def admin_set_limit(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        if len(context.args) == 2 and context.args[0].isdigit() and context.args[1].isdigit():
            target_user_id = int(context.args[0])
            new_limit = int(context.args[1])
            update_user_daily_limit(target_user_id, new_limit)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"已将用户ID `{target_user_id}` 的每日翻译次数设置为 `{new_limit}`。", parse_mode=telegram.constants.ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="用法: `/admin_set_limit <用户ID> <新的次数>`")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="您没有权限执行此命令。")

async def admin_broadcast(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        if context.args:
            message = " ".join(context.args)
            user_ids = get_all_user_ids()
            sent_count = 0
            failed_count = 0
            for user_id in user_ids:
                try:
                    await context.bot.send_message(chat_id=user_id, text=f"**管理员广播：**\n{message}", parse_mode=telegram.constants.ParseMode.MARKDOWN)
                    sent_count += 1
                    time.sleep(0.1) # 避免过于频繁发送
                except Exception as e:
                    logging.error(f"向用户 {user_id} 发送广播消息失败: {e}")
                    failed_count += 1
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"广播消息已发送给 {sent_count} 位用户，{failed_count} 位发送失败。")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="用法: `/admin_broadcast <要发送的消息>`")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="您没有权限执行此命令。")

async def translate(update, context):
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username if user.username else 'default_user'
        user_info = get_user_info(user_id, username)

        if user_id not in user_translation_status or user_translation_status[user_id] == 'enabled':
            user_text = update.message.text
            if len(user_text) > 20:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="免费用户每次翻译内容不能超过20字，文字较多可以断句分次发送。")
                return

            if user_info['daily_limit'] > 0:
                prompt = f"将以下中文文本翻译成老挝语，并用拉丁语展示老挝语的发音，返回中文注释、老挝语发音和纯汉字谐音。中文文本：{user_text}。格式：\n\n完整翻译：\n发音：（内容用拉丁语）\n纯汉字谐音：\n中文词语分析：（中文词语：老挝词语 （纯汉字谐音））"
                genai.configure(api_key=get_current_api_config()['api_key'])
                model = genai.GenerativeModel(get_current_model())
                response = model.generate_content(prompt)
                translation = response.text
                translation = re.sub(r'纯汉字谐音：(.*?)\n', lambda x: f'纯汉字谐音：{re.sub(r"[^\u4e00-\u9fa5]", "", x.group(1))}\n', translation)

                full_translation = re.search(r'完整翻译：(.*?)发音：', translation, re.DOTALL)
                latin_pronunciation = re.search(r'发音：(.*?)纯汉字谐音：', translation, re.DOTALL)
                chinese_homophonic = re.search(r'纯汉字谐音：(.*?)中文词语分析：', translation, re.DOTALL)
                word_analysis = re.search(r'中文词语分析：(.*)', translation, re.DOTALL)

                formatted_translation = f"----------------------------\n🇱🇦正文：\n{clean_text(full_translation.group(1).strip().replace('。', '\n')) if full_translation else '翻译结果未找到'}\n\n️发音：\n{clean_text(latin_pronunciation.group(1).strip().replace('。', '\n')) if latin_pronunciation else '拉丁发音结果未找到'}\n\n🇨🇳谐音：\n{clean_text(chinese_homophonic.group(1).strip()) if chinese_homophonic else '谐音结果未找到'}\n\n中文词语分析：\n{clean_text(word_analysis.group(1).strip()) if word_analysis else '词语分析结果未找到'}\n\n今日剩余翻译次数：{user_info['daily_limit'] - 1}"

                await context.bot.send_message(chat_id=update.effective_chat.id, text=formatted_translation, reply_to_message_id=update.message.message_id)

                update_user_daily_limit(user_id, user_info['daily_limit'] - 1)
                await save_translation_history(user_id, user_text, clean_text(full_translation.group(1).strip().replace('。', '\n')) if full_translation else '翻译失败')
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="今日翻译次数已用完，明日可以继续使用，升级为vip用户体验更完美")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已关闭，请在下方键盘点击“翻译开关”开启。")
    except Exception as e:
        print(f"translate 函数出错：{e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译过程中出现错误。请稍后再试。")

async def start(update, context):
    user = update.effective_user
    username = user.username if user.username else 'default_user'
    get_user_info(user.id, username) # 确保新用户在 /start 时被录入

    if user.id in ADMIN_IDS:
        # 管理员键盘
        admin_keyboard = [
            ['查看统计', '设置次数'],
            ['发送广播']
        ]
        reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="欢迎，管理员！请选择要执行的操作：", reply_markup=reply_markup)
    else:
        # 普通用户键盘
        keyboard = [
            ['账号出售', '网站搭建', 'AI创业'],
            ['网赚资源', '常用工具', '技术指导'],
            ['翻译开关', '我的资料']
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="请选择您需要的功能：", reply_markup=reply_markup)

async def admin_button_click(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        button_text = update.message.text
        if button_text == '查看统计':
            await admin_stats(update, context)
        elif button_text == '设置次数':
            await context.bot.send_message(chat_id=update.effective_chat.id, text="请发送要设置次数的用户ID和新的次数，格式为：`设置次数 <用户ID> <新的次数>`", parse_mode=telegram.constants.ParseMode.MARKDOWN)
            context.user_data['expecting_admin_set_limit'] = True
        elif button_text == '发送广播':
            await context.bot.send_message(chat_id=update.effective_chat.id, text="请发送要广播的消息内容：")
            context.user_data['expecting_admin_broadcast'] = True
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="无效的管理操作。")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="您没有权限执行此操作。")

async def handle_admin_input(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        if context.user_data.get('expecting_admin_set_limit'):
            text = update.message.text
            parts = text.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                target_user_id = int(parts[0])
                new_limit = int(parts[1])
                await admin_set_limit(update, context) # 直接调用现有的命令处理函数
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="格式错误。请发送：`用户ID 新的次数`", parse_mode=telegram.constants.ParseMode.MARKDOWN)
            context.user_data['expecting_admin_set_limit'] = False
        elif context.user_data.get('expecting_admin_broadcast'):
            message = update.message.text
            await admin_broadcast(update, context.bot, [message]) # 需要将 message 包装成列表传递给 context.args
            context.user_data['expecting_admin_broadcast'] = False

async def button_click(update, context):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        await admin_button_click(update, context)
    else:
        # 普通用户的按钮点击逻辑
        button_text = update.message.text
        if button_text == '翻译开关':
            if user.id not in user_translation_status or user_translation_status[user.id] == 'disabled':
                user_translation_status[user.id] = 'enabled'
                await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已开启。")
            else:
                user_translation_status[user.id] = 'disabled'
                await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已关闭。")
        elif button_text in main_keyboard_buttons:
            keyboard = [['1', '2', '3'], ['4', '5', '6'], ['返回主键盘']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"请选择 {button_text} 的子功能：", reply_markup=reply_markup)
        elif button_text in ['1', '2', '3', '4', '5', '6']:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"您选择了 {button_text}。")
        elif button_text == '返回主键盘':
            await start(update, context)
        elif button_text == '我的资料':
            await profile(update, context)
        else:
            if user.id in user_translation_status and user_translation_status[user.id] == 'enabled':
                await translate(update,context)
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="无效输入，请从主菜单开启翻译")


async def send_lao_vocabulary(context: CallbackContext):
    try:
        categories = ['交通', '教育', '日常', '工具', '餐饮', '娱乐', '房产', '汽车', '家用', '旅游', '航天', '婚姻', '情感', '社会', '名词', '动词', '代词', '副词', '形容词', '介词', '连接词', '感叹词', '限定词', '时间', '地点', '称呼', '动物', '植物', '行为', '运动', '单位', '数字', '关系', '身体', '颜色', '人体器官']
        selected_categories = random.sample(categories,5)

        prompt = f"从以下分类中随机生成 10 个老挝语词汇或句子，并提供中文翻译和拉丁语发音。分类：{', '.join(selected_categories)}。格式：中文：老挝语（谐音用汉语拼音）。已发送的词汇/句子：{sent_vocabulary}"
        genai.configure(api_key=get_current_api_config()['api_key'])
        model = genai.GenerativeModel(get_current_model())
        response = model.generate_content(prompt)
        vocabulary = response.text

        new_vocabulary = re.findall(r'^(.*?): (.*?)\((.*?)\)', vocabulary, re.MULTILINE)
        if new_vocabulary:
            sent_vocabulary.extend([item[1] for item in new_vocabulary])

        user_ids = get_all_user_ids()
        for user_id in user_ids:
            try:
                await context.bot.send_message(chat_id=user_id, text=vocabulary)
            except Exception as e:
                print(f"发送词汇给用户 {user_id} 时出错：{e}")

        try:
            await context.bot.send_message(chat_id=GROUP_ID, text=vocabulary)
        except Exception as e:
            print(f"发送词汇给群组 {GROUP_ID} 时出错：{e}")

    except Exception as e:
        print(f"send_lao_vocabulary 函数出错：{e}")

def reset_user_daily_limit_status():
    global user_daily_limit_status
    user_daily_limit_status = {}

def reset_user_remaining_days_status(user_id=None):
    global user_remaining_days_status
    if user_id:
        if user_id in user_remaining_days_status:
            del user_remaining_days_status[user_id]
    else:
        user_remaining_days_status = {}

def main():
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        start_handler = CommandHandler('start', start)
        application.add_handler(start_handler)
        button_handler = MessageHandler(Filters.TEXT & (~Filters.COMMAND), button_click)
        application.add_handler(button_handler)
        translate_handler = MessageHandler(Filters.TEXT & (~Filters.COMMAND), translate)
        application.add_handler(translate_handler)
        history_handler = CommandHandler('history', history)
        application.add_handler(history_handler)
        profile_handler = CommandHandler('profile', profile)
        application.add_handler(profile_handler)
        feedback_handler = CommandHandler('feedback', feedback)
        application.add_handler(feedback_handler)
        feedback_message_handler = MessageHandler(Filters.TEXT & (~Filters.COMMAND), handle_feedback_message)
        application.add_handler(feedback_message_handler)
        admin_stats_handler = CommandHandler('admin_stats', admin_stats)
        application.add_handler(admin_stats_handler)
        admin_set_limit_handler = CommandHandler('admin_set_limit', admin_set_limit)
        application.add_handler(admin_set_limit_handler)
        admin_broadcast_handler = CommandHandler('admin_broadcast', admin_broadcast)
        application.add_handler(admin_broadcast_handler)
        admin_input_handler = MessageHandler(Filters.TEXT & (~Filters.COMMAND), handle_admin_input)
        application.add_handler(admin_input_handler)

        target_time = datetime.time(hour=0, minute=0, second=0)
        application.job_queue.run_daily(reset_user_daily_limit_status, time=target_time)
        application.job_queue.run_once(send_lao_vocabulary, when=5)
        application.job_queue.run_daily(send_lao_vocabulary, time=target_time)

        application.run_polling()
    except Exception as e:
        print(f"main 函数出错：{e}")

if __name__ == '__main__':
    main()