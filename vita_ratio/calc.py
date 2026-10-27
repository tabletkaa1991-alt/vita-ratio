"""Доменная математика Vita Ratio: цели КБЖУ, план питания, сон, расписание.

Все функции чистые (без БД и сети) — их используют сервер, бот и тесты.
Время суток — строки "HH:MM", даты — "YYYY-MM-DD", weekday 0=понедельник … 6=воскресенье.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta, timezone, tzinfo

# --- словари -----------------------------------------------------------------

ACTIVITY = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "high": 1.725,
    "athlete": 1.9,
}

ACTIVITY_LABELS = {
    "sedentary": "Сидячий (офис, без спорта)",
    "light": "Лёгкая активность (1–2 тренировки)",
    "moderate": "Средняя (3–4 тренировки)",
    "high": "Высокая (5–6 тренировок)",
    "athlete": "Очень высокая (спорт, физический труд)",
}

KIND_LABELS = {"gym": "Тренировка", "study": "Учёба", "other": "Другое"}

WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WEEKDAYS_SHORT_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

KCAL_PER_KG_FAT = 7700.0
LAST_MEAL_BEFORE_BED_MIN = 120        # последний приём — минимум за 2 ч до сна
EATING_AFTER_WAKE_MIN = 30            # завтрак через 30 мин после подъёма
PRE_WORKOUT_MIN = 90                  # перекус за 90 мин до тренировки
POST_WORKOUT_MIN = 30                 # приём после тренировки


# --- время -------------------------------------------------------------------

def time_to_minutes(value: str) -> int:
    """'HH:MM' -> минуты от полуночи. Бросает ValueError на мусоре."""
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) < 2:
        raise ValueError(f"Ожидается время HH:MM, получено: {value!r}")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ValueError(f"Недопустимое время: {value!r}")
    return hours * 60 + minutes


def minutes_to_time(total: int) -> str:
    """минуты -> 'HH:MM' (по модулю суток)."""
    total = int(total) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def add_minutes(value: str, delta: int) -> str:
    """'23:00' + 45 -> '23:45'; переход через полночь поддерживается."""
    return minutes_to_time(time_to_minutes(value) + int(delta))


def duration_between(bed: str, wake: str) -> float:
    """Часы между отходом и подъёмом (точность до минуты), переход через полночь."""
    diff = (time_to_minutes(wake) - time_to_minutes(bed)) % (24 * 60)
    if diff == 0:
        diff = 24 * 60
    return round(diff / 60.0, 2)


def _tz(name: str | None) -> tzinfo:
    if name:
        try:
            from zoneinfo import ZoneInfo  # noqa: WPS433 (stdlib)
            return ZoneInfo(name)
        except Exception:  # на Windows без tzdata — фиксированное смещение
            pass
    # Разумный фолбэк: Москва, UTC+3, без перехода на летнее время.
    return timezone(timedelta(hours=3))


def local_now(tz_name: str | None = "Europe/Moscow") -> datetime:
    return datetime.now(_tz(tz_name)).replace(tzinfo=None)


def local_today(tz_name: str | None = "Europe/Moscow") -> str:
    return local_now(tz_name).date().isoformat()


def parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


# --- цели --------------------------------------------------------------------

@dataclass(frozen=True)
class Targets:
    kcal: int
    protein: int
    fat: int
    carbs: int
    water_ml: int
    surplus_kcal: int
    bmr: int
    tdee: int

    def to_dict(self) -> dict:
        return asdict(self)


def bmr(sex: str, weight_kg: float, height_cm: float, age: float) -> float:
    """Миффлин–Сан Жеор."""
    base = 10.0 * float(weight_kg) + 6.25 * float(height_cm) - 5.0 * float(age)
    return base + (5.0 if str(sex).lower() == "male" else -161.0)


def tdee(sex: str, weight_kg: float, height_cm: float, age: float, activity: str) -> float:
    factor = ACTIVITY.get(str(activity).lower(), ACTIVITY["moderate"])
    return bmr(sex, weight_kg, height_cm, age) * factor


def targets(
    sex: str,
    age: float,
    height_cm: float,
    weight_kg: float,
    activity: str = "moderate",
    goal_rate: float = 0.35,
    protein_per_kg: float = 2.0,
) -> Targets:
    """Цели под набор массы: TDEE + профицит из темпа (кг/нед), белок 1.8–2.2 г/кг."""
    base = bmr(sex, weight_kg, height_cm, age)
    total = base * ACTIVITY.get(str(activity).lower(), ACTIVITY["moderate"])

    rate = max(0.0, min(float(goal_rate), 1.5))
    surplus = rate * KCAL_PER_KG_FAT / 7.0
    surplus = max(0.0, min(surplus, 1200.0))
    kcal = total + surplus

    protein_g = max(float(protein_per_kg), 1.0) * float(weight_kg)
    # жиры: 25% калорий, но не меньше 0.8 г/кг
    fat_g = max(kcal * 0.25 / 9.0, float(weight_kg) * 0.8)
    carbs_g = max(0.0, (kcal - protein_g * 4.0 - fat_g * 9.0) / 4.0)

    return Targets(
        kcal=int(round(kcal)),
        protein=int(round(protein_g)),
        fat=int(round(fat_g)),
        carbs=int(round(carbs_g)),
        water_ml=int(round(float(weight_kg) * 35.0)),
        surplus_kcal=int(round(surplus)),
        bmr=int(round(base)),
        tdee=int(round(total)),
    )


def bmi(weight_kg: float, height_cm: float) -> float:
    height_m = max(float(height_cm), 1.0) / 100.0
    return round(float(weight_kg) / (height_m * height_m), 1)


# --- сон и окно питания -------------------------------------------------------

def sleep_window(bed: str = "23:00", wake: str = "07:00") -> dict:
    """Окно сна + производное окно питания (завтрак -> последний приём до сна)."""
    duration = duration_between(bed, wake)
    eat_start = add_minutes(wake, EATING_AFTER_WAKE_MIN)
    eat_end = add_minutes(bed, -LAST_MEAL_BEFORE_BED_MIN)
    return {
        "bed": bed,
        "wake": wake,
        "duration_h": duration,
        "last_meal_before_bed_min": LAST_MEAL_BEFORE_BED_MIN,
        "eating_window": {"start": eat_start, "end": eat_end},
    }


# --- план питания -------------------------------------------------------------

_PLAN_SHARES = [
    ("Завтрак", 0.0, "breakfast", 0.25),
    ("Обед", 0.38, "lunch", 0.35),
    ("Перекус", 0.62, "snack", 0.10),
    ("Ужин", 0.92, "dinner", 0.30),
]


def meal_plan(
    bed: str = "23:00",
    wake: str = "07:00",
    classes: list[dict] | None = None,
    goal_kcal: float | None = None,
    date_value: str | date | None = None,
) -> list[dict]:
    """План приёмов пищи на день, синхронизированный со сном и тренировкой.

    classes: занятия этого дня (dict с start_time, duration_min, kind).
    Возвращает слоты {"time","title","share","kcal","tag"} по возрастанию времени.
    Если goal_kcal не задан — kcal=None.
    """
    window = sleep_window(bed, wake)
    start_min = time_to_minutes(window["eating_window"]["start"])
    end_min = time_to_minutes(window["eating_window"]["end"])
    if end_min <= start_min:
        end_min += 24 * 60
    if end_min - start_min < 240:                      # слишком узкое окно
        end_min = start_min + 240
    span = end_min - start_min

    slots: list[dict] = []
    for title, fraction, tag, share in _PLAN_SHARES:
        position = start_min + int(round(span * fraction))
        slots.append({"time": minutes_to_time(position), "title": title, "share": share, "kcal": None, "tag": tag})

    gym = _first_gym(classes)
    if gym is not None:
        gym_start = time_to_minutes(gym.get("start_time", "18:00"))
        gym_duration = int(gym.get("duration_min") or 60)
        pre_time = gym_start - PRE_WORKOUT_MIN

        if pre_time > start_min:
            slots = [s for s in slots if s["tag"] != "snack"]
            slots.append({
                "time": minutes_to_time(pre_time),
                "title": "Перекус перед тренировкой",
                "share": 0.10,
                "kcal": None,
                "tag": "pre_workout",
            })

        # ужин после тренировки (если она вечером), иначе оставляем ужин в окне
        post_time = gym_start + gym_duration + POST_WORKOUT_MIN
        dinner = next((s for s in slots if s["tag"] == "dinner"), None)
        if dinner is not None and gym_start >= start_min + 3 * 60:
            dinner["time"] = minutes_to_time(post_time)
            dinner["share"] = max(dinner["share"], 0.25)

    # нормализовать доли, чтобы сумма = 1.0
    total_share = sum(s["share"] for s in slots) or 1.0
    for slot in slots:
        slot["share"] = round(slot["share"] / total_share, 4)
        if goal_kcal:
            slot["kcal"] = int(round(float(goal_kcal) * slot["share"]))

    slots.sort(key=lambda s: time_to_minutes(s["time"]))
    return slots


def _first_gym(classes: list[dict] | None) -> dict | None:
    for item in classes or []:
        data = dict(item) if not isinstance(item, dict) else item
        if str(data.get("kind", "")).lower() == "gym":
            return data
    return None


# --- инсайты ------------------------------------------------------------------

def day_insights(profile: dict, day: dict, targets_obj: Targets | None = None) -> list[str]:
    """Короткие советы по дню: недобор/перебор, белок, сон, пропущенные занятия."""
    if not profile:
        return []
    if targets_obj is None:
        targets_obj = targets(
            profile.get("sex", "male"),
            profile.get("age", 25),
            profile.get("height_cm", 175),
            profile.get("weight_kg", 70),
            profile.get("activity", "moderate"),
            profile.get("goal_rate", 0.35),
            profile.get("protein_per_kg", 2.0),
        )

    tips: list[str] = []
    kcal = float(day.get("kcal") or 0)
    protein = float(day.get("protein") or 0)
    goal_kcal = float(targets_obj.kcal)

    if kcal > 0:
        if kcal < goal_kcal * 0.85:
            tips.append(f"Недобор {int(goal_kcal - kcal)} ккал до цели — добавь перекус: творог, орехи или гейнер.")
        elif kcal > goal_kcal * 1.15:
            tips.append(f"Перебор {int(kcal - goal_kcal)} ккал — для чистого набора чуть сбавь порции.")

    if protein > 0 and protein < targets_obj.protein * 0.85:
        tips.append(f"Белка не хватает {int(targets_obj.protein - protein)} г — яйца, творог, курица, рыба.")

    sleep_h = day.get("sleep_h")
    if sleep_h is not None:
        if sleep_h < 7.0:
            tips.append(f"Сон {sleep_h:.1f} ч — для роста мышц нужно 7–9 ч, ложись раньше.")
        elif sleep_h > 9.5:
            tips.append(f"Сон {sleep_h:.1f} ч — много; проверь качество и режим.")

    planned = int(day.get("classes_planned") or 0)
    done = int(day.get("classes_done") or 0)
    if planned and done < planned:
        tips.append(f"Пропущено занятий: {planned - done} — лучше перенести, чем выбросить из режима.")

    if not tips:
        tips.append("Всё по плану — продолжай в том же темпе.")
    return tips[:5]


# --- расписание ---------------------------------------------------------------

def _as_class(item) -> dict:
    return item if isinstance(item, dict) else dict(item)


def occurrences(classes, date_from=None, date_to=None) -> list[dict]:
    """Разворачивает повторяющиеся классы в конкретные даты диапазона."""
    start = parse_date(date_from) if date_from else parse_date(local_today())
    end = parse_date(date_to) if date_to else start
    if end < start:
        start, end = end, start

    result: list[dict] = []
    cursor = start
    while cursor <= end:
        for item in classes or []:
            data = _as_class(item)
            if int(data.get("weekday", -1)) != cursor.weekday():
                continue
            if not int(data.get("active", 1)):
                continue
            result.append({
                "class_id": int(data.get("id", data.get("class_id", 0))),
                "title": data.get("title", ""),
                "kind": data.get("kind", "other"),
                "weekday": cursor.weekday(),
                "date": cursor.isoformat(),
                "start_time": data.get("start_time", "18:00"),
                "duration_min": int(data.get("duration_min", 60)),
                "place": data.get("place", ""),
                "note": data.get("note", ""),
                "status": data.get("status"),
            })
        cursor += timedelta(days=1)
    result.sort(key=lambda o: (o["date"], time_to_minutes(o["start_time"])))
    return result


def next_occurrences(classes, now: datetime | None = None, limit: int = 5) -> list[dict]:
    """Ближайшие вхождения начиная с now (по умолчанию — сейчас)."""
    now = now or local_now()
    horizon = (now + timedelta(days=14)).date().isoformat()
    items = occurrences(classes, now.date().isoformat(), horizon)
    upcoming = []
    for item in items:
        moment = datetime.combine(parse_date(item["date"]), time.fromisoformat(item["start_time"]))
        if moment >= now:
            item = dict(item)
            item["starts_in_min"] = int((moment - now).total_seconds() // 60)
            upcoming.append(item)
        if len(upcoming) >= limit:
            break
    return upcoming


def schedule_summary(occurrences_list: list[dict], done_map: dict | None = None) -> dict:
    """Статистика по вхождениям: всего/посещено/пропущено и по типам."""
    done_map = done_map or {}
    summary = {"total": 0, "done": 0, "missed": 0, "by_kind": {}}
    for item in occurrences_list:
        key = (item.get("class_id"), item.get("date"))
        status = item.get("status") or done_map.get(key)
        kind = item.get("kind", "other")
        bucket = summary["by_kind"].setdefault(kind, {"total": 0, "done": 0, "missed": 0, "minutes": 0})
        summary["total"] += 1
        bucket["total"] += 1
        bucket["minutes"] += int(item.get("duration_min", 60))
        if status == "present":
            summary["done"] += 1
            bucket["done"] += 1
        elif status in ("absent", "moved"):
            summary["missed"] += 1
            bucket["missed"] += 1
    return summary


# --- цель по весу -------------------------------------------------------------

GOAL_DIRECTION_EPS = 0.05


def goal_progress(
    goal_weight_kg: float | None,
    goal_date: str | date | None = None,
    start_weight_kg: float | None = None,
    current_weight_kg: float | None = None,
    today: date | str | None = None,
) -> dict:
    """Прогресс к цели по весу: сколько кг пройдено/осталось и сколько дней до даты."""
    result = {
        "enabled": bool(goal_weight_kg),
        "goal_weight_kg": round(float(goal_weight_kg), 1) if goal_weight_kg else None,
        "goal_date": str(goal_date)[:10] if goal_date else None,
        "start_weight_kg": round(float(start_weight_kg), 1) if start_weight_kg else None,
        "current_weight_kg": round(float(current_weight_kg), 1) if current_weight_kg else None,
        "kg_left": None,
        "kg_done": None,
        "pct": 0,
        "days_left": None,
        "reached": False,
        "direction": "gain",
    }
    if not goal_weight_kg:
        return result
    goal = float(goal_weight_kg)
    current = float(current_weight_kg) if current_weight_kg else None
    start = float(start_weight_kg) if start_weight_kg else current
    if start is None:
        return result

    result["direction"] = "gain" if goal >= start else "lose"
    result["start_weight_kg"] = round(start, 1)
    if current is not None:
        result["kg_left"] = round(goal - current, 1)
        result["kg_done"] = round(current - start, 1)
        span = goal - start
        if abs(span) < GOAL_DIRECTION_EPS:
            result["pct"] = 100
        else:
            result["pct"] = int(round(max(0.0, min(1.0, (current - start) / span)) * 100))
        result["reached"] = current >= goal if goal >= start else current <= goal
    if goal_date:
        try:
            days = (parse_date(goal_date) - parse_date(today or local_today())).days
            result["days_left"] = max(0, int(days))
        except ValueError:
            result["days_left"] = None
    return result


# --- планировщик дня ----------------------------------------------------------

DAY_KIND_LABELS = {
    "meal": "Еда",
    "gym": "Тренировка",
    "study": "Учёба",
    "sleep": "Сон",
    "work": "Дела",
    "other": "Другое",
}


def day_suggestions(
    profile: dict,
    meal_slots: list[dict] | None = None,
    classes_today: list[dict] | None = None,
    sleep_window_value: dict | None = None,
) -> list[dict]:
    """Заготовки блоков на день из режима сна, плана питания и занятий."""
    if not profile:
        return []
    window = sleep_window_value or sleep_window(
        profile.get("sleep_bed") or "23:00",
        profile.get("sleep_wake") or "07:00",
    )
    suggestions: list[dict] = [
        {
            "time": window["wake"],
            "title": "Подъём",
            "kind": "other",
            "duration_min": 15,
            "note": "Вода и лёгкая разминка",
            "source": "sleep",
        }
    ]
    class_duration = {"gym": 75, "study": 90, "other": 60}
    for item in classes_today or []:
        suggestions.append({
            "time": item.get("start_time", "18:00"),
            "title": item.get("title", "Занятие"),
            "kind": item.get("kind", "other") if item.get("kind") in DAY_KIND_LABELS else "other",
            "duration_min": int(item.get("duration_min") or class_duration.get(item.get("kind"), 60)),
            "note": item.get("place", ""),
            "source": "class",
        })
    for slot in meal_slots or []:
        title = slot.get("title") or "Приём пищи"
        kcal = slot.get("kcal")
        suggestions.append({
            "time": slot.get("time", "12:00"),
            "title": title,
            "kind": "meal",
            "duration_min": 30,
            "note": (f"≈ {int(kcal)} ккал" if kcal else ""),
            "source": "meal_plan",
        })
    suggestions.append({
        "time": window["bed"],
        "title": "Отбой",
        "kind": "sleep",
        "duration_min": 480,
        "note": "Последний приём пищи — за 2 ч до сна",
        "source": "sleep",
    })
    suggestions.sort(key=lambda item: time_to_minutes(item["time"]))
    return suggestions


def day_summary(items: list[dict]) -> dict:
    """Итоги плана дня: сколько блоков, выполнено, минуты и следующий блок."""
    total = len(items)
    done = sum(1 for item in items if int(item.get("done") or 0))
    planned = sum(int(item.get("duration_min") or 0) for item in items)
    done_minutes = sum(int(item.get("duration_min") or 0) for item in items if int(item.get("done") or 0))
    now_minutes = time_to_minutes(local_now().strftime("%H:%M"))
    upcoming = [
        item for item in items
        if not int(item.get("done") or 0) and time_to_minutes(item.get("time", "12:00")) >= now_minutes
    ]
    upcoming.sort(key=lambda item: time_to_minutes(item.get("time", "12:00")))
    return {
        "total": total,
        "done": done,
        "planned_minutes": planned,
        "done_minutes": done_minutes,
        "pct": int(round(done / total * 100)) if total else 0,
        "next": upcoming[0] if upcoming else None,
    }


# --- статус цели и недельный чек-ин -------------------------------------------

GOAL_STATUS_LABELS = {
    "on_track": "Идёшь по плану",
    "ahead": "Опережаешь план",
    "behind": "Отстаёшь от плана",
    "done": "Цель достигнута",
    "no_data": "Нужны взвешивания",
}

GOAL_STATUS_TONES = {
    "on_track": "good",
    "ahead": "warn",
    "behind": "bad",
    "done": "good",
    "no_data": "muted",
}


def goal_status(goal: dict, trend_kg_per_week: float | None, goal_rate: float = 0.35) -> dict:
    """Оценка: идёт ли прогресс к цели тем темпом, который заявлен.

    trend_kg_per_week — фактический тренд веса (кг/нед), goal_rate — целевой темп.
    """
    status = {
        "code": "no_data",
        "label": GOAL_STATUS_LABELS["no_data"],
        "tone": GOAL_STATUS_TONES["no_data"],
        "trend_kg_per_week": None,
        "target_kg_per_week": None,
        "hint": "Взвешивайся хотя бы раз в неделю, чтобы видеть динамику.",
    }
    if not goal or not goal.get("enabled"):
        status["hint"] = "Поставь цель по весу в профиле."
        return status
    if goal.get("reached"):
        status.update({
            "code": "done",
            "label": GOAL_STATUS_LABELS["done"],
            "tone": GOAL_STATUS_TONES["done"],
            "hint": "Можно ставить новую цель или перейти на поддержание веса.",
        })
        return status
    if trend_kg_per_week is None:
        return status

    direction = 1.0 if goal.get("direction", "gain") == "gain" else -1.0
    target = max(0.05, float(goal_rate or 0.35)) * direction
    actual = float(trend_kg_per_week)
    status["trend_kg_per_week"] = round(actual, 2)
    status["target_kg_per_week"] = round(target, 2)

    effective = actual * direction          # >0 — движемся в нужную сторону
    wanted = abs(target)
    if effective <= 0.02:
        status.update({
            "code": "behind",
            "label": GOAL_STATUS_LABELS["behind"],
            "tone": "bad",
            "hint": "Вес стоит или идёт не туда: проверь калории и регулярность взвешиваний.",
        })
    elif effective < wanted * 0.6:
        status.update({
            "code": "behind",
            "label": GOAL_STATUS_LABELS["behind"],
            "tone": "bad",
            "hint": "Темп ниже плана: добавь 150–200 ккал и не пропускай приёмы пищи.",
        })
    elif effective > wanted * 1.6:
        status.update({
            "code": "ahead",
            "label": GOAL_STATUS_LABELS["ahead"],
            "tone": "warn",
            "hint": "Темп выше плана: следи, чтобы прирост был не только жировой.",
        })
    else:
        status.update({
            "code": "on_track",
            "label": GOAL_STATUS_LABELS["on_track"],
            "tone": "good",
            "hint": "Продолжай в том же режиме — питание и сон совпадают с целью.",
        })
    return status


def week_bounds(value: date | str | None = None) -> dict:
    """Границы текущей ISO-недели (понедельник–воскресенье)."""
    day = parse_date(value) if value else parse_date(local_today())
    start = day - timedelta(days=day.weekday())
    return {
        "week_start": start.isoformat(),
        "week_end": (start + timedelta(days=6)).isoformat(),
        "day_of_week": day.weekday(),
        "days_to_sunday": 6 - day.weekday(),
    }


def meal_items_totals(items: list[dict]) -> dict:
    """Сумма КБЖУ и граммов по ингредиентам приёма пищи."""
    totals = {"kcal": 0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "grams": 0.0}
    for item in items or []:
        totals["kcal"] += int(item.get("kcal") or 0)
        totals["protein"] += float(item.get("protein") or 0)
        totals["fat"] += float(item.get("fat") or 0)
        totals["carbs"] += float(item.get("carbs") or 0)
        totals["grams"] += float(item.get("grams") or 0)
    return {
        "kcal": int(totals["kcal"]),
        "protein": round(totals["protein"], 1),
        "fat": round(totals["fat"], 1),
        "carbs": round(totals["carbs"], 1),
        "grams": round(totals["grams"], 1),
    }
