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

def get_user_info(user_id, username='default_user'):
    service = get_sheets_service()
    user_data = None
    if service:
        logging.info(f"SHEET_ID 的值: {SHEET_ID}")
        logging.info(f"SHEET_RANGE 的值 (在 get_user_info 中): {SHEET_RANGE}")
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values and len(values) > 1:
                for row in values[1:]:
                    if row[0] == str(user_id):
                        user_data = {
                            'user_id': row[0],
                            'username': row[1],
                            'daily_limit': int(row[2]),
                            'remaining_days': int(row[3])
                        }
                        return user_data
        except Exception as e:
            logging.error(f"get_user_info API error: {e}")
            print(f"get_user_info API error: {e}")

    # 如果完全没有找到用户信息，则写入新用户
    if not user_data:
        new_user_data = [str(user_id), username, '3', '3']
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
            print(f"新用户 {user_id} 已添加到 Google Sheets: {response}")
            return {'user_id': str(user_id), 'username': username, 'daily_limit': 3, 'remaining_days': 3}
        except Exception as e:
            print(f"向 Google Sheets 写入新用户信息时出错: {e}")
            return {'user_id': str(user_id), 'username': username, 'daily_limit': 3, 'remaining_days': 3}
    return user_data

def get_all_user_ids():
    service = get_sheets_service()
    if service:
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values and len(values) > 1:
                return [int(row[0]) for row in values[1:]]
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
            if values and len(values) > 1:
                for i, row in enumerate(values[1:]):
                    if row[0] == str(user_id):
                        row_number = i + 2  # 找到匹配用户的行号（注意跳过标题行）
                        body = {
                            'value_input_option': 'RAW',
                            'data': [
                                {
                                    'range': f'UserStats!C{row_number}',
                                    'values': [[str(daily_limit)]]
                                }
                            ]
                        }
                        update_result = service.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
                        print(f"update_user_daily_limit API response: {update_result}")
                        return
                print(f"警告：找不到用户 ID {user_id} 来更新每日限制。")
        except Exception as e:
            print(f"update_user_daily_limit API error: {e}")

def update_user_remaining_days(user_id, remaining_days):
    service = get_sheets_service()
    if service:
        try:
            result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
            values = result.get('values', [])
            if values and len(values) > 1:
                for i, row in enumerate(values[1:]):
                    if row[0] == str(user_id):
                        row_number = i + 2  # 找到匹配用户的行号
                        body = {
                            'value_input_option': 'RAW',
                            'data': [
                                {
                                    'range': f'UserStats!D{row_number}',
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


async def translate(update, context):
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username if user.username else 'default_user'
        user_info = get_user_info(user_id, username)

        if user_id not in user_translation_status or user_translation_status[user_id] == 'enabled':
            user_text = update.message.text
            if len(user_text) > 20:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="每次翻译内容不能超过20字。")
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
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="今日翻译次数已用完。")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已关闭，请点击“翻译开关”开启。")
    except Exception as e:
        print(f"translate 函数出错：{e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译过程中出现错误。请稍后再试。")

async def start(update, context):
    user = update.effective_user
    username = user.username if user.username else 'default_user'
    get_user_info(user.id, username) # 确保新用户在 /start 时被录入

    keyboard = [
        ['账号出售', '网站搭建', 'AI创业'],
        ['网赚资源', '常用工具', '技术指导'],
        ['翻译开关']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="请选择您需要的功能：", reply_markup=reply_markup)

async def button_click(update, context):
    user = update.effective_user
    user_id = user.id
    username = user.username if user.username else 'default_user'
    button_text = update.message.text

    if button_text == '翻译开关':
        if user_id not in user_translation_status or user_translation_status[user_id] == 'disabled':
            user_translation_status[user_id] = 'enabled'
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已开启。")
        else:
            user_translation_status[user_id] = 'disabled'
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已关闭。")
    elif button_text in main_keyboard_buttons:
        # 显示二级键盘
        keyboard = [['1', '2', '3'], ['4', '5', '6'], ['返回主键盘']] # 示例二级键盘，包含返回主键盘按钮
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"请选择 {button_text} 的子功能：", reply_markup=reply_markup)
    elif button_text in ['1', '2', '3', '4', '5', '6']: # 二级键盘上的数字按钮
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"您选择了 {button_text}。") # 这里可以添加二级键盘数字按钮对应的功能
    elif button_text == '返回主键盘':
        await start(update, context) # 调用 start 函数，显示主键盘
    else:
        # 如果不是按钮，并且翻译开关是开启状态，那么就直接调用翻译功能
        if user_id in user_translation_status and user_translation_status[user_id] == 'enabled':
            await translate(update,context)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="无效输入，请从主菜单开启翻译")

async def send_lao_vocabulary(context: CallbackContext):
    try:
        categories = ['交通', '教育', '日常', '工具', '餐饮', '娱乐', '房产', '汽车', '家用', '旅游', '航天', '婚姻', '情感', '社会', '名词', '动词', '代词', '副词', '形容词', '介词', '连接词', '感叹词', '限定词', '时间', '地点', '称呼', '动物', '植物', '行为', '运动', '单位', '数字', '关系', '身体', '颜色', '人体器官']
        selected_categories = random.sample(categories,5) # 随机选择 5 个分类

        prompt = f"从以下分类中随机生成 10 个老挝语词汇或句子，并提供中文翻译和拉丁语发音。分类：{', '.join(selected_categories)}。格式：中文：老挝语（谐音用汉语拼音）。已发送的词汇/句子：{sent_vocabulary}"
        genai.configure(api_key=get_current_api_config()['api_key'])
        model = genai.GenerativeModel(get_current_model())
        response = model.generate_content(prompt)
        vocabulary = response.text

        # 将新生成的词汇/句子添加到已发送列表
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

        # 添加定时任务，每天凌晨重置用户每日翻译次数 (假设每天 00:00 UTC+7 是 00:00 UTC)
        target_time = datetime.time(hour=0, minute=0, second=0)
        application.job_queue.run_daily(reset_user_daily_limit_status, time=target_time)

        # 添加定时任务，每天发送老挝语词汇 (首次延迟 5 秒启动)
        application.job_queue.run_once(send_lao_vocabulary, when=5)
        application.job_queue.run_daily(send_lao_vocabulary, time=target_time)

        application.run_polling()
    except Exception as e:
        print(f"main 函数出错：{e}")

if __name__ == '__main__':
    main()
