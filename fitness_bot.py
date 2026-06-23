import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command

API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

DATA_FILE = 'fitness_data.json'
USERS_FILE = 'users.json'

goals_buffer = {}
goal_input_buffer = {}
profile_input_buffer = {}

# --- Загрузка и сохранение данных ---

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def log_user(user):
    users = load_users()
    found = False
    for u in users:
        if u["id"] == user["id"]:
            u["last_active"] = user.get("last_active", u.get("last_active"))
            found = True
            break
    if not found:
        users.append(user)
    save_users(users)

def get_logged_users():
    return load_users()

def get_weights(workout):
    """Обратная совместимость: старые записи хранят 'weight' (число), новые — 'weights' (список)."""
    if 'weights' in workout:
        return workout['weights']
    elif 'weight' in workout:
        w = workout['weight']
        return [w] if isinstance(w, (int, float)) else []
    return []

def calc_session_volume(workout):
    """Общий объём нагрузки: подходы × повторения × средний вес."""
    weights = get_weights(workout)
    if not weights:
        return 0.0
    return workout['sets'] * workout['reps'] * (sum(weights) / len(weights))

# Словарь упражнений → мышечная группа (поиск по подстроке)
MUSCLE_GROUPS = {
    "жим лёжа": "грудь", "жим лежа": "грудь", "жим гантелей": "грудь",
    "разводка": "грудь", "отжимания": "грудь", "кроссовер": "грудь", "бабочка": "грудь",
    "подтягивания": "спина", "вертикальная тяга": "спина",
    "тяга верхнего блока": "спина", "тяга нижнего блока": "спина",
    "горизонтальная тяга": "спина", "тяга штанги": "спина",
    "тяга гантели": "спина", "гиперэкстензия": "спина",
    "армейский жим": "плечи", "жим над головой": "плечи",
    "жим арнольда": "плечи", "махи": "плечи", "тяга к подбородку": "плечи",
    "приседания": "ноги", "приседание в смите": "ноги",
    "жим ногами": "ноги", "жим платформы": "ноги",
    "болгарский": "ноги", "выпады": "ноги",
    "разгибания ног": "ноги", "сгибания ног": "ноги",
    "ягодичный мост": "ягодицы",
    "сгибания с гантелями": "бицепс", "подъём штанги на бицепс": "бицепс",
    "молотки": "бицепс",
    "разгибания с косичкой": "трицепс", "жим узким хватом": "трицепс",
    "французский жим": "трицепс", "разгибания на блоке": "трицепс", "разгибания": "трицепс",
    "скручивания": "пресс", "планка": "пресс", "подъём ног": "пресс",
}

def get_muscle_group(exercise_name):
    name = exercise_name.lower().strip()
    for key, group in MUSCLE_GROUPS.items():
        if key in name or name in key:
            return group
    return None

def calc_bmi(weight_kg, height_cm):
    if not weight_kg or not height_cm or height_cm <= 0:
        return None
    h = height_cm / 100
    return round(weight_kg / (h * h), 1)

def bmi_category(bmi):
    if bmi < 18.5:
        return "недостаточный вес"
    elif bmi < 25.0:
        return "норма"
    elif bmi < 30.0:
        return "избыточный вес"
    else:
        return "ожирение"

async def init_user(user_id):
    data = load_data()
    if str(user_id) not in data:
        data[str(user_id)] = {
            "goal": "не указана",
            "height": None,
            "weight": None,
            "volume": None,
            "workouts": []
        }
        save_data(data)

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить тренировку")],
            [KeyboardButton(text="История"), KeyboardButton(text="Прогресс")],
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Цель")],
            [KeyboardButton(text="Удалить последнюю"), KeyboardButton(text="Пользователи")]
        ],
        resize_keyboard=True
    )

def get_motivation_message(change):
    if change > 0:
        return "Отличный результат! Ты прогрессируешь 💪 Продолжай в том же духе!"
    elif change == 0:
        return "Ты держишь планку, и это уже победа! Не сдавайся, прогресс всегда впереди."
    else:
        return "Бывают откаты, но это часть пути. Главное — не останавливаться!"

def make_user_info(message):
    return {
        "id": message.from_user.id,
        "name": message.from_user.full_name,
        "username": message.from_user.username,
        "last_active": int(time.time())
    }

def clear_user_buffers(user_id):
    goal_input_buffer.pop(user_id, None)
    profile_input_buffer.pop(user_id, None)

# --- Обработчики ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await init_user(message.from_user.id)
    log_user(make_user_info(message))
    await message.answer(
        "Привет! Я твой фитнес-бот 💪\n\n"
        "Подсказка: в любой момент введите /cancel или «Отмена», чтобы прервать ввод.",
        reply_markup=get_main_menu()
    )

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    clear_user_buffers(message.from_user.id)
    await message.answer("Действие отменено.", reply_markup=get_main_menu())

@dp.message(lambda m: m.text == "Отмена")
async def text_cancel(message: Message):
    clear_user_buffers(message.from_user.id)
    await message.answer("Действие отменено.", reply_markup=get_main_menu())

@dp.message(lambda m: m.text == "Цель")
async def ask_goal_type(message: Message):
    log_user(make_user_info(message))
    goal_input_buffer[message.from_user.id] = {"step": 1}
    await message.answer(
        "Выберите тип цели:\n"
        "1 - Вес (кг)\n"
        "2 - Объёмы тела (см)\n\n"
        "Отправьте /cancel для отмены."
    )

@dp.message(lambda m: m.text == "Добавить тренировку")
async def add_workout(message: Message):
    log_user(make_user_info(message))
    await message.answer(
        "Введите тренировку в формате:\n"
        "Упражнение, Подходы, Повторения, веса через пробел\n"
        "Например:\nЖим лежа, 4, 10, 70 75 80 85\n"
        "где 70 75 80 85 — веса для каждого из 4 подходов"
    )

@dp.message(lambda m: m.text == "Удалить последнюю")
async def delete_last_workout(message: Message):
    log_user(make_user_info(message))
    user_id = message.from_user.id
    data = load_data()
    uid = str(user_id)
    if uid not in data or not data[uid]['workouts']:
        await message.answer("История тренировок пуста — нечего удалять.")
        return
    removed = data[uid]['workouts'].pop()
    save_data(data)
    weights = get_weights(removed)
    weights_str = ' '.join(str(w) for w in weights) if weights else '—'
    await message.answer(
        f"Удалена последняя тренировка:\n"
        f"{removed['date']}: {removed['exercise']} — {removed['sets']}x{removed['reps']}, веса: {weights_str} кг",
        reply_markup=get_main_menu()
    )

@dp.message(lambda m: m.text == "Пользователи")
async def show_users(message: Message):
    log_user(make_user_info(message))
    users = get_logged_users()
    if not users:
        await message.answer("Пока никто не заходил.")
        return
    text = "Пользователи бота:\n\n"
    for u in users:
        text += f"id: {u['id']} | {u['name']}" + (f" | @{u['username']}" if u['username'] else "") + "\n"
    await message.answer(text)

@dp.message(lambda m: m.text == "Профиль")
async def show_profile(message: Message):
    log_user(make_user_info(message))
    user_id = message.from_user.id
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        await init_user(user_id)
        data = load_data()
    profile = data[uid]

    goal = profile.get("goal")
    goal_str = "не указана"
    if isinstance(goal, dict):
        unit = "кг" if goal.get("type") == "weight" else "см"
        goal_str = f"{goal.get('value')} {unit}"
    elif isinstance(goal, str):
        goal_str = goal

    weight_val = profile.get("weight")
    height_val = profile.get("height")
    bmi_str = ""
    bmi = calc_bmi(weight_val, height_val)
    if bmi is not None:
        bmi_str = f"\nИМТ: {bmi} ({bmi_category(bmi)})"

    text = (
        f"Ваш профиль:\n"
        f"Цель: {goal_str}\n"
        f"1. Вес: {weight_val or 'не указан'} кг\n"
        f"2. Объёмы тела: {profile.get('volume') or 'не указаны'} см\n"
        f"3. Рост: {height_val or 'не указан'} см"
        f"{bmi_str}\n\n"
        "Введите 1, 2 или 3, чтобы изменить соответствующее значение.\n"
        "Отправьте /cancel для отмены."
    )
    profile_input_buffer[user_id] = {"step": 1}
    await message.answer(text)

@dp.message()
async def universal_handler(message: Message):
    user_id = message.from_user.id
    text = message.text

    log_user(make_user_info(message))

    # Обработка ввода цели
    if user_id in goal_input_buffer:
        step_info = goal_input_buffer[user_id]
        if step_info["step"] == 1:
            if text not in ("1", "2"):
                await message.answer("Пожалуйста, введите 1 (Вес) или 2 (Объёмы тела), или /cancel для отмены.")
                return
            step_info["type"] = "weight" if text == "1" else "volume"
            step_info["step"] = 2
            goal_input_buffer[user_id] = step_info
            unit = "кг" if step_info["type"] == "weight" else "см"
            await message.answer(f"Введите желаемое значение цели ({unit}):")
            return
        if step_info["step"] == 2:
            try:
                val = float(text)
            except ValueError:
                await message.answer("Введите числовое значение, пожалуйста.")
                return
            data = load_data()
            uid = str(user_id)
            if uid not in data:
                await init_user(user_id)
                data = load_data()
            data[uid]["goal"] = {"type": step_info["type"], "value": val}
            save_data(data)
            del goal_input_buffer[user_id]
            unit = "кг" if step_info["type"] == "weight" else "см"
            await message.answer(f"Цель сохранена: {val} {unit}", reply_markup=get_main_menu())
            return

    # Обработка ввода профиля
    if user_id in profile_input_buffer:
        step_info = profile_input_buffer[user_id]
        if step_info.get("step") == 1:
            type_map = {"1": "weight", "2": "volume", "3": "height"}
            if text not in type_map:
                await message.answer("Пожалуйста, введите 1, 2 или 3, или /cancel для отмены.")
                return
            step_info["type"] = type_map[text]
            step_info["step"] = 2
            profile_input_buffer[user_id] = step_info
            unit = "кг" if step_info["type"] == "weight" else "см"
            await message.answer(f"Введите новое значение ({unit}):")
            return
        elif step_info.get("step") == 2:
            try:
                val = float(text)
            except ValueError:
                await message.answer("Введите числовое значение, пожалуйста.")
                return
            data = load_data()
            uid = str(user_id)
            if uid not in data:
                await init_user(user_id)
                data = load_data()
            field_map = {"weight": "weight", "volume": "volume", "height": "height"}
            label_map = {"weight": "Вес", "volume": "Объёмы тела", "height": "Рост"}
            unit_map = {"weight": "кг", "volume": "см", "height": "см"}
            t = step_info["type"]
            data[uid][field_map[t]] = val
            save_data(data)
            del profile_input_buffer[user_id]

            # Пересчитать ИМТ если данные есть
            profile = data[uid]
            bmi_note = ""
            bmi = calc_bmi(profile.get("weight"), profile.get("height"))
            if bmi is not None:
                bmi_note = f"\nВаш ИМТ: {bmi} ({bmi_category(bmi)})"

            await message.answer(
                f"{label_map[t]} обновлён: {val} {unit_map[t]}{bmi_note}",
                reply_markup=get_main_menu()
            )
            return

    # Ввод тренировки с весами
    if text and ',' in text:
        parts = [p.strip() for p in text.split(',')]
        if len(parts) != 4:
            await message.answer("Неверный формат! Используйте: Упражнение, Подходы, Повторения, веса через пробел")
            return
        try:
            exercise = parts[0]
            sets = int(parts[1])
            reps = int(parts[2])
            weights_list = [float(w) for w in parts[3].strip().split()]
            if len(weights_list) != sets:
                await message.answer(
                    f"Ошибка: количество весов ({len(weights_list)}) не совпадает с количеством подходов ({sets})"
                )
                return
        except Exception:
            await message.answer("Ошибка! Проверьте формат и числа. Пример:\nЖим лежа, 4, 10, 70 75 80 85")
            return
        data = load_data()
        uid = str(user_id)
        if uid not in data:
            await init_user(user_id)
            data = load_data()
        workout_entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "exercise": exercise,
            "sets": sets,
            "reps": reps,
            "weights": weights_list
        }
        data[uid]['workouts'].append(workout_entry)
        save_data(data)
        max_weight = max(weights_list)
        recommendation = generate_recommendation(data, uid, exercise, weights_list, sets, reps)
        await message.answer(
            f"Тренировка '{exercise}' добавлена.\nРекомендация: {recommendation}",
            reply_markup=get_main_menu()
        )
        return

    # История (с фильтром по упражнению: «История Жим лёжа»)
    if text == "История" or (text and text.lower().startswith("история ")):
        data = load_data()
        uid = str(user_id)
        if uid not in data or not data[uid]['workouts']:
            await message.answer("История тренировок пуста.")
            return

        exercise_filter = None
        if text.lower().startswith("история "):
            exercise_filter = text[len("история "):].strip()

        workouts = data[uid]['workouts']
        if exercise_filter:
            workouts = [w for w in workouts if exercise_filter.lower() in w['exercise'].lower()]
            if not workouts:
                await message.answer(f"Тренировки с упражнением «{exercise_filter}» не найдены.")
                return

        last = workouts[-5:]
        lines = []
        for w in last:
            weights = get_weights(w)
            weights_str = ' '.join(str(wt) for wt in weights) if weights else '—'
            lines.append(f"{w['date']}: {w['exercise']} — {w['sets']}x{w['reps']}, веса: {weights_str} кг")

        hint = "\n\nДля поиска по упражнению отправьте: «История Жим лёжа»" if not exercise_filter else ""
        title = f"Последние тренировки — {exercise_filter}:\n\n" if exercise_filter else "Последние тренировки:\n\n"
        await message.answer(title + "\n\n".join(lines) + hint)
        return

    # Прогресс
    if text == "Прогресс":
        data = load_data()
        uid = str(user_id)
        if uid not in data or not data[uid]['workouts']:
            await message.answer("Недостаточно данных для анализа прогресса.")
            return

        by_exercise = {}
        for w in data[uid]['workouts']:
            ex = w['exercise']
            weights = get_weights(w)
            if not weights:
                continue
            by_exercise.setdefault(ex, []).append(max(weights))

        if not by_exercise:
            await message.answer("Недостаточно данных для анализа прогресса.")
            return

        report = []
        for ex, weights in by_exercise.items():
            if len(weights) > 1:
                change = weights[-1] - weights[0]
                motivation = get_motivation_message(change)
                report.append(f"{ex}: изменение {change:+.1f} кг\n{motivation}")
            else:
                report.append(f"{ex}: только одна тренировка\nБудет прогресс — будет мотивация! 😉")

        # Прогресс к цели
        profile = data[uid]
        goal = profile.get("goal")
        goal_section = ""
        if isinstance(goal, dict):
            goal_type = goal.get("type")
            goal_value = goal.get("value")
            if goal_type == "weight":
                current = profile.get("weight")
                if current is not None and goal_value is not None:
                    diff = goal_value - current
                    arrow = "⬇️" if diff < 0 else "⬆️"
                    goal_section = (
                        f"\n\n🎯 Цель по весу: {goal_value} кг\n"
                        f"Текущий вес: {current} кг\n"
                        f"Осталось: {arrow} {abs(diff):.1f} кг"
                    )
            elif goal_type == "volume":
                current = profile.get("volume")
                if current is not None and goal_value is not None:
                    diff = goal_value - current
                    arrow = "⬇️" if diff < 0 else "⬆️"
                    goal_section = (
                        f"\n\n🎯 Цель по объёмам: {goal_value} см\n"
                        f"Текущие объёмы: {current} см\n"
                        f"Осталось: {arrow} {abs(diff):.1f} см"
                    )

        # Анализ баланса мышечных групп
        muscle_counts = {}
        for ex, weights in by_exercise.items():
            group = get_muscle_group(ex)
            if group:
                muscle_counts[group] = muscle_counts.get(group, 0) + len(weights)

        balance_note = ""
        if len(muscle_counts) >= 2:
            max_group = max(muscle_counts, key=muscle_counts.get)
            min_group = min(muscle_counts, key=muscle_counts.get)
            if muscle_counts[max_group] >= 3 * muscle_counts[min_group]:
                balance_note = (
                    f"\n\n⚖️ Дисбаланс нагрузки: «{max_group}» тренируется значительно больше, "
                    f"чем «{min_group}» — рассмотрите более равномерное распределение."
                )

        await message.answer("Ваш прогресс:\n\n" + "\n\n".join(report) + goal_section + balance_note)
        return

    await message.answer("Пожалуйста, используйте меню для навигации.", reply_markup=get_main_menu())

def generate_recommendation(data, user_id, exercise, weights_list, sets, reps):
    ex_workouts = [w for w in data[user_id]['workouts'] if w['exercise'].lower() == exercise.lower()]
    goal = data[user_id].get('goal')
    goal_type = goal.get('type') if isinstance(goal, dict) else None
    tips = []

    # 1. Прогрессия нагрузки
    if len(ex_workouts) == 1:
        tips.append("Первая тренировка по этому упражнению — хорошее начало!")
    else:
        max_hist = [max(get_weights(w) or [0]) for w in ex_workouts]
        delta = max_hist[-1] - max_hist[-2]

        if delta > 0:
            streak = 0
            for i in range(len(max_hist) - 1, 0, -1):
                if max_hist[i] > max_hist[i - 1]:
                    streak += 1
                else:
                    break
            if streak >= 3:
                tips.append(f"Вес растёт {streak} тренировки подряд — отличная прогрессия! 🔥")
            else:
                tips.append(f"Добавили {delta:.1f} кг к максимуму — прогресс есть! 💪")
        elif delta == 0:
            flat = 0
            for i in range(len(max_hist) - 1, 0, -1):
                if max_hist[i] == max_hist[i - 1]:
                    flat += 1
                else:
                    break
            if flat >= 2:
                tips.append(f"Вес не меняется {flat + 1} тренировки подряд — попробуйте добавить 2.5 кг или увеличить повторения.")
            else:
                tips.append("Нагрузка не изменилась — в следующий раз попробуйте прибавить немного.")
        else:
            tips.append(f"Максимальный вес снизился на {abs(delta):.1f} кг — проверьте восстановление и сон.")

    # 2. Объём нагрузки (tonnage)
    if len(ex_workouts) >= 2:
        cur_vol = calc_session_volume(ex_workouts[-1])
        prev_vol = calc_session_volume(ex_workouts[-2])
        if prev_vol > 0:
            ratio = cur_vol / prev_vol
            if ratio > 1.15:
                tips.append(f"Объём нагрузки вырос на {(ratio - 1) * 100:.0f}% — уделите внимание восстановлению.")
            elif ratio < 0.85:
                tips.append(f"Объём нагрузки упал на {(1 - ratio) * 100:.0f}% — стоит проверить технику или добавить подход.")

    # 3. Диапазон повторений относительно цели
    if goal_type == "weight":  # похудение: нужны высокие повторения
        if reps < 10:
            tips.append("Для жиросжигания эффективнее 12–15 повторений с меньшим весом.")
        elif reps > 20:
            tips.append("Очень высокое число повторений — убедитесь, что нагрузка достаточна для прогресса.")
    elif goal_type == "volume":  # набор мышц: гипертрофийный диапазон
        if reps < 6:
            tips.append("Для набора мышечного объёма оптимальный диапазон — 8–12 повторений.")
        elif reps > 15:
            tips.append("Более 15 повторений — скорее выносливость. Для роста мышц попробуйте 8–12 с бо́льшим весом.")

    return " ".join(tips) if tips else "Продолжайте тренироваться и следите за прогрессом!"

# --- Фоновые задачи ---

async def notify_inactive_users():
    while True:
        await asyncio.sleep(12 * 60 * 60)
        users = load_users()
        now = int(time.time())
        threshold = 7 * 24 * 60 * 60
        changed = False
        for user in users:
            last_active = user.get("last_active", 0)
            last_notified = user.get("last_notified", 0)
            if now - last_active > threshold and now - last_notified > threshold:
                try:
                    await bot.send_message(user["id"], "Мы скучаем по вам! Возвращайтесь к тренировкам 😉")
                    user["last_notified"] = now
                    changed = True
                except Exception:
                    pass
        if changed:
            save_users(users)

async def weekly_summary():
    """Каждое воскресенье в 10:00 отправляет пользователям сводку за неделю."""
    while True:
        now = datetime.now()
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 10:
            days_until_sunday = 7
        next_sunday = (now + timedelta(days=days_until_sunday)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        wait_seconds = (next_sunday - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        users = get_logged_users()
        data = load_data()
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
        for user in users:
            uid = str(user['id'])
            if uid not in data:
                continue
            week_workouts = [w for w in data[uid]['workouts'] if w['date'] >= week_ago]
            if not week_workouts:
                continue
            exercises = list(dict.fromkeys(w['exercise'] for w in week_workouts))
            ex_list = ", ".join(exercises[:5]) + ("..." if len(exercises) > 5 else "")
            try:
                await bot.send_message(
                    user['id'],
                    f"📊 Итоги недели:\n"
                    f"Тренировок: {len(week_workouts)}\n"
                    f"Упражнений: {len(exercises)}\n"
                    f"{ex_list}\n\n"
                    f"Отличная работа! Продолжайте в том же духе 💪"
                )
            except Exception:
                pass

async def main():
    asyncio.create_task(notify_inactive_users())
    asyncio.create_task(weekly_summary())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
