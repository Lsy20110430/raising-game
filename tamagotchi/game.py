"""养成游戏核心：好感度、心情、体力、金币、礼物、打工、存档与长期记忆。

所有数值规则在本地结算（可预期、防刷），DeepSeek 只负责角色扮演台词与
闲聊时对好感度/心情的微调，以及从对话里提炼长期记忆。
"""

import json
import random
import time

import db
import llm

MAX_STAMINA = 100
MAX_MOOD = 100
MAX_AFFINITY = 1000
MIN_MOOD = 15
EXP_PER_LEVEL = 80

# 游戏时钟与现实时间脱钩：不操作时现实 1 秒 = 游戏 1 分钟，动作再额外推进。
GAME_MINUTES_PER_REAL_SECOND = 1
START_GAME_MINUTES = 15 * 60
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 24 * MINUTES_PER_HOUR
STAMINA_UNIT_MINUTES = 10
MOOD_DECAY_MINUTES = 240
CHAT_MINUTES = 5
GIFT_MINUTES = 15
HISTORY_LIMIT = 20
MEMORY_LIMIT = 12
EVENT_LIMIT = 8

STAGES = [
    (0, "陌生人", "你对她来说只是路人，礼貌但疏远，回答简短，不会主动多说。"),
    (50, "打过照面", "你算是混了个脸熟，她愿意搭话，偶尔损你两句。"),
    (150, "朋友", "你们是朋友了，她会主动聊自己的事，语气轻松。"),
    (350, "好朋友", "关系很铁，她会撒娇、吐槽，也会关心你今天过得怎么样。"),
    (600, "有点心动", "她对你有好感但嘴硬，会害羞、口是心非，偶尔试探你。"),
    (850, "恋人", "你们在一起了，她黏人、直白、会吃醋，把你的事放在心上。"),
]

PERSONAS = {
    "qiqi": {
        "girl": "柒柒",
        "persona": (
            "24 岁，独立咖啡馆的常驻店员兼地下漫画同人作者。嘴上毒舌、爱怼人，"
            "心里其实很软。说话短促、爱用谐音梗和网络梗，被人戳中心事会立刻转移话题。"
            "喜欢熬夜赶稿，白天靠冰美式续命。"
        ),
        "likes": ["music", "game", "snack"],
        "dislikes": ["jewelry"],
        "intro": "下午三点的咖啡馆，吧台后那个正低头改稿的店员抬眼看了看你。",
    },
    "hoshino": {
        "girl": "星野凛",
        "persona": (
            "20 岁，植物系的插画学生，话少、慢热、怕生。习惯用很小的声音说话，"
            "容易脸红。喜欢花、雨天和一切毛茸茸的东西，写手账记下每天的小事。"
            "被认真对待时会手足无措，但会悄悄把你说过的话记下来。"
        ),
        "likes": ["flower", "letter", "plush", "book"],
        "dislikes": ["game"],
        "intro": "美术馆门口，抱着速写本的她站在台阶上，似乎在等雨停。",
    },
    "suwan": {
        "girl": "苏晚",
        "persona": (
            "27 岁，美术馆讲解员，清冷克制，说话像念诗。情绪很少外露，"
            "但会在意细节，记得住你说过的每一句无心之言。偏爱旧唱片与深夜散步，"
            "认为礼物贵不贵重不重要，重要的是有没有被认真挑过。"
        ),
        "likes": ["letter", "music", "book", "photo"],
        "dislikes": ["drink", "snack"],
        "intro": "散场后的展厅，她一个人站在那幅画前，很久没有动。",
    },
}

ITEMS = [
    {"id": "daisy", "name": "小雏菊", "emoji": "🌼", "tag": "flower",
     "price": 15, "affinity": 4, "mood": 3, "desc": "路边花摊随手买的一小束。"},
    {"id": "milktea", "name": "珍珠奶茶", "emoji": "🧋", "tag": "drink",
     "price": 30, "affinity": 7, "mood": 6, "desc": "三分糖去冰，她写在便签上的那种。"},
    {"id": "cake", "name": "草莓蛋糕", "emoji": "🍰", "tag": "dessert",
     "price": 60, "affinity": 12, "mood": 10, "desc": "动物奶油，草莓堆得快要塌下来。"},
    {"id": "letter", "name": "手写情书", "emoji": "💌", "tag": "letter",
     "price": 90, "affinity": 18, "mood": 8, "desc": "信纸是旧的，字写得有点抖。"},
    {"id": "handheld", "name": "复古掌机", "emoji": "🎮", "tag": "game",
     "price": 220, "affinity": 30, "mood": 14, "desc": "二手的，附赠三张卡带。"},
    {"id": "bracelet", "name": "星空手链", "emoji": "✨", "tag": "jewelry",
     "price": 220, "affinity": 24, "mood": 12, "desc": "碎银拼成一小片夜空，看不出牌子。"},
    {"id": "vinyl", "name": "黑胶唱片", "emoji": "💿", "tag": "music",
     "price": 350, "affinity": 42, "mood": 18, "desc": "老爵士，封套边角磨白。"},
    {"id": "ticket", "name": "演唱会门票", "emoji": "🎫", "tag": "music",
     "price": 800, "affinity": 80, "mood": 30, "desc": "内场前排，两张——所以还有一张是给你的。"},
    {"id": "cookie", "name": "手作曲奇", "emoji": "🍪", "tag": "snack",
     "price": 45, "affinity": 9, "mood": 8, "desc": "黄油味很重，边缘烤得有点焦。"},
    {"id": "plush", "name": "毛绒兔子", "emoji": "🧸", "tag": "plush",
     "price": 120, "affinity": 20, "mood": 15, "desc": "耳朵软得能捏出水，据说抱着睡得着。"},
    {"id": "poetry", "name": "旧诗集", "emoji": "📖", "tag": "book",
     "price": 150, "affinity": 26, "mood": 12, "desc": "扉页留着前主人的铅笔字，某人写了一半。"},
    {"id": "scarf", "name": "手织围巾", "emoji": "🧣", "tag": "clothes",
     "price": 180, "affinity": 24, "mood": 14, "desc": "米白色，针脚歪歪扭扭，但真的暖。"},
    {"id": "polaroid", "name": "拍立得相机", "emoji": "📷", "tag": "photo",
     "price": 480, "affinity": 52, "mood": 22, "desc": "附一整盒相纸，第一张大概会是你俩。"},
    {"id": "onsen", "name": "温泉旅行券", "emoji": "♨️", "tag": "travel",
     "price": 1200, "affinity": 110, "mood": 40, "desc": "两天一夜含早晚餐，山里那家，窗外有溪。"},
]

JOBS = [
    {"id": "flyer", "name": "街头发传单", "emoji": "📄", "hours": 2, "cooldown_hours": 1,
     "stamina": 10, "coins": (25, 40), "exp": 3, "level_req": 1, "mood": 0,
     "window": (8, 19), "desc": "站一下午，腿酸。"},
    {"id": "cafe", "name": "咖啡店帮工", "emoji": "☕", "hours": 3, "cooldown_hours": 2,
     "stamina": 20, "coins": (60, 85), "exp": 6, "level_req": 1, "mood": 1,
     "window": (8, 20), "desc": "洗杯子洗到手抽筋，但能蹭一杯美式。"},
    {"id": "tutor", "name": "当家教", "emoji": "📚", "hours": 4, "cooldown_hours": 4,
     "stamina": 30, "coins": (110, 150), "exp": 10, "level_req": 3, "mood": 0,
     "window": (15, 22), "desc": "讲一下午函数，嗓子冒烟。"},
    {"id": "delivery", "name": "深夜配送", "emoji": "🛵", "hours": 5, "cooldown_hours": 6,
     "stamina": 40, "coins": (180, 240), "exp": 16, "level_req": 5, "mood": -3,
     "window": (21, 5), "desc": "凌晨的订单加价最多，也最熬人。"},
    {"id": "store", "name": "便利店夜班", "emoji": "🏪", "hours": 4, "cooldown_hours": 5,
     "stamina": 28, "coins": (95, 130), "exp": 12, "level_req": 2, "mood": -1,
     "window": (20, 4), "desc": "补货、关东煮、收银，凌晨的客人话都很少。"},
    {"id": "pet", "name": "宠物店帮忙", "emoji": "🐕", "hours": 3, "cooldown_hours": 3,
     "stamina": 18, "coins": (70, 100), "exp": 7, "level_req": 2, "mood": 4,
     "window": (9, 18), "desc": "洗狗吹毛，被甩了一身水，但挺快乐。"},
    {"id": "library", "name": "图书馆整理", "emoji": "🗂️", "hours": 3, "cooldown_hours": 3,
     "stamina": 16, "coins": (75, 105), "exp": 8, "level_req": 3, "mood": 1,
     "window": (9, 17), "desc": "把还回来的书一本本归位，安静得听见空调声。"},
    {"id": "busker", "name": "街头卖唱", "emoji": "🎤", "hours": 3, "cooldown_hours": 5,
     "stamina": 25, "coins": (60, 220), "exp": 11, "level_req": 4, "mood": 2,
     "window": (17, 23), "desc": "唱得好不好全看路人心情，收成起伏很大。"},
    {"id": "moving", "name": "搬家苦力", "emoji": "📦", "hours": 5, "cooldown_hours": 8,
     "stamina": 45, "coins": (210, 280), "exp": 18, "level_req": 6, "mood": -4,
     "window": (8, 20), "desc": "六楼没电梯，一趟一趟往上扛。"},
]

# 娱乐项目：单人自己放松回心情，双人（kind=duo）要 100 好感起，带她一起出门，
# 每次结束都会写进她的长期记忆。
ACTIVITIES = [
    {"id": "arcade", "name": "打街机", "emoji": "🕹️", "kind": "solo",
     "hours": 1, "cooldown_hours": 2, "stamina": 10, "cost": 10, "mood": 9, "affinity": 0,
     "exp": 3, "level_req": 1, "window": (10, 24), "desc": "一个币一个人，把最高分刷上去。"},
    {"id": "jogging", "name": "沿江夜跑", "emoji": "🏃", "kind": "solo",
     "hours": 1, "cooldown_hours": 3, "stamina": 14, "cost": 0, "mood": 7, "affinity": 0,
     "exp": 4, "level_req": 1, "window": (17, 24), "desc": "跑到桥下折返，风吹得人清醒。"},
    {"id": "cat_cafe", "name": "猫咖撸猫", "emoji": "🐈", "kind": "solo",
     "hours": 2, "cooldown_hours": 4, "stamina": 12, "cost": 40, "mood": 16, "affinity": 0,
     "exp": 6, "level_req": 2, "window": (9, 21), "desc": "三只橘猫轮流踩你腿，走的时候全是毛。"},
    {"id": "ranked", "name": "通宵排位", "emoji": "🎮", "kind": "solo",
     "hours": 3, "cooldown_hours": 5, "stamina": 22, "cost": 0, "mood": 12, "affinity": 0,
     "exp": 9, "level_req": 2, "window": (19, 24), "desc": "连跪三把，但最后一把赢了。"},
    {"id": "reading", "name": "图书馆看书", "emoji": "📚", "kind": "solo",
     "hours": 2, "cooldown_hours": 3, "stamina": 10, "cost": 0, "mood": 8, "affinity": 0,
     "exp": 8, "level_req": 3, "window": (9, 18), "desc": "靠窗的位置，一下午只看完半本。"},
    {"id": "spa", "name": "一个人泡温泉", "emoji": "♨️", "kind": "solo",
     "hours": 3, "cooldown_hours": 6, "stamina": 5, "cost": 120, "mood": 24, "affinity": 0,
     "exp": 7, "level_req": 4, "window": (10, 23), "desc": "露天池子只有你，水汽把路灯糊成一团。"},
    {"id": "movie", "name": "一起看电影", "emoji": "🎬", "kind": "duo",
     "hours": 3, "cooldown_hours": 6, "stamina": 15, "cost": 60, "mood": 18, "affinity": 12,
     "exp": 6, "level_req": 1, "window": (17, 24), "desc": "夜场，爆米花买一份，两个人抢。",
     "memory": "第 {day} 天你们一起看了夜场电影，散场时她还一直在聊剧情。"},
    {"id": "escape", "name": "双人密室", "emoji": "🗝️", "kind": "duo",
     "hours": 3, "cooldown_hours": 8, "stamina": 20, "cost": 90, "mood": 20, "affinity": 15,
     "exp": 8, "level_req": 2, "window": (10, 22), "desc": "最后一关是你解的，她在旁边喊得比你大声。",
     "memory": "第 {day} 天你们一起玩了双人密室，最后一关的谜是你解开的，她记到了现在。"},
    {"id": "sunset", "name": "海边看日落", "emoji": "🌇", "kind": "duo",
     "hours": 4, "cooldown_hours": 10, "stamina": 18, "cost": 40, "mood": 24, "affinity": 17,
     "exp": 9, "level_req": 2, "window": (15, 20), "desc": "坐最后一班地铁去海边，风大得说话要靠喊。",
     "memory": "第 {day} 天你们在海边看了日落，风很大，她说想再来一次。"},
    {"id": "night_market", "name": "逛夜市", "emoji": "🍡", "kind": "duo",
     "hours": 3, "cooldown_hours": 8, "stamina": 20, "cost": 80, "mood": 22, "affinity": 18,
     "exp": 9, "level_req": 3, "window": (18, 23), "desc": "从烤串吃到糖水，她在糖画摊前站了很久。",
     "memory": "第 {day} 天你们一起去逛了夜市，她在糖画摊前站了很久。"},
    {"id": "livehouse", "name": "一起看 livehouse", "emoji": "🎸", "kind": "duo",
     "hours": 4, "cooldown_hours": 12, "stamina": 25, "cost": 180, "mood": 30, "affinity": 26,
     "exp": 14, "level_req": 4, "window": (17, 23), "desc": "挤在第二排，耳朵嗡嗡了一整晚。",
     "memory": "第 {day} 天你们一起挤在 livehouse 第二排，散场后耳朵嗡嗡了一整晚。"},
    {"id": "trip", "name": "周末短途旅行", "emoji": "🚗", "kind": "duo",
     "hours": 8, "cooldown_hours": 24, "stamina": 45, "cost": 400, "mood": 40, "affinity": 36,
     "exp": 24, "level_req": 6, "window": (6, 14), "desc": "两天一夜，她拍了一路照片。",
     "memory": "第 {day} 天你们一起去了两天一夜的短途旅行，她拍了很多照片。"},
]

DUO_AFFINITY_REQ = 100

REST_HOURS = 4
REST_COOLDOWN_HOURS = 6
REST_STAMINA = 45
REST_MOOD = 3


def clamp(value, low, high):
    return max(low, min(high, value))


PERIODS = [
    (0, 5, "凌晨"),
    (5, 8, "清晨"),
    (8, 11, "上午"),
    (11, 13, "中午"),
    (13, 17, "下午"),
    (17, 19, "傍晚"),
    (19, 23, "晚上"),
    (23, 24, "深夜"),
]


def period_of(hour):
    for start, end, name in PERIODS:
        if start <= hour < end:
            return name
    return "深夜"


def clock_of(game_minutes):
    day, minute_of_day = divmod(int(game_minutes), MINUTES_PER_DAY)
    hour, minute = divmod(minute_of_day, MINUTES_PER_HOUR)
    return {
        "minutes": int(game_minutes),
        "day": day + 1,
        "hour": hour,
        "minute": minute,
        "minute_of_day": minute_of_day,
        "period": period_of(hour),
        "text": "第 {} 天 {:02d}:{:02d}".format(day + 1, hour, minute),
        "night": hour >= 23 or hour < 6,
    }


def game_time_text(game_minutes):
    return clock_of(game_minutes)["text"]


def duration_text(minutes):
    minutes = int(minutes)
    if minutes <= 0:
        return "现在"
    days, rest = divmod(minutes, MINUTES_PER_DAY)
    hours, mins = divmod(rest, MINUTES_PER_HOUR)
    parts = []
    if days:
        parts.append("{} 天".format(days))
    if hours:
        parts.append("{} 小时".format(hours))
    if mins and not days:
        parts.append("{} 分钟".format(mins))
    return "".join(parts) if parts else "1 分钟"


def window_text(window):
    if not window:
        return "随时"
    return "{:02d}:00-{:02d}:00".format(window[0], window[1])


def in_window(hour, window):
    if not window:
        return True
    start, end = window
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def stage_of(affinity):
    stage = STAGES[0]
    for item in STAGES:
        if affinity >= item[0]:
            stage = item
    index = STAGES.index(stage)
    upper = STAGES[index + 1][0] if index + 1 < len(STAGES) else MAX_AFFINITY
    return {
        "name": stage[1],
        "attitude": stage[2],
        "floor": stage[0],
        "ceil": upper,
    }


def level_of(exp):
    return 1 + exp // EXP_PER_LEVEL


def exp_progress(exp):
    return exp % EXP_PER_LEVEL, EXP_PER_LEVEL


def find_item(item_id):
    for item in ITEMS:
        if item["id"] == item_id:
            return item
    return None


def find_job(job_id):
    for job in JOBS:
        if job["id"] == job_id:
            return job
    return None


def find_activity(activity_id):
    for activity in ACTIVITIES:
        if activity["id"] == activity_id:
            return activity
    return None


def find_persona(persona_key):
    return PERSONAS.get(persona_key)


def get_save():
    return db.get_save()


def new_game(persona_key=None):
    key = persona_key if persona_key in PERSONAS else random.choice(list(PERSONAS))
    persona = PERSONAS[key]
    now = int(time.time())
    db.wipe()
    db.put_save({
        "girl": persona["girl"],
        "persona": persona["persona"],
        "likes": json.dumps(persona["likes"], ensure_ascii=False),
        "dislikes": json.dumps(persona["dislikes"], ensure_ascii=False),
        "affinity": 10,
        "mood": 60,
        "stamina": MAX_STAMINA,
        "coins": 120,
        "exp": 0,
        "game_time": START_GAME_MINUTES,
        "tick_mark": START_GAME_MINUTES,
        "last_tick": now,
        "created_ts": now,
        "updated_ts": now,
    })
    db.add_memory("setting", "你在咖啡馆第一次见到她。", now)
    db.add_event("story", persona["intro"], now)
    return get_save()


def _ensure_likes(save):
    """礼物新增标签后，老存档的喜好表要跟上：按角色名找回人设，补齐缺失的标签。"""
    persona = next((p for p in PERSONAS.values() if p["girl"] == save["girl"]), None)
    if not persona:
        return
    likes = json.loads(save["likes"])
    dislikes = json.loads(save["dislikes"])
    changed = False
    for tag in persona["likes"]:
        if tag not in likes:
            likes.append(tag)
            changed = True
    for tag in persona["dislikes"]:
        if tag not in dislikes:
            dislikes.append(tag)
            changed = True
    if changed:
        save["likes"] = json.dumps(likes, ensure_ascii=False)
        save["dislikes"] = json.dumps(dislikes, ensure_ascii=False)


def _ensure_clock(save, real_now):
    """老存档没有游戏时钟，一次性补齐：时钟归到开局时刻，旧事件时间一并归位。"""
    if save.get("game_time"):
        return
    save["game_time"] = START_GAME_MINUTES
    save["tick_mark"] = START_GAME_MINUTES
    save["last_tick"] = real_now
    db.rebase_timestamps(START_GAME_MINUTES)
    db.clear_cooldowns()


def _sync(save, real_now=None):
    """把存档推进到当前游戏时刻，并按流逝的游戏时间结算体力与心情。

    last_tick 存的是与 game_time 对应的现实秒，两者加上流逝量才是「现在」。
    """
    real_now = int(time.time()) if real_now is None else real_now
    _ensure_clock(save, real_now)
    _ensure_likes(save)
    game_minutes = save["game_time"] + max(0, real_now - save["last_tick"]) * GAME_MINUTES_PER_REAL_SECOND

    passed = ((game_minutes - save["tick_mark"]) // STAMINA_UNIT_MINUTES) * STAMINA_UNIT_MINUTES
    if passed > 0:
        save["stamina"] = min(MAX_STAMINA, save["stamina"] + passed // STAMINA_UNIT_MINUTES)
        save["mood"] = max(MIN_MOOD, save["mood"] - passed // MOOD_DECAY_MINUTES)
        save["tick_mark"] += passed

    save["game_time"] = game_minutes
    save["last_tick"] = real_now
    save["updated_ts"] = real_now
    db.put_save(save)
    return save


def _spend(save, minutes):
    """动作本身占用的游戏时间。"""
    save["game_time"] += minutes
    save["last_tick"] = int(time.time())


def _save(save, now):
    save["updated_ts"] = now
    db.put_save(save)


def _add_affinity(save, amount):
    before = stage_of(save["affinity"])["name"]
    save["affinity"] = clamp(save["affinity"] + amount, 0, MAX_AFFINITY)
    after = stage_of(save["affinity"])["name"]
    if before != after:
        db.add_event("stage", "你们的关系变成了「{}」。".format(after), save["game_time"])


def _add_exp(save, amount):
    before = level_of(save["exp"])
    save["exp"] += amount
    after = level_of(save["exp"])
    if after > before:
        db.add_event("level", "你的等级升到了 Lv.{}。".format(after), save["game_time"])
        db.add_memory("event", "你升到了 Lv.{}。".format(after), save["game_time"])


def _system_prompt(save, extra=None, json_output=True, with_history=True):
    likes = json.loads(save["likes"])
    stage = stage_of(save["affinity"])
    clock = clock_of(save["game_time"])
    memories = db.recent_memories(MEMORY_LIMIT)
    events = db.recent_events(EVENT_LIMIT)

    memory_text = "\n".join("- " + m["content"] for m in memories) or "- （还没有什么值得记住的事）"
    event_text = "\n".join(
        "- [{}] {}".format(game_time_text(e["ts"]), e["text"])
        for e in events
    ) or "- （刚刚开始）"

    parts = [
        "你在一款养成互动游戏里扮演「{}」，玩家是和你相识的人。永远以她本人的身份说话。".format(save["girl"]),
        "\n【角色设定】\n" + save["persona"],
        "\n【你们的当前关系】好感度 {}/{}\n【你现在的状态】心情 {}/100，体力 {}/100\n"
        "【玩家的钱包】{} 金币".format(
            save["affinity"], MAX_AFFINITY, save["mood"], save["stamina"], save["coins"]
        ),
        "\n【关系阶段：{}】{}".format(stage["name"], stage["attitude"]),
        "\n【现在的时间】{0}（{1}）".format(clock["text"], clock["period"]),
        "\n【你记得的事】\n" + memory_text,
        "\n【最近发生的事】\n" + event_text,
    ]
    if extra:
        parts.append("\n【此刻的场景】\n" + extra)
    history = _history_text()
    if with_history and history:
        parts.append("\n【你们之前的对话（按时间顺序）】\n" + history)
    if json_output:
        parts.append(
            "\n【输出要求】只输出一个 JSON 对象，不要其他文字：\n"
            '{"reply": "你的台词", "affinity_delta": 0, "mood_delta": 0, "memory": ""}\n'
            "规则：\n"
            "- reply：1~3 句中文口语，符合角色语气、当前关系阶段和当前时段（清晨刚醒、深夜别约她出门），"
            "不念数值、不说自己是 AI、不下场解说，最多一句轻描淡写的动作描写。\n"
            "- affinity_delta：普通闲聊 0~2；让你开心 3~5；冒犯、越界、油腻 -5~-1。\n"
            "- mood_delta：-5~5，随对话氛围。\n"
            "- memory：只有玩家透露了值得长期记住的信息（名字、喜好、约定、心事）才写一句"
            "话，否则留空字符串。"
        )
    else:
        parts.append(
            "\n【输出要求】直接输出她说出口的话，1~2 句中文口语，要顾得上当前时段。"
            "不要 JSON、不要引号包裹、不要括号里写数值、不要任何格式标记。"
        )
    return "".join(parts)


def _history_text(limit=HISTORY_LIMIT):
    """历史以文本形式进 prompt：这个网关在「多轮 messages + JSON 模式」下会稳定返回空内容。"""
    messages = db.recent_messages(limit)
    lines = [
        ("玩家：" if m["role"] == "user" else "她：") + m["content"]
        for m in messages
    ]
    return "\n".join(lines)


def _scene_reply(save, scene, fallbacks):
    """非对话场景（打工、送礼）里让角色说一句自然的话，失败时用兜底台词。"""
    try:
        text = llm.chat(
            [
                {"role": "system", "content": _system_prompt(save, json_output=False)},
                {"role": "user", "content": "（旁白，不是玩家的发言）" + scene},
            ],
            temperature=1.0,
            max_tokens=220,
        ).strip()
        text = text.strip('"“”')
        if text and "{" not in text:
            return text
    except llm.LLMError:
        pass
    return random.choice(fallbacks)


def do_chat(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("说点什么吧")
    if len(text) > 500:
        text = text[:500]

    save = _sync(get_save() or new_game())
    _spend(save, CHAT_MINUTES)
    stamp = save["game_time"]

    messages = [
        {"role": "system", "content": _system_prompt(save)},
        {"role": "user", "content": text},
    ]

    data = llm.chat_json(messages)
    reply = str(data.get("reply", "")).strip() or "……"
    affinity_delta = clamp(int(data.get("affinity_delta") or 0), -5, 5)
    mood_delta = clamp(int(data.get("mood_delta") or 0), -5, 5)
    memory = str(data.get("memory") or "").strip()

    db.add_message("user", text, stamp)
    db.add_message("assistant", reply, stamp)

    _add_affinity(save, affinity_delta)
    save["mood"] = clamp(save["mood"] + mood_delta, MIN_MOOD, MAX_MOOD)
    _add_exp(save, 1)

    if memory:
        db.add_memory("talk", memory, stamp)

    _save(save, int(time.time()))
    db.add_event("chat", "你：「{}」".format(text[:40]), stamp)
    return {
        "reply": reply,
        "affinity_delta": affinity_delta,
        "mood_delta": mood_delta,
        "memory_added": memory or None,
        "game_minutes": CHAT_MINUTES,
    }


def do_gift(item_id):
    item = find_item(item_id)
    if not item:
        raise ValueError("没有这件礼物")

    now = int(time.time())
    save = _sync(get_save() or new_game(), now)
    _spend(save, GIFT_MINUTES)
    stamp = save["game_time"]

    if save["coins"] < item["price"]:
        raise ValueError("金币不够，先去打工吧")

    likes = json.loads(save["likes"])
    dislikes = json.loads(save["dislikes"])
    if item["tag"] in likes:
        factor, reaction = 2.0, "喜欢"
    elif item["tag"] in dislikes:
        factor, reaction = -0.25, "不太喜欢"
    else:
        factor, reaction = 1.0, "一般"

    sent_before = db.gift_count(item["id"])
    if factor > 0:
        factor *= max(0.45, 1.0 - 0.2 * sent_before)

    affinity_gain = int(round(item["affinity"] * factor))
    mood_gain = int(round(item["mood"] * max(factor, 0.2)))

    save["coins"] -= item["price"]
    _add_affinity(save, affinity_gain)
    save["mood"] = clamp(save["mood"] + mood_gain, MIN_MOOD, MAX_MOOD)
    _add_exp(save, 2)
    db.bump_gift_count(item["id"])
    _save(save, now)

    scene = "玩家刚刚把「{}」送给了你，你对这类礼物的态度是{}。请说一句自然的话回应。".format(
        item["name"], reaction
    )
    line = _scene_reply(save, scene, ["……谢谢。", "收下了，别多想。"])
    db.add_message("assistant", line, stamp)
    db.add_event(
        "gift",
        "你送了她{}，好感度 {:+d}。".format(item["emoji"] + item["name"], affinity_gain),
        stamp,
    )
    if affinity_gain >= 30:
        db.add_memory("gift", "你送过她{}，她很高兴。".format(item["name"]), stamp)

    return {
        "reply": line,
        "affinity_delta": affinity_gain,
        "mood_delta": mood_gain,
        "reaction": reaction,
        "coins": save["coins"],
        "game_minutes": GIFT_MINUTES,
    }


def do_work(job_id):
    job = find_job(job_id)
    if not job:
        raise ValueError("没有这份工作")

    now = int(time.time())
    save = _sync(get_save() or new_game(), now)

    clock = clock_of(save["game_time"])
    if not in_window(clock["hour"], job["window"]):
        raise ValueError("「{}」只在 {} 能做，现在是 {}（{}）。".format(
            job["name"], window_text(job["window"]), clock["text"], clock["period"]))
    if level_of(save["exp"]) < job["level_req"]:
        raise ValueError("等级不够，Lv.{} 才能做这份工作".format(job["level_req"]))
    if save["stamina"] < job["stamina"]:
        raise ValueError("体力不够，先休息一下吧")

    ready = db.get_cooldown("job:" + job["id"])
    if ready > save["game_time"]:
        raise ValueError("这份工作还要等 {}（游戏内）".format(duration_text(ready - save["game_time"])))

    _spend(save, job["hours"] * MINUTES_PER_HOUR)
    stamp = save["game_time"]

    base = random.randint(job["coins"][0], job["coins"][1])
    if save["mood"] >= 70:
        multiplier, mood_note = 1.2, "心情好，效率高"
    elif save["mood"] <= 30:
        multiplier, mood_note = 0.8, "状态低落，提不起劲"
    else:
        multiplier, mood_note = 1.0, ""
    earned = int(round(base * multiplier))

    save["coins"] += earned
    save["stamina"] -= job["stamina"]
    save["mood"] = clamp(save["mood"] + job["mood"], MIN_MOOD, MAX_MOOD)
    _add_exp(save, job["exp"])
    _save(save, now)
    db.set_cooldown(
        "job:" + job["id"],
        save["game_time"] + job["cooldown_hours"] * MINUTES_PER_HOUR,
    )

    db.add_event("work", "你做了{}，赚到 {} 金币。".format(job["name"], earned), stamp)
    scene = "玩家刚去「{}」干了 {} 小时回来，赚了 {} 金币，现在体力只剩 {}/100。"\
            "请说一句自然的话，可以调侃或关心。".format(
                job["name"], job["hours"], earned, save["stamina"]
            )
    line = _scene_reply(save, scene, ["辛苦了。", "赚这么点，值得吗？"])
    db.add_message("assistant", line, stamp)

    return {
        "reply": line,
        "earned": earned,
        "mood_note": mood_note,
        "coins": save["coins"],
        "stamina": save["stamina"],
        "game_minutes": job["hours"] * MINUTES_PER_HOUR,
    }


def do_rest():
    now = int(time.time())
    save = _sync(get_save() or new_game(), now)

    ready = db.get_cooldown("rest")
    if ready > save["game_time"]:
        raise ValueError("刚休息过，还要等 {}（游戏内）".format(duration_text(ready - save["game_time"])))

    _spend(save, REST_HOURS * MINUTES_PER_HOUR)
    stamp = save["game_time"]
    save["stamina"] = min(MAX_STAMINA, save["stamina"] + REST_STAMINA)
    save["mood"] = clamp(save["mood"] + REST_MOOD, MIN_MOOD, MAX_MOOD)
    _save(save, now)
    db.set_cooldown("rest", save["game_time"] + REST_COOLDOWN_HOURS * MINUTES_PER_HOUR)
    db.add_event("rest", "你睡了 {} 小时，体力恢复了一些。".format(REST_HOURS), stamp)

    clock = clock_of(save["game_time"])
    scene = "玩家刚补了一觉（{} 小时），现在 {}（{}）、体力 {}/100。请说一句自然的话。".format(
        REST_HOURS, clock["text"], clock["period"], save["stamina"]
    )
    line = _scene_reply(save, scene, ["睡醒了？", "再睡下去要长蘑菇了。"])
    db.add_message("assistant", line, stamp)
    return {"reply": line, "stamina": save["stamina"], "game_minutes": REST_HOURS * MINUTES_PER_HOUR}


def do_activity(activity_id):
    act = find_activity(activity_id)
    if not act:
        raise ValueError("没有这个娱乐项目")

    now = int(time.time())
    save = _sync(get_save() or new_game(), now)
    duo = act["kind"] == "duo"
    clock = clock_of(save["game_time"])

    if not in_window(clock["hour"], act["window"]):
        raise ValueError("「{}」只在 {} 能去，现在是 {}（{}）。".format(
            act["name"], window_text(act["window"]), clock["text"], clock["period"]))
    if level_of(save["exp"]) < act["level_req"]:
        raise ValueError("等级不够，Lv.{} 才能玩这个".format(act["level_req"]))
    if duo and save["affinity"] < DUO_AFFINITY_REQ:
        raise ValueError("好感度不到 {}，现在还约不动她".format(DUO_AFFINITY_REQ))
    if save["coins"] < act["cost"]:
        raise ValueError("金币不够，先攒攒吧")
    if save["stamina"] < act["stamina"]:
        raise ValueError("体力不够，先休息一下吧")

    ready = db.get_cooldown("act:" + act["id"])
    if ready > save["game_time"]:
        raise ValueError("刚玩过这个，还要等 {}（游戏内）".format(duration_text(ready - save["game_time"])))

    _spend(save, act["hours"] * MINUTES_PER_HOUR)
    stamp = save["game_time"]

    save["coins"] -= act["cost"]
    save["stamina"] -= act["stamina"]
    save["mood"] = clamp(save["mood"] + act["mood"], MIN_MOOD, MAX_MOOD)
    if act["affinity"]:
        _add_affinity(save, act["affinity"])
    _add_exp(save, act["exp"])
    _save(save, now)
    db.set_cooldown(
        "act:" + act["id"],
        save["game_time"] + act["cooldown_hours"] * MINUTES_PER_HOUR,
    )

    memory = None
    if duo:
        scene = ("玩家刚带你一起去「{}」，你们一起待了 {} 小时，现在是 {}。"
                 "请用她的口吻说一句刚散场时的感想，1~2 句，别提数值。".format(
                     act["name"], act["hours"], game_time_text(stamp)))
        line = _scene_reply(save, scene, ["……嗯，今天挺开心的。", "下次换你挑地方。"])
        memory = act["memory"].format(day=clock_of(stamp)["day"])
        db.add_memory("date", memory, stamp)
        db.add_event("date", "你们一起去了{}，好感度 {:+d}，心情 {:+d}。".format(
            act["name"], act["affinity"], act["mood"]), stamp)
    else:
        scene = "玩家刚一个人去「{}」玩了 {} 小时回来，心情 {}/100，体力 {}/100。"\
                "请说一句自然的话。".format(act["name"], act["hours"], save["mood"], save["stamina"])
        line = _scene_reply(save, scene, ["一个人玩也挺好。", "玩够了就回来说话。"])
        db.add_event("play", "你一个人去{}玩了 {} 小时，心情 {:+d}。".format(
            act["name"], act["hours"], act["mood"]), stamp)

    db.add_message("assistant", line, stamp)
    return {
        "reply": line,
        "kind": act["kind"],
        "affinity_delta": act["affinity"],
        "mood_delta": act["mood"],
        "coins": save["coins"],
        "stamina": save["stamina"],
        "memory_added": memory,
        "game_minutes": act["hours"] * MINUTES_PER_HOUR,
    }


def build_state():
    real_now = int(time.time())
    save = _sync(get_save() or new_game(), real_now)

    clock = clock_of(save["game_time"])
    level = level_of(save["exp"])
    exp_now, exp_need = exp_progress(save["exp"])

    shop = []
    for item in ITEMS:
        shop.append(dict(item, affordable=save["coins"] >= item["price"]))

    jobs = []
    for job in JOBS:
        ready = db.get_cooldown("job:" + job["id"])
        jobs.append(dict(
            job,
            locked=level < job["level_req"],
            cooldown=max(0, ready - save["game_time"]),
            open=in_window(clock["hour"], job["window"]),
            window_text=window_text(job["window"]),
            enough_stamina=save["stamina"] >= job["stamina"],
        ))

    activities = []
    for act in ACTIVITIES:
        ready = db.get_cooldown("act:" + act["id"])
        duo = act["kind"] == "duo"
        activities.append(dict(
            act,
            duo=duo,
            affinity_req=DUO_AFFINITY_REQ if duo else 0,
            locked=level < act["level_req"],
            affinity_locked=duo and save["affinity"] < DUO_AFFINITY_REQ,
            affordable=save["coins"] >= act["cost"],
            cooldown=max(0, ready - save["game_time"]),
            open=in_window(clock["hour"], act["window"]),
            window_text=window_text(act["window"]),
            enough_stamina=save["stamina"] >= act["stamina"],
        ))

    rest_ready = db.get_cooldown("rest")
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in db.recent_messages(60)
    ]

    return {
        "girl": save["girl"],
        "persona": save["persona"],
        "affinity": save["affinity"],
        "affinity_max": MAX_AFFINITY,
        "stage": stage_of(save["affinity"]),
        "mood": save["mood"],
        "mood_max": MAX_MOOD,
        "stamina": save["stamina"],
        "stamina_max": MAX_STAMINA,
        "coins": save["coins"],
        "level": level,
        "exp": exp_now,
        "exp_need": exp_need,
        "history": history,
        "shop": shop,
        "jobs": jobs,
        "activities": activities,
        "duo_affinity_req": DUO_AFFINITY_REQ,
        "time": dict(clock, rate=GAME_MINUTES_PER_REAL_SECOND, synced_at=real_now),
        "rest_cooldown": max(0, rest_ready - save["game_time"]),
        "rest_ready": rest_ready <= save["game_time"],
        "memories": db.recent_memories(20),
        "events": db.recent_events(20),
        "saved_at": save["updated_ts"],
    }
