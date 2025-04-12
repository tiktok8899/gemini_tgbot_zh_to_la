import telegram
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters as Filters, CallbackContext
import google.generativeai as genai
import re
import time
import google.auth
from googleapiclient.discovery import build
import os
import random
import json
import logging

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logging.critical("TELEGRAM_BOT_TOKEN 环境变量未设置！程序退出。")
    exit(1)
logging.info("TELEGRAM_BOT_TOKEN 已加载。")

API_CONFIGS = [
    {
        'api_key': os.environ.get('GEMINI_API_KEY_1'),
    },
    {
        'api_key': os.environ.get('GEMINI_API_KEY_2'),
    },
    {
        'api_key': os.environ.get('GEMINI_API_KEY_3'),
    }
]
GEMINI_MODELS = ['gemini-2.0-flash-exp-image-generation', 'gemini-2.0-pro','gemma-3-27b-it'] # 您的 Gemini 模型列表
current_api_index = 0
current_model_index = 0
logging.info(f"初始 Gemini 模型: {GEMINI_MODELS[current_model_index]}")

# Google Sheets 配置
SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
if not SHEET_ID:
    logging.warning("GOOGLE_SHEET_ID 环境变量未设置。Google Sheets 相关功能可能无法正常工作。")
else:
    logging.info(f"GOOGLE_SHEET_ID 已加载: {SHEET_ID}")
SHEET_RANGE = 'A:D'

# 从环境变量中获取 JSON 凭据
credentials_json_str = os.environ.get('GOOGLE_CREDENTIALS_JSON')
CREDENTIALS = json.loads(credentials_json_str) if credentials_json_str else None
if not CREDENTIALS:
    logging.warning("GOOGLE_CREDENTIALS_JSON 环境变量未设置或内容无效。Google Sheets 相关功能可能无法正常工作。")
else:
    logging.info("GOOGLE_CREDENTIALS_JSON 已加载。")

user_daily_limit_status = {} # 用于跟踪用户每日翻译状态的字典
user_remaining_days_status = {} # 用于跟踪用户体验天数状态的字典

# 群组 ID
GROUP_ID = os.environ.get('TELEGRAM_GROUP_ID')
try:
    GROUP_ID = int(GROUP_ID)
    logging.info(f"TELEGRAM_GROUP_ID 已加载: {GROUP_ID}")
except (ValueError, TypeError):
    logging.error("TELEGRAM_GROUP_ID 环境变量未正确设置或不是有效的整数！")
    GROUP_ID = None

# 已发送的词汇/句子列表，用于避免重复
sent_vocabulary = []

# 用户状态字典，用于跟踪用户是否启用了翻译功能
user_translation_status = {}

#一级菜单的列表
main_keyboard_buttons = ['账号出售', '网站搭建', 'AI创业','网赚资源', '常用工具', '技术指导']

def get_current_api_config():
    config = API_CONFIGS[current_api_index]
    logging.debug(f"当前 API 配置: {config}")
    return config

def get_current_model():
    model = GEMINI_MODELS[current_model_index]
    logging.debug(f"当前 Gemini 模型: {model}")
    return model

def switch_to_next_model():
    global current_model_index
    current_model_index = (current_model_index + 1) % len(GEMINI_MODELS)
    logging.info(f"切换到模型: {get_current_model()}")

def switch_to_next_api():
    global current_api_index, current_model_index
    current_api_index = (current_api_index + 1) % len(API_CONFIGS)
    current_model_index = 0
    logging.info(f"切换到 API (Index: {current_api_index}), 模型: {get_current_model()}")

def clean_text(text):
    text = text.replace('*', '')
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()

def get_sheets_service():
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = google.auth.load_credentials_from_file(CREDENTIALS_FILE, scopes)[0]
    return build('sheets', 'v4', credentials=creds)

def get_user_info(user_id):
    if not CREDENTIALS or not SHEET_ID:
        logging.warning("无法获取用户信息，Google Sheets 凭据或 ID 未配置。")
        return {'user_id': str(user_id), 'username': 'default_user', 'daily_limit': 3, 'remaining_days': 1}
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
        values = result.get('values', [])
        if values and len(values) > 1:
            for row in values[1:]:
                if row[0] == str(user_id):
                    user_info = {
                        'user_id': row[0],
                        'username': row[1],
                        'daily_limit': int(row[2]),
                        'remaining_days': int(row[3])
                    }
                    logging.debug(f"获取用户信息 (User ID: {user_id}): {user_info}")
                    return user_info
        #如果没找到用户信息，默认初始化一个
        default_info = {'user_id': str(user_id), 'username': 'default_user', 'daily_limit': 3, 'remaining_days': 1}
        logging.info(f"未找到用户 {user_id} 的信息，返回默认信息: {default_info}")
        return default_info
    except Exception as e:
        logging.error(f"获取用户信息时出错 (User ID: {user_id}): {e}")
        return {'user_id': str(user_id), 'username': 'default_user', 'daily_limit': 3, 'remaining_days': 1}

def get_all_user_ids():
    if not CREDENTIALS or not SHEET_ID:
        logging.warning("无法获取所有用户 ID，Google Sheets 凭据或 ID 未配置。")
        return []
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
        values = result.get('values', [])
        if values and len(values) > 1:
            user_ids = [int(row[0]) for row in values[1:]]
            logging.debug(f"获取所有用户 ID: {user_ids}")
            return user_ids
        return []
    except Exception as e:
        logging.error(f"获取所有用户 ID 时出错: {e}")
        return []

def update_user_daily_limit(user_id, daily_limit):
    if not CREDENTIALS or not SHEET_ID:
        logging.warning("无法更新用户每日限制，Google Sheets 凭据或 ID 未配置。")
        return
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
        values = result.get('values', [])
        if values and len(values) > 1:
            for i, row in enumerate(values[1:]):
                if row[0] == str(user_id):
                    body = {
                        'value_input_option': 'RAW',
                        'data': [
                            {
                                'range': u'工作表1!C{}'.format(i + 2),
                                'values': [[str(daily_limit)]]
                            }
                        ]
                    }
                    update_result = service.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
                    logging.info(f"更新用户 {user_id} 每日限制为 {daily_limit}，API 响应: {update_result}")
                    return
    except Exception as e:
        logging.error(f"更新用户 {user_id} 每日限制时出错: {e}")

def update_user_remaining_days(user_id, remaining_days):
    if not CREDENTIALS or not SHEET_ID:
        logging.warning("无法更新用户剩余天数，Google Sheets 凭据或 ID 未配置。")
        return
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
        values = result.get('values', [])
        if values and len(values) > 1:
            for i, row in enumerate(values[1:]):
                if row[0] == str(user_id):
                    body = {
                        'value_input_option': 'RAW',
                        'data': [
                            {
                                'range': u'工作表1!D{}'.format(i + 2),
                                'values': [[str(remaining_days)]]
                            }
                        ]
                    }
                    update_result = service.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
                    logging.info(f"更新用户 {user_id} 剩余天数为 {remaining_days}，API 响应: {update_result}")
                    return
    except Exception as e:
        logging.error(f"更新用户 {user_id} 剩余天数时出错: {e}")

async def translate(update, context):
    try:
        user_id = update.effective_user.id
        user_info = get_user_info(user_id) #获取用户信息
        if user_id not in user_translation_status or user_translation_status[user_id] == 'enabled':
            if user_info['daily_limit'] <= 0:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="今日翻译次数已用完。")
                return

            user_text = update.message.text
            logging.info(f"用户 {user_id} 请求翻译: {user_text}")
            if len(user_text) > 20:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="每次翻译内容不能超过20字。")
                return

            prompt = f"将以下中文文本翻译成老挝语，并用拉丁语展示老挝语的发音，返回中文注释、老挝语发音和纯汉字谐音。中文文本：{user_text}。格式：\n\n完整翻译：\n发音：（内容用拉丁语）\n纯汉字谐音：\n中文词语分析：（中文词语：老挝词语 （纯汉字谐音））"
            genai.configure(api_key=get_current_api_config()['api_key'])
            model = genai.GenerativeModel(get_current_model())
            logging.info(f"使用模型 {get_current_model()} 和 API Key (Index: {current_api_index}) 进行翻译。")
            response = model.generate_content(prompt)
            translation = response.text
            logging.info(f"Gemini API 翻译结果: {translation}")
            translation = re.sub(r'纯汉字谐音：(.*?)\n', lambda x: f'纯汉字谐音：{re.sub(r"[^\u4e00-\u9fa5]", "", x.group(1))}\n', translation)

            full_translation = re.search(r'完整翻译：(.*?)发音：', translation, re.DOTALL)
            latin_pronunciation = re.search(r'发音：(.*?)纯汉字谐音：', translation, re.DOTALL)
            chinese_homophonic = re.search(r'纯汉字谐音：(.*?)中文词语分析：', translation, re.DOTALL)
            word_analysis = re.search(r'中文词语分析：(.*)', translation, re.DOTALL)

            formatted_translation = f"----------------------------\n🇱🇦正文：\n{clean_text(full_translation.group(1).strip().replace('。', '\n')) if full_translation else '翻译结果未找到'}\n\n️发音：\n{clean_text(latin_pronunciation.group(1).strip().replace('。', '\n')) if latin_pronunciation else '拉丁发音结果未找到'}\n\n🇨🇳谐音：\n{clean_text(chinese_homophonic.group(1).strip()) if chinese_homophonic else '谐音结果未找到'}\n\n中文词语分析：\n{clean_text(word_analysis.group(1).strip()) if word_analysis else '词语分析结果未找到'}\n\n今日剩余翻译次数：{user_info['daily_limit'] - 1}"

            await context.bot.send_message(chat_id=update.effective_chat.id, text=formatted_translation, reply_to_message_id=update.message.message_id)
            update_user_daily_limit(user_id, user_info['daily_limit'] - 1)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已关闭，请点击“翻译开关”开启。")
    except Exception as e:
        logging.error(f"translate 函数出错：{e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译过程中出现错误。请稍后再试。")

async def start(update, context):
    user_id = update.effective_user.id
    logging.info(f"用户 {user_id} 发送了 /start 命令。")
    keyboard = [
        ['账号出售', '网站搭建', 'AI创业'],
        ['网赚资源', '常用工具', '技术指导'],
        ['翻译开关']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="请选择您需要的功能：", reply_markup=reply_markup)

async def button_click(update, context):
    user_id = update.effective_user.id
    button_text = update.message.text
    logging.info(f"用户 {user_id} 点击了按钮: {button_text}")

    if button_text == '翻译开关':
        if user_id not in user_translation_status or user_translation_status[user_id] == 'disabled':
            user_translation_status[user_id] = 'enabled'
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已开启。")
        else:
            user_translation_status[user_id] = 'disabled'
            await context.bot.send_message(chat_id=update.effective_chat.id, text="翻译功能已关闭。")
    elif button_text in main_keyboard_buttons:
        keyboard = [['1', '2', '3'], ['4', '5', '6'], ['返回主键盘']] # 示例二级键盘，包含返回主键盘按钮
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"请选择 {button_text} 的子功能：", reply_markup=reply_markup)
    elif button_text in ['1', '2', '3', '4', '5', '6']: # 二级键盘上的数字按钮
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"您选择了 {button_text}。") # 这里可以添加二级键盘数字按钮对应的功能
    elif button_text == '返回主键盘':
        await start(update, context) # 调用 start 函数，显示主键盘
    else:
        #如果不是按钮，并且翻译开关是开启状态，那么就直接调用翻译功能
        if user_id in user_translation_status and user_translation_status[user_id] == 'enabled':
            await translate(update,context)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="无效输入，请从主菜单选择")

async def send_lao_vocabulary(context: CallbackContext):
    try:
        categories = ['交通', '教育', '日常', '工具', '餐饮', '娱乐', '房产', '汽车', '家用', '旅游', '航空', '航天', '婚姻', '情感', '社会', '名词', '动词', '代词', '副词', '形容词', '介词', '连接词', '感叹词', '限定词', '时间', '地点', '称呼', '动物', '植物', '行为', '运动', '单位', '数字', '关系', '身体', '颜色', '人体器官']
        selected_categories = random.sample(categories, 5) # 随机选择 5 个分类

        prompt = f"从以下分类中随机生成 10 个老挝语词汇或句子，并提供中文翻译和拉丁语发音。分类：{', '.join(selected_categories)}。格式：中文：老挝语（谐音用汉语拼音）。已发送的词汇/句子：{sent_vocabulary}"
        genai.configure(api_key=get_current_api_config()['api_key'])
        model = genai.GenerativeModel(get_current_model())
        logging.info(f"发送每日老挝语词汇，使用模型: {get_current_model()}, API Index: {current_api_index}, 分类: {selected_categories}")
        response = model.generate_content(prompt)
        vocabulary = response.text
        logging.info(f"生成的每日老挝语词汇: {vocabulary}")

        # 将新生成的词汇/句子添加到已发送列表
        new_vocabulary = re.findall(r'^(.*?): (.*?)\((.*?)\)', vocabulary, re.MULTILINE)
        if new_vocabulary:
            sent_vocabulary.extend([item[1] for item in new_vocabulary])
            logging.debug(f"已发送词汇列表更新: {sent_vocabulary}")

        user_ids = get_all_user_ids()
        for user_id in user_ids:
            try:
                await context.bot.send_message(chat_id=user_id, text=vocabulary)
                logging.info(f"成功发送每日词汇给用户 {user_id}")
            except Exception as e:
                logging.error(f"发送词汇给用户 {user_id} 时出错：{e}")

        if GROUP_ID:
            try:
                await context.bot.send_message(chat_id=GROUP_ID, text=vocabulary)
                logging.info(f"成功发送每日词汇给群组 {GROUP_ID}")
            except Exception as e:
                logging.error(f"发送词汇给群组 {GROUP_ID} 时出错：{e}")
        else:
            logging.warning("GROUP_ID 未设置，跳过向群组发送每日词汇。")

    except Exception as e:
        logging.error(f"send_lao_vocabulary 函数出错：{e}")


def reset_user_daily_limit_status():
    global user_daily_limit_status
    user_daily_limit_status = {}
    logging.info("用户每日翻译限制状态已重置。")

def reset_user_remaining_days_status(user_id=None):
    global user_remaining_days_status
    if user_id:
        if user_id in user_remaining_days_status:
            del user_remaining_days_status[user_id]
            logging.info(f"用户 {user_id} 的剩余天数状态已重置。")
    else:
        user_remaining_days_status = {}
        logging.info("所有用户的剩余天数状态已重置。")

def main():
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        start_handler = CommandHandler('start', start)
        application.add_handler(start_handler)
        button_handler = MessageHandler(Filters.TEXT & (~Filters.COMMAND), button_click)
        application.add_handler(button_handler)
        translate_handler = MessageHandler(Filters.TEXT & (~Filters.COMMAND), translate)
        application.add_handler(translate_handler)

        # 添加定时任务，每天凌晨重置用户每日翻译次数 (假设每天 00:00 UTC+7 是 17:00 UTC)
        application.job_queue.run_daily(reset_user_daily_limit_status, time=time.time() + 25200) # 7 小时 * 3600 秒

        # 添加定时任务，每隔 24 小时发送老挝语词汇 (首次延迟 5 秒启动)
        application.job_queue.run_repeating(send_lao_vocabulary, interval=24 * 3600, first=5)

        logging.info("Telegram Bot 开始运行...")
        application.run_polling()
    except Exception as e:
        logging.error(f"main 函数出错：{e}")

if __name__ == '__main__':
    main()
