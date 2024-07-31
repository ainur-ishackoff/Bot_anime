import asyncio
import logging
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
import hashlib
import os

# Настройки
API_TOKEN = 'YOUR_BOT_TOKEN'  # Вставьте сюда токен бота
ADMIN_ID = 'YOUR_ADMIN_ID'  # Вставьте сюда ID вашего Telegram-аккаунта
BASE_URL = f'https://api.telegram.org/bot{API_TOKEN}/'

# Логирование
logging.basicConfig(level=logging.INFO)

# Состояния для FSM
class AnimeSearch:
    def __init__(self):
        self.anime_title = None
        self.anime_channel = None

# Кнопки для инлайн-меню
def create_inline_keyboard(buttons: list[str], row_width: int = 2) -> dict:
    keyboard = []
    row = []
    for i, button in enumerate(buttons):
        row.append({"text": button, "callback_data": button})
        if (i + 1) % row_width == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return {"inline_keyboard": keyboard}

# Отправка сообщения
def send_message(chat_id, text, reply_markup=None):
    url = BASE_URL + 'sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'reply_markup': reply_markup
    }
    response = requests.post(url, json=payload)
    return response.json()

# Обработка команды /start
def start_handler(message):
    chat_id = message['chat']['id']
    if str(chat_id) == ADMIN_ID:
        reply_markup = create_inline_keyboard(['Добавить аниме'])
        send_message(chat_id, 'Добро пожаловать, админ! Выберите действие:', reply_markup=reply_markup)
    else:
        send_message(chat_id, 'Доступ запрещён.')

# Обработка команды /addanime
def add_anime_handler(message, state: AnimeSearch):
    chat_id = message['chat']['id']
    if str(chat_id) != ADMIN_ID:
        send_message(chat_id, 'Доступ запрещён.')
        return

    send_message(chat_id, 'Введите ссылку на AnimeVost:')
    state.anime_title = True

# Обработка ввода ссылки на AnimeVost
def anime_title_handler(message, state: AnimeSearch):
    chat_id = message['chat']['id']
    state.anime_title = message['text']
    send_message(chat_id, 'Вставьте ссылку на канал Telegram, куда будут выкладываться серии:')
    state.anime_channel = True

# Обработка ввода ссылки на канал
def anime_channel_handler(message, state: AnimeSearch):
    chat_id = message['chat']['id']
    state.anime_channel = message['text']

    # Получаем информацию об аниме
    get_anime_info(state.anime_title, state.anime_channel)
    send_message(chat_id, 'Аниме добавлено!')
    state.anime_title = None
    state.anime_channel = None

# Получение информации об аниме
def get_anime_info(anime_link: str, channel_link: str):
    response = requests.get(anime_link)
    soup = BeautifulSoup(response.text, 'lxml')

    anime_title = soup.find('h1', class_='title').text.strip()
    episodes_list = soup.find('ul', class_='episodes').find_all('li')

    anime_info = {
        'title': anime_title,
        'channel_id': channel_link[4:],
        'episodes': []
    }

    for episode in episodes_list:
        episode_link = episode.find('a')['href']
        episode_number = episode.find('span', class_='num').text.strip()
        episode_title = episode.find('span', class_='name').text.strip()
        episode_data = {
            'link': episode_link,
            'number': episode_number,
            'title': episode_title,
            'md5': None
        }
        anime_info['episodes'].append(episode_data)

    # Запуск цикла проверки новых серий
    asyncio.run(check_for_new_episodes(anime_info))

# Проверка на наличие новых серий
async def check_for_new_episodes(anime_info: dict):
    while True:
        await asyncio.sleep(30)

        for episode in anime_info['episodes']:
            response = requests.get(episode['link'])
            soup = BeautifulSoup(response.text, 'lxml')

            video_link = soup.find('a', class_='down_file')['href']
            md5_hash = hashlib.md5(video_link.encode()).hexdigest()

            if episode['md5'] != md5_hash:
                video_path = await download_video(video_link)
                await send_episode_to_channel(anime_info['channel_id'], video_path, episode)
                episode['md5'] = md5_hash

# Скачивание видео
async def download_video(video_link: str) -> str:
    response = requests.get(video_link, stream=True)
    file_name = video_link.split('/')[-1].split('?')[0]

    with open(file_name, 'wb') as f:
        total_length = int(response.headers.get('content-length'))
        for chunk in tqdm(response.iter_content(chunk_size=1024), total=total_length // 1024, unit='KB',
                          desc='Скачивание видео', leave=False):
            f.write(chunk)

    return file_name

# Отправка видео в канал
async def send_episode_to_channel(channel_id: str, video_path: str, episode_data: dict):
    try:
        url = BASE_URL + 'sendVideo'
        with open(video_path, 'rb') as video_file:
            files = {'video': video_file}
            payload = {
                'chat_id': channel_id,
                'caption': f"{episode_data['title']} (Серия {episode_data['number']})",
                'disable_notification': True
            }
            response = requests.post(url, data=payload, files=files)
            if response.status_code != 200:
                logging.error(f"Ошибка при отправке видео: {response.text}")
        os.remove(video_path)
    except Exception as e:
        logging.error(f"Ошибка при отправке видео: {e}")

# Обработка обновлений
def handle_updates(updates):
    state = AnimeSearch()
    for update in updates['result']:
        message = update.get('message') or update.get('callback_query', {}).get('message')
        if not message:
            continue

        chat_id = message['chat']['id']
        text = message.get('text') or message.get('data')

        if text == '/start':
            start_handler(message)
        elif text == 'Добавить аниме':
            add_anime_handler(message, state)
        elif state.anime_title is True:
            anime_title_handler(message, state)
        elif state.anime_channel is True:
            anime_channel_handler(message, state)

# Получение обновлений
def get_updates(offset=None):
    url = BASE_URL + 'getUpdates'
    payload = {'offset': offset} if offset else {}
    response = requests.get(url, params=payload)
    return response.json()

# Основной цикл
def main():
    offset = None
    while True:
        updates = get_updates(offset)
        if updates['ok']:
            handle_updates(updates)
            if updates['result']:
                offset = updates['result'][-1]['update_id'] + 1
        asyncio.sleep(1)

if __name__ == '__main__':
    main()