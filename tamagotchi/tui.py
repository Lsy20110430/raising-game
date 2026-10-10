"""终端版入口：在 Termux / 任意 TTY 里玩，复用 game / db / llm 的全部逻辑。

用法：sh run.sh（或 python3 tui.py）
"""

import os
import sys
import unicodedata

import db
import game
import llm

WIDTH_FALLBACK = 52
MIN_WIDTH = 28
MAX_WIDTH = 100
HISTORY_SHOW = 40

HELP = """\
  直接输入内容      和她聊天
  /state            当前状态与冷却
  /shop             礼物清单
  /gift <编号>      送礼物（/gift 3）
  /work             工作清单
  /work <编号>      去打工（/work 2）
  /play             娱乐清单（单人 / 双人）
  /play <编号>      去玩（/play 3，双人项目需好感 100）
  /rest             休息，恢复体力
  /log [条数]       最近发生的事
  /memory           她记得的事
  /new [角色]       重新开始（qiqi / hoshino / suwan）
  /help             这份帮助
  /quit             退出"""


def setup_stdio():
    """Termux 默认不设 LANG，stdout 可能是 ascii 编码，print 一句中文就崩。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def char_width(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(text):
    return sum(char_width(ch) for ch in text)


def pad(text, target):
    return text + " " * max(0, target - width(text))


def plain(text):
    """Termux 的字体基本没有 emoji 字形，直接输出是一排豆腐块，显示前摘掉。"""
    return "".join(ch for ch in str(text) if unicodedata.category(ch) != "So")


def columns():
    cols = 0
    try:
        cols = os.get_terminal_size().columns
    except OSError:
        cols = 0
    if not cols:
        cols = int(os.environ.get("TUI_WIDTH") or WIDTH_FALLBACK)
    return max(MIN_WIDTH, min(cols, MAX_WIDTH))


def wrap(text, limit=None):
    limit = limit or columns()
    lines, cur, used = [], "", 0
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur, used = "", 0
            continue
        if used + char_width(ch) > limit and cur:
            lines.append(cur)
            cur, used = "", 0
            if ch == " ":
                continue
        cur += ch
        used += char_width(ch)
    lines.append(cur)
    return lines


def paragraph(text, prefix=""):
    limit = max(8, columns() - width(prefix))
    pad_to = " " * width(prefix)
    for index, line in enumerate(wrap(plain(text), limit)):
        print((prefix if index == 0 else pad_to) + line)


def rule(char="-"):
    print(char * columns())


def bar(value, maximum, cells=10):
    filled = 0 if maximum <= 0 else int(round(cells * value / maximum))
    filled = max(0, min(cells, filled))
    return "[" + "#" * filled + "." * (cells - filled) + "]"


def next_stage(stage):
    for index, entry in enumerate(game.STAGES):
        if entry[0] == stage["floor"] and index + 1 < len(game.STAGES):
            return game.STAGES[index + 1]
    return None


def human_delta(affinity=0, mood=0):
    bits = []
    if affinity:
        bits.append("{}{} 好感".format("+" if affinity > 0 else "", affinity))
    if mood:
        bits.append("{}{} 心情".format("+" if mood > 0 else "", mood))
    return "（" + "，".join(bits) + "）" if bits else ""


def show_state(state, brief=False):
    stage = state["stage"]
    clock = state["time"]
    print("  {}   {}   {} / {}".format(
        state["girl"], stage["name"], state["affinity"], state["affinity_max"]))
    print("  现在 {}（{}）".format(clock["text"], clock["period"]))
    print("  心情 {} {}   体力 {} {}".format(
        state["mood"], bar(state["mood"], state["mood_max"]),
        state["stamina"], bar(state["stamina"], state["stamina_max"])))
    print("  金币 {}   Lv.{}   经验 {}/{}".format(
        state["coins"], state["level"], state["exp"], state["exp_need"]))
    if brief:
        return
    paragraph("她现在的态度：" + stage["attitude"], "  ")
    upcoming = next_stage(stage)
    if upcoming:
        print("  离「{}」还差 {} 点好感".format(upcoming[1], max(0, stage["ceil"] - state["affinity"])))
    else:
        print("  好感已经满了，恭喜。")
    cooling = [j for j in state["jobs"] if j["cooldown"] > 0]
    if cooling:
        print("  打工冷却：" + "，".join(
            "{} {}".format(j["name"], game.duration_text(j["cooldown"])) for j in cooling))
    if state["rest_cooldown"] > 0:
        print("  休息冷却：{}".format(game.duration_text(state["rest_cooldown"])))


def show_history(state, limit=HISTORY_SHOW):
    history = state["history"][-limit:]
    if not history:
        print("  （还没聊过什么）")
        return
    for message in history:
        who = "你：" if message["role"] == "user" else state["girl"] + "："
        paragraph(message["content"], who)


def show_shop(state):
    print("  礼物清单（现有 {} 金币）：".format(state["coins"]))
    for index, item in enumerate(state["shop"], 1):
        note = "" if item["affordable"] else "  金币不足"
        print("  {}. {} {} 金币{}".format(index, pad(item["name"], 10), item["price"], note))
        paragraph(item["desc"], "        ")


def show_jobs(state):
    clock = state["time"]
    print("  工作清单（Lv.{}，体力 {}，现在 {}）：".format(state["level"], state["stamina"], clock["text"]))
    for index, job in enumerate(state["jobs"], 1):
        if job["locked"]:
            note = "要 Lv.{}".format(job["level_req"])
        elif not job["open"]:
            note = "只在 {} 能做".format(job["window_text"])
        elif job["cooldown"] > 0:
            note = "冷却 {}".format(game.duration_text(job["cooldown"]))
        elif not job["enough_stamina"]:
            note = "体力不够（要 {}）".format(job["stamina"])
        else:
            note = "可以去做"
        print("  {}. {} {}~{} 金币  耗时 {} 小时  [{}]".format(
            index, pad(job["name"], 10), job["coins"][0], job["coins"][1],
            job["hours"], note))
        paragraph(job["desc"], "        ")


def show_activities(state):
    clock = state["time"]
    print("  娱乐清单（Lv.{}，体力 {}，金币 {}，现在 {}）：".format(
        state["level"], state["stamina"], state["coins"], clock["text"]))
    for index, act in enumerate(state["activities"], 1):
        if act["locked"]:
            note = "要 Lv.{}".format(act["level_req"])
        elif act["affinity_locked"]:
            note = "要好感 {}".format(act["affinity_req"])
        elif not act["open"]:
            note = "只在 {} 能去".format(act["window_text"])
        elif act["cooldown"] > 0:
            note = "冷却 {}".format(game.duration_text(act["cooldown"]))
        elif not act["affordable"]:
            note = "金币不够（要 {}）".format(act["cost"])
        elif not act["enough_stamina"]:
            note = "体力不够（要 {}）".format(act["stamina"])
        else:
            note = "可以回去"
        tag = "双人" if act["duo"] else "单人"
        gain = "心情 +{}".format(act["mood"])
        if act["duo"]:
            gain += "，好感 +{}".format(act["affinity"])
        print("  {}. [{}] {} {} 金币  耗时 {} 小时  {}  [{}]".format(
            index, tag, pad(act["name"], 16), act["cost"], act["hours"], gain, note))
        paragraph(act["desc"], "        ")


def show_log(state, arg):
    limit = 8
    if arg.isdigit():
        limit = max(1, min(30, int(arg)))
    events = state["events"][-limit:]
    if not events:
        print("  （还没有发生什么）")
        return
    for event in events:
        paragraph(event["text"], "  {} ".format(game.game_time_text(event["ts"])))


def show_memory(state):
    memories = state["memories"]
    if not memories:
        print("  （她还没记住什么）")
        return
    for memory in memories:
        paragraph(memory["content"], "  - ")


def thinking():
    if sys.stdout.isatty():
        sys.stdout.write("  ……她在打字")
        sys.stdout.flush()


def clear_thinking():
    if sys.stdout.isatty():
        sys.stdout.write("\r" + " " * columns() + "\r")
        sys.stdout.flush()


def pick(items, token):
    """编号（/gift 3）或 id（/gift daisy）都能用。"""
    if token.isdigit():
        index = int(token) - 1
        return items[index] if 0 <= index < len(items) else None
    for item in items:
        if item["id"] == token:
            return item
    return None


def show_clock(state):
    print("  （现在是 {} {}）".format(state["time"]["text"], state["time"]["period"]))


def next_state():
    state = game.build_state()
    show_clock(state)
    return state


def chat(text, state):
    thinking()
    try:
        result = game.do_chat(text)
    finally:
        clear_thinking()
    print()
    paragraph(result["reply"], state["girl"] + "：")
    delta = human_delta(result["affinity_delta"], result["mood_delta"])
    if delta:
        print("  " + delta)
    if result["memory_added"]:
        print("  （她记下了：{}）".format(plain(result["memory_added"])))
    return next_state()


def gift(arg, state):
    if not arg:
        show_shop(state)
        return state
    item = pick(state["shop"], arg)
    if not item:
        print("  没有这个礼物，先看看 /shop")
        return state
    thinking()
    try:
        result = game.do_gift(item["id"])
    finally:
        clear_thinking()
    print()
    paragraph(result["reply"], state["girl"] + "：")
    print("  （送出「{}」，她{}）{}".format(
        item["name"], result["reaction"], human_delta(result["affinity_delta"], result["mood_delta"])))
    return next_state()


def work(arg, state):
    if not arg:
        show_jobs(state)
        return state
    job = pick(state["jobs"], arg)
    if not job:
        print("  没有这份工作，先看看 /work")
        return state
    thinking()
    try:
        result = game.do_work(job["id"])
    finally:
        clear_thinking()
    print()
    paragraph(result["reply"], state["girl"] + "：")
    note = "（{}）".format(result["mood_note"]) if result["mood_note"] else ""
    print("  （做完「{}」，赚到 {} 金币，体力剩 {}）{}".format(
        job["name"], result["earned"], result["stamina"], note))
    return next_state()


def play(arg, state):
    if not arg:
        show_activities(state)
        return state
    act = pick(state["activities"], arg)
    if not act:
        print("  没有这个娱乐项目，先看看 /play")
        return state
    thinking()
    try:
        result = game.do_activity(act["id"])
    finally:
        clear_thinking()
    print()
    paragraph(result["reply"], state["girl"] + "：")
    if act["duo"]:
        print("  （你带着她一起去了「{}」，花了 {} 金币）".format(act["name"], act["cost"]))
    else:
        print("  （你一个人去了「{}」，花了 {} 金币）".format(act["name"], act["cost"]))
    if result["memory_added"]:
        print("  （她记下了：{}）".format(plain(result["memory_added"])))
    print("  体力剩 {}".format(result["stamina"]))
    return next_state()


def rest(state):
    thinking()
    try:
        result = game.do_rest()
    finally:
        clear_thinking()
    print()
    paragraph(result["reply"], state["girl"] + "：")
    print("  （体力恢复到 {}）".format(result["stamina"]))
    return next_state()


def new_game(arg, state):
    if arg and arg not in game.PERSONAS:
        print("  可选角色：" + "，".join(game.PERSONAS))
        return state
    try:
        answer = input("  重新开始会清空当前存档，确定吗？[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return state
    if answer not in ("y", "yes"):
        print("  好，什么都没动。")
        return state
    game.new_game(arg or None)
    state = game.build_state()
    print()
    rule("=")
    paragraph(state["events"][-1]["text"], "  ")
    rule("=")
    paragraph(state["persona"], "  ")
    show_state(state, brief=True)
    return state


def command(line, state):
    parts = line.split()
    name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if name in ("/quit", "/exit", "/q"):
        return None
    if name in ("/help", "/h", "/?"):
        print(HELP)
    elif name == "/state":
        show_state(state)
    elif name == "/shop":
        show_shop(state)
    elif name == "/gift":
        return gift(arg, state)
    elif name == "/work":
        return work(arg, state)
    elif name == "/play":
        return play(arg, state)
    elif name == "/rest":
        return rest(state)
    elif name == "/log":
        show_log(state, arg)
    elif name == "/memory":
        show_memory(state)
    elif name == "/new":
        return new_game(arg, state)
    else:
        print("  没有这个命令，/help 看一眼。")
    return state


def main():
    setup_stdio()
    db.init_db()
    if not game.get_save():
        game.new_game()
    state = game.build_state()

    rule("=")
    print("  养成游戏 · 终端版    /help 命令   /quit 退出")
    rule("=")
    if not state["history"] and state["events"]:
        paragraph(state["events"][-1]["text"], "  ")
    show_state(state)
    rule()

    while True:
        state = game.build_state()
        try:
            line = input("\n[{}] 你> ".format(state["time"]["text"])).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n下线了，存档都在。")
            return
        if not line:
            continue
        try:
            if line.startswith("/"):
                state = command(line, state)
                if state is None:
                    print("\n下线了，存档都在。")
                    return
            else:
                state = chat(line, state)
        except ValueError as exc:
            print("  " + plain(exc))
        except llm.LLMError as exc:
            print("  模型那边出问题了：" + plain(exc))
        except KeyboardInterrupt:
            print("\n（中断了，这次没写进存档）")


if __name__ == "__main__":
    main()
