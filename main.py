import os
import sqlite3
import time
import threading
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ================= КОНФИГУРАЦИЯ =================
INSTANCE_ID = os.getenv("INSTANCE_ID", "7107626489")
API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise ValueError("API_TOKEN жок!")

GROUP_ID = os.getenv("GROUP_ID")  # WhatsApp группасынын ID (постлор үчүн)
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "996227155603")  # Админ номери

BASE_URL = f"https://api.green-api.com/waInstance{INSTANCE_ID}"

# ================= REGIONS =================
regions = {
    "Баткен облусу": ["Баткен", "Кадамжай", "Лейлек (Раззаков)", "Кызыл-Кыя", "Сүлүктү"],
    "Жалал-Абад облусу": ["Манас", "Сузак", "Базар-Коргон", "Ноокен", "Кара-Көл", "Таш-Көмүр", "Майлуу-Суу", "Ала-Бука", "Аксы", "Чаткал", "Тогуз-Торо"],
    "Нарын облусу": ["Нарын", "Ат-Башы", "Ак-Талаа", "Жумгал", "Кочкор"],
    "Ош облусу": ["Ош", "Кара-Суу", "Араван", "Ноокат", "Өзгөн", "Кара-Кулжа", "Алай", "Чоң-Алай"],
    "Талас облусу": ["Талас", "Бакай-Ата", "Кара-Буура", "Манас району"],
    "Чүй облусу": ["Жайыл", "Токмок", "Кемин"],
    "Ысык-Көл облусу": ["Каракол", "Балыкчы", "Чолпон-Ата", "Түп", "Ак-Суу", "Жети-Өгүз", "Тоң"]
}

region_list = list(regions.keys())
city_map = {}

def build_maps():
    ci = 0
    for region_name, cities in regions.items():
        for city_name in cities:
            ci += 1
            city_map[str(ci)] = (city_name, region_name)

build_maps()

def get_city_num(city_name):
    for num, (name, _) in city_map.items():
        if name == city_name:
            return num
    return None

# ================= DB =================
DB_PATH = os.getenv("DB_PATH", "taxi.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn, conn.cursor()

def init_db():
    conn, c = get_db()
    c.execute("""
    CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, car TEXT,
        from_city TEXT, to_city TEXT,
        time TEXT, price TEXT,
        phone TEXT, seats TEXT,
        comment TEXT, created_at REAL
    )
    """)
    conn.commit()
    conn.close()

def clean_old_records():
    conn, c = get_db()
    cutoff = time.time() - 43200  # 12 саат
    c.execute("DELETE FROM drivers WHERE created_at < ?", (cutoff,))
    conn.commit()
    conn.close()

def auto_clean_loop():
    while True:
        time.sleep(3600)
        clean_old_records()

# ================= USER STATE =================
user_data = {}

def set_data(uid, k, v):
    user_data.setdefault(uid, {})[k] = v

def get_data(uid):
    return user_data.get(uid, {})

def reset(uid):
    user_data.pop(uid, None)

def set_state(uid, state):
    set_data(uid, "state", state)

def get_state(uid):
    return get_data(uid).get("state")

# ================= GREEN API =================
def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage/{API_TOKEN}"
    payload = {"chatId": chat_id, "message": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def receive_notification():
    url = f"{BASE_URL}/receiveNotification/{API_TOKEN}"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Receive error: {e}")
    return None

def delete_notification(receipt_id):
    url = f"{BASE_URL}/deleteNotification/{API_TOKEN}/{receipt_id}"
    try:
        requests.delete(url, timeout=10)
    except Exception as e:
        print(f"Delete error: {e}")

# ================= MENU =================
MAIN_MENU = (
    "🚕 Такси бот — Кош келиңиз!\n\n"
    "Тандаңыз:\n"
    "1️⃣ — 🚗 Айдоочумун\n"
    "2️⃣ — 🔍 Жүргүнчүмүн"
)

def send_main_menu(chat_id):
    send_message(chat_id, MAIN_MENU)

def regions_menu():
    lines = ["🗺 Облус тандаңыз (номер жазыңыз):\n"]
    for i, name in enumerate(region_list, 1):
        lines.append(f"{i}. {name}")
    return "\n".join(lines)

def cities_menu(region_name):
    cities = regions.get(region_name, [])
    lines = [f"📍 {region_name}\nШаар тандаңыз (номер жазыңыз):\n"]
    for i, city in enumerate(cities, 1):
        lines.append(f"{i}. {city}")
    return "\n".join(lines)

# ================= DRIVER FLOW =================
def handle_driver_flow(chat_id, text, state, data):
    if state == "d_name":
        set_data(chat_id, "name", text)
        set_state(chat_id, "d_car")
        send_message(chat_id, "🚘 Машинаңыздын маркасы жана модели:")

    elif state == "d_car":
        set_data(chat_id, "car", text)
        set_state(chat_id, "d_route")
        send_message(chat_id, "Маршрут тандаңыз:\n1️⃣ — 🏙 Бишкекке барам\n2️⃣ — 🌄 Бишкектен кетем")

    elif state == "d_route":
        if text == "1":
            set_data(chat_id, "to", "Бишкек")
            set_state(chat_id, "d_from_region")
            send_message(chat_id, regions_menu())
        elif text == "2":
            set_data(chat_id, "from", "Бишкек")
            set_state(chat_id, "d_to_region")
            send_message(chat_id, regions_menu())
        else:
            send_message(chat_id, "❗ 1 же 2 жазыңыз.")

    elif state == "d_from_region":
        try:
            idx = int(text) - 1
            region = region_list[idx]
            set_data(chat_id, "d_region", region)
            set_state(chat_id, "d_from_city")
            send_message(chat_id, cities_menu(region))
        except (ValueError, IndexError):
            send_message(chat_id, "❗ Туура номер жазыңыз.")

    elif state == "d_from_city":
        region = data.get("d_region")
        cities = regions.get(region, [])
        try:
            idx = int(text) - 1
            city = cities[idx]
            set_data(chat_id, "from", city)
            set_state(chat_id, "d_time")
            send_message(chat_id, "⏰ Качан жолго чыгасыз:")
        except (ValueError, IndexError):
            send_message(chat_id, "❗ Туура номер жазыңыз.")

    elif state == "d_to_region":
        try:
            idx = int(text) - 1
            region = region_list[idx]
            set_data(chat_id, "d_region", region)
            set_state(chat_id, "d_to_city")
            send_message(chat_id, cities_menu(region))
        except (ValueError, IndexError):
            send_message(chat_id, "❗ Туура номер жазыңыз.")

    elif state == "d_to_city":
        region = data.get("d_region")
        cities = regions.get(region, [])
        try:
            idx = int(text) - 1
            city = cities[idx]
            set_data(chat_id, "to", city)
            set_state(chat_id, "d_time")
            send_message(chat_id, "⏰ Качан жолго чыгасыз:")
        except (ValueError, IndexError):
            send_message(chat_id, "❗ Туура номер жазыңыз.")

    elif state == "d_time":
        set_data(chat_id, "time", text)
        set_state(chat_id, "d_price")
        send_message(chat_id, "💰 Жол кире акы (сом):")

    elif state == "d_price":
        set_data(chat_id, "price", text)
        set_state(chat_id, "d_seats")
        send_message(chat_id, "🪑 Бош орун саны:")

    elif state == "d_seats":
        set_data(chat_id, "seats", text)
        set_state(chat_id, "d_phone")
        send_message(chat_id, "📱 Телефон номериңиз:")

    elif state == "d_phone":
        set_data(chat_id, "phone", text)
        set_state(chat_id, "d_comment")
        send_message(chat_id, "💬 Комментарий (болбосо — сызыкча коюңуз):")

    elif state == "d_comment":
        set_data(chat_id, "comment", text)
        finish_driver(chat_id)

def finish_driver(chat_id):
    data = get_data(chat_id)
    required = ["name", "car", "from", "to", "time", "price", "phone", "seats"]
    for field in required:
        if field not in data:
            send_message(chat_id, "❌ Маалымат жетишсиз. Кайрадан баштаңыз.")
            reset(chat_id)
            send_main_menu(chat_id)
            return

    clean_old_records()

    post_text = (
        "🚗 *АЙДООЧУ*\n\n"
        f"👤 Аты: {data['name']}\n"
        f"🚘 Машина: {data['car']}\n"
        f"📍 Маршрут: {data['from']} → {data['to']}\n"
        f"⏰ Убакыт: {data['time']}\n"
        f"💰 Баа: {data['price']} сом\n"
        f"🪑 Бош орун: {data['seats']}\n"
        f"📞 Тел: {data['phone']}\n"
        f"💬 Комментарий: {data.get('comment', '-')}"
    )

    # Группага жибер (эгер GROUP_ID орнотулган болсо)
    if GROUP_ID:
        send_message(GROUP_ID, post_text)

    # DB га сакта
    conn, c = get_db()
    c.execute("""
        INSERT INTO drivers (name,car,from_city,to_city,time,price,phone,seats,comment,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        data["name"], data["car"],
        data["from"], data["to"],
        data["time"], data["price"],
        data["phone"], data["seats"],
        data.get("comment", "-"), time.time()
    ))
    conn.commit()
    conn.close()

    send_message(chat_id, "✅ Маалыматыңыз жазылды!")
    reset(chat_id)
    send_main_menu(chat_id)

# ================= PASSENGER FLOW =================
def handle_passenger_flow(chat_id, text, state, data):
    if state == "p_route":
        if text == "1":
            set_state(chat_id, "p_to_region")
            send_message(chat_id, regions_menu())
        elif text == "2":
            set_state(chat_id, "p_from_region")
            send_message(chat_id, regions_menu())
        else:
            send_message(chat_id, "❗ 1 же 2 жазыңыз.")

    elif state == "p_to_region":
        try:
            idx = int(text) - 1
            region = region_list[idx]
            city_list = regions[region]
            clean_old_records()
            search_drivers(chat_id, from_cities=city_list, region_name=region)
            reset(chat_id)
            send_main_menu(chat_id)
        except (ValueError, IndexError):
            send_message(chat_id, "❗ Туура номер жазыңыз.")

    elif state == "p_from_region":
        try:
            idx = int(text) - 1
            region = region_list[idx]
            city_list = regions[region]
            clean_old_records()
            search_drivers(chat_id, to_cities=city_list, region_name=region)
            reset(chat_id)
            send_main_menu(chat_id)
        except (ValueError, IndexError):
            send_message(chat_id, "❗ Туура номер жазыңыз.")

# ================= SEARCH =================
def search_drivers(chat_id, from_cities=None, to_cities=None, region_name=""):
    conn, c = get_db()

    if from_cities:
        placeholders = ",".join("?" * len(from_cities))
        c.execute(
            f"SELECT * FROM drivers WHERE from_city IN ({placeholders}) AND to_city='Бишкек'",
            from_cities
        )
        header = f"🔍 {region_name} → Бишкек:"
    elif to_cities:
        placeholders = ",".join("?" * len(to_cities))
        c.execute(
            f"SELECT * FROM drivers WHERE from_city='Бишкек' AND to_city IN ({placeholders})",
            to_cities
        )
        header = f"🔍 Бишкек → {region_name}:"
    else:
        conn.close()
        return

    rows = c.fetchall()
    conn.close()

    if not rows:
        send_message(chat_id, "❌ Азырынча айдоочу табылган жок.\nКийинчерээк кайра текшериңиз.")
        return

    send_message(chat_id, f"{header}\n✅ {len(rows)} айдоочу табылды")

    grouped = defaultdict(list)
    for r in rows:
        key = r[3] if from_cities else r[4]
        grouped[key].append(r)

    for city_key, drivers in grouped.items():
        for r in drivers:
            text = (
                f"🚗 АЙДООЧУ\n\n"
                f"👤 Аты: {r[1]}\n"
                f"🚘 Машина: {r[2]}\n"
                f"📍 Маршрут: {r[3]} → {r[4]}\n"
                f"⏰ Убакыт: {r[5]}\n"
                f"💰 Баа: {r[6]} сом\n"
                f"🪑 Орун: {r[8]}\n"
                f"📞 Тел: {r[7]}\n"
                f"💬 Комментарий: {r[9]}"
            )
            send_message(chat_id, text)

# ================= MESSAGE HANDLER =================
def handle_message(chat_id, text):
    text = text.strip()
    state = get_state(chat_id)
    data = get_data(chat_id)

    # Каалаган убакта баштан баштоо
    if text.lower() in ["старт", "start", "баштоо", "меню", "menu", "/start"]:
        reset(chat_id)
        send_main_menu(chat_id)
        return

    # Башкы меню
    if state is None:
        if text == "1":
            reset(chat_id)
            set_state(chat_id, "d_name")
            send_message(chat_id, "👤 Атыңыз:")
        elif text == "2":
            reset(chat_id)
            set_state(chat_id, "p_route")
            send_message(chat_id, "Маршрут тандаңыз:\n1️⃣ — 🏙 Бишкекке барам\n2️⃣ — 🌄 Бишкектен кетем")
        else:
            send_main_menu(chat_id)
        return

    # Айдоочу flow
    if state.startswith("d_"):
        handle_driver_flow(chat_id, text, state, data)
        return

    # Жүргүнчү flow
    if state.startswith("p_"):
        handle_passenger_flow(chat_id, text, state, data)
        return

# ================= MAIN LOOP =================
def main():
    init_db()
    threading.Thread(target=auto_clean_loop, daemon=True).start()
    print("✅ WhatsApp Такси Бот иштеп жатат...")

    while True:
        notification = receive_notification()
        if not notification:
            time.sleep(1)
            continue

        receipt_id = notification.get("receiptId")
        body = notification.get("body", {})

        try:
            type_webhook = body.get("typeWebhook")

.   if type_webhook in ("outgoingMessageReceived", "outgoingAPIMessageReceived"):
    delete_notification(receipt_id)
    continue
    if type_webhook == "incomingMessageReceived":
                sender = body.get("senderData", {})
                chat_id = sender.get("chatId")
                msg_data = body.get("messageData", {})
                msg_type = msg_data.get("typeMessage")

                if msg_type == "textMessage":
                    text = msg_data.get("textMessageData", {}).get("textMessage", "")
                    if chat_id and text:
                        handle_message(chat_id, text)

        except Exception as e:
            print(f"Handler error: {e}")
        finally:
            if receipt_id:
                delete_notification(receipt_id)

if __name__ == "__main__":
    main()
