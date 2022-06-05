"""Вся программа расчитана для запуска на майнинг риге с gminer.
Можно подключать другие риги, при условии их нахождения в одной
локальной сети, либо они раздают API с внешних IP.
Программа не работает если: нет интернета, риг с запушеной программой
полностью выключился.
"""
import datetime
import logging
import os
import time
from http import HTTPStatus

import requests
import telegram
from dotenv import load_dotenv
from telegram.ext import CommandHandler, Updater

load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='program.log',
    level=logging.INFO,
    encoding='UTF-8',
    # stream=sys.stdout,  # Нельзя одновременно с filename=....
    filemode='a')


try:
    TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
    TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
except Exception as e:
    raise logging.error(f'Token error: {e}. Работа не возможна.')
EP_POOL_ALL = {
    'EP_2MINER_RVN' : 'https://rvn.2miners.com/api/accounts/RJph4xK73HBAG2C7uRfD8FBSvWSgKRw4rt',
    'EP_FLYPOOL_RVN' : 'https://api-ravencoin.flypool.org/miner/:RJph4xK73HBAG2C7uRfD8FBSvWSgKRw4rt/dashboard',
    
}
#  Ethpool, Ethermine & Flypool. имеют общий endpoint API, но лучше уточнять, особенно Fly:
#  'https://api.ethermine.org/miner/:0x8154b8c38d3b53010f878bad4b3864119771f9d2/dashboard' .
EP_ALL_RIGS = {
    # Здесь нужно указывать внутренний IP ригов.
    'EP_RIG_1': 'http://192.168.1.52:10293/stat',
    'EP_RIG_2': 'http://192.168.1.52:10294/stat',
}
EP_BIN_API = {
    'BIN_API_BTC....': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT',
    'BIN_API_CFX....': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=CFXUSDT',
    'BIN_API_CTXC..': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=CTXCUSDT',
    'BIN_API_NANO': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=NANOUSDT',
    'BIN_API_USDT..': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=USDTRUB',
    'BIN_API_RVN....': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=RVNUSDT',
    'BIN_API_ETH....': 'https://api2.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT',
}
SLEEP_TIME = 20  # цикл работы в секундах
TIMEOUT_ERROR = 3600  # 3600 - час
GPU_TEMP_LIMIT = 62  # 63 - градусы
MEM_TEMP_LIMIT = 97

def api_error(response):
    """Логируем ответ, если он не 200."""
    response_json = response.json()
    resp_s_c = response.status_code
    if ['error'] in response_json:
        resp_err = response_json['error']
        logging.error(f'response error:{resp_err}, status code:{resp_s_c}')
    elif ['code'] in response_json:
        resp_err = response_json['code']
        logging.error(f'response error:{resp_err}, status code:{resp_s_c}')
    else:
        logging.error(f'Endpoint != 200. error: {resp_s_c}.')
    raise


def get_api_answer(options_requsts: int = None):
    """Делает API запрос, проверяет на 200, возвращает словарь."""
    if options_requsts is not None:
        try:
            response = requests.get(options_requsts)
        except Exception as e:
            raise logging.error(f'Не удалось получить ответ API error: {e}.')
    else:
        raise logging.error('Не понятно куда делать запрос API.')
    response_json = response.json()
    if response.status_code != HTTPStatus.OK:
        api_error(response)
    logging.debug('Endpoint = 200.')
    if type(response_json) != dict:
        raise logging.error('response_json != dict. Обработка не возможна.')
    return response_json  # dict


def send_message(bot, message):
    """Отправляет сообщение в телеграм."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.info('Message send.')
    except Exception as e:
        raise logging.error(f'Error: {e}. bot.send_messege - incorrect.')


def parse_problem_from_rig(response_mi):
    """Парсит API с рига, готовит сообщение, если перегрев."""
    devices_all = response_mi['devices']
    global timestamp_err
    for id in devices_all:
        # Если есть перегрев, то спамит в Телегу раз в час.
        if (int(id['temperature']) > GPU_TEMP_LIMIT or int(id['memory_temperature']) > MEM_TEMP_LIMIT) and timestamp_err < int(time.time()):
            e1 = id['temperature']
            e2 = id['name']
            e3 = id['memory_temperature']
            timestamp_err = int(time.time()) + TIMEOUT_ERROR
            logging.warning(f'Перегрев на {e2} - температура: {e1} память: {e3}.')
            return (f'Перегрев на {e2} - температура: {e1} память: {e3}.')
        return None


def wake_up(update, context):
    """Бот. Подключаем кнопочки. /start."""
    chat = update.effective_chat
    name = update.message.chat.first_name
    button = telegram.ReplyKeyboardMarkup([
        ['/pool_stat', '/coin_stat', '/rig_stat']
    ], resize_keyboard=True)
    context.bot.send_message(
        chat_id=chat.id,
        text='Привет, {}. Кнопочки ап!'.format(name),
        reply_markup=button
    )


def pool_stat(update, context):
    """Бот. Парсит данные майнинга с сайта пула. /miner_stat."""
    for pool, adress in EP_POOL_ALL.items():
        response = get_api_answer(adress)
        try:
            hr_30min = response['currentHashrate'] or response['data']['currentStatistics']['currentHashrate']
            hr_6h = response['hashrate'] or response['data']['currentStatistics']['averageHashrate']
            status = not response['workers']['0']['offline'] or response['status']
            message_stat = (
                f'Пул: {pool}.\n'
                f'Хешрейт за 30 мин: {hr_30min/1000000:.2f} MH/s \n'
                f'Хешрейт за 6 часов: {hr_6h/1000000:.2f} MH/s \n'
                f'Статус: {status}\n'
            )
            send_message(context.bot, message_stat)
        except:
            logging.debug(f'Отсутствуют данные по пулу {pool}.')

def rig_stat(update, context):
    """Бот. Парсит данные майнинга с рига. gminer /rig_stat."""
    for rig, endpoint in EP_ALL_RIGS.items():
        message_stat = rig + '\n'
        response = get_api_answer(endpoint)
        uptime = datetime.timedelta(seconds=response['uptime'])
        start_time = datetime.datetime.fromtimestamp(int(time.time())) - uptime
        status = response['extended_share_info']
        hr = response['pool_speed']
        message_stat += (
            f'start_time: {start_time} \n'
            f'uptime: {uptime} \n'
            f'Статус: {status} \n'
            f'Хешрэйт по факту: {hr/1000000:.2f} MH/s\n'
        )
        devices = response['devices']
        for device in devices:
            name = device['name']
            fan = device['fan']
            temp = device['temperature']
            m_temp = device['memory_temperature']
            hr = device['speed']
            add_message = f'{name} t: {temp} tm: {m_temp} fan: {fan} hr: {hr/1000000:.2f} MH/s\n'
            message_stat += add_message
        send_message(context.bot, message_stat)


def coin_stat(update, context):
    """Бот. Парсит данные coin с биржи. /coin_stat."""
    message_stat = ' '
    for name, adress in EP_BIN_API.items():
        response = get_api_answer(adress)
        # symbol = response['symbol']
        price = float(response['lastPrice'])
        price_pr = float(response['priceChangePercent'])
        highPrice = float(response['highPrice'])
        message_tmp = f'== {name},{price_pr:.2f} - percent, price:{price:.2f},  h_p:{highPrice:.2f} \n'
        message_stat += message_tmp
    send_message(context.bot, message_stat)


def main():
    """MAIN is MAIN."""
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    updater = Updater(token=TELEGRAM_TOKEN)
    updater.dispatcher.add_handler(CommandHandler('start', wake_up))
    updater.dispatcher.add_handler(CommandHandler('pool_stat', pool_stat))
    updater.dispatcher.add_handler(CommandHandler('rig_stat', rig_stat))
    updater.dispatcher.add_handler(CommandHandler('coin_stat', coin_stat))
    global timestamp_err
    timestamp_err = 0
    send_message(bot, ('Риг запустился или перезагрузился!'))
    logging.warning('Риг запустился или перезагрузился!')
    # Т.к. скрипт запускается на риге, то после перезагрузки
    # (если скрипт в авто запуске ОС) скрипт запустится и сообщит об этом
    # в Телегу.
    while True:
        # Ниже проблемы рига.
        try:
            for rig, endpoint in EP_ALL_RIGS.items():
                response_mi = get_api_answer(endpoint)
                problems = parse_problem_from_rig(response_mi)
                if isinstance(problems, str):
                    send_message(bot, (f'{rig} \n {problems}'))
            # Далее запросы через бота. Обработка хендлеров.
            updater.start_polling(poll_interval=20.0)
            time.sleep(SLEEP_TIME)
        # Далее - если где либо выше будет исключение, то получаем
        # сообщение в телегу(раз в час). В случае деплоя скрипта
        # на внешнем от рига сервере, то это решит проблему с получение
        # сигнала о отсутствии инета или полном отключении рига,
        # т.к. сработает исключение и получим сообщение ниже.
        except Exception as e:
            if timestamp_err < int(time.time()):
                message = f'Сбой в работе программы: {e}. \n Проверь риги. Работаем.'
                bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=message
                )
                timestamp_err = int(time.time()) + TIMEOUT_ERROR
            logging.error('Общее исключение. Цикл. Работаем.')
            time.sleep(SLEEP_TIME)
        else:
            logging.debug('Цикл прошел. Все ок.')


if __name__ == '__main__':
    main()
