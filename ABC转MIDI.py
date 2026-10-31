# -*- coding: utf-8 -*-
"""ABC 乐谱 → 鼓 / 贝斯 MIDI（解析 YuE2 产出的多声部 ABC，依赖 mido）。

当前生产链路只使用鼓与贝斯两个构建器；旋律/和弦垫转换已删除。
"""
import random
import re
from pathlib import Path

import mido

TPQ = 480
PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
MAJOR_KEYS = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
              "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}
MINOR_KEYS = {"A": 0, "E": 1, "B": 2, "F#": 3, "C#": 4, "G#": 5, "D#": 6, "A#": 7,
              "D": -1, "G": -2, "C": -3, "F": -4, "Bb": -5, "Eb": -6, "Ab": -7}
def parse_headers(text):
    hdr = {"M": (4, 4), "L": (1, 8), "Q": 120, "K": "C", "V": []}
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("%"):
            continue
        m = re.match(r"^([A-Za-z]):\s*(.*)$", s)
        if not m:
            break
        key, val = m.group(1).upper(), m.group(2).strip()
        if key == "M":
            mm = re.match(r"(\d+)\s*/\s*(\d+)", val)
            if mm:
                hdr["M"] = (int(mm.group(1)), int(mm.group(2)))
        elif key == "L":
            mm = re.match(r"(\d+)\s*/\s*(\d+)", val)
            if mm:
                hdr["L"] = (int(mm.group(1)), int(mm.group(2)))
        elif key == "Q":
            mm = re.search(r"=\s*(\d+)", val)
            if not mm:
                # YuE2 常见写法是 Q:143，而不是标准 ABC 的 Q:1/4=143
                mm = re.fullmatch(r"(\d+)", val.strip())
            if mm:
                hdr["Q"] = int(mm.group(1))
        elif key == "K":
            hdr["K"] = val
        elif key == "V":
            mm = re.match(r"([^\s]+)", val)
            if mm:
                hdr["V"].append(mm.group(1))
    return hdr


def key_signature(key):
    k = key.strip()
    minor = k.endswith("m") and len(k) > 1
    base = k[:-1] if minor else k
    sf = (MINOR_KEYS if minor else MAJOR_KEYS).get(base, 0)
    acc = {}
    if sf > 0:
        for i, n in enumerate(SHARP_ORDER[:sf]):
            acc[n] = 1
    elif sf < 0:
        for n in FLAT_ORDER[:-sf]:
            acc[n] = -1
    return sf, acc


def parse_duration(txt, i):
    """读取音符后的时值（数字与 /、附点），返回 (倍数, 新位置)。"""
    num, den, dots = 1, 1, 0
    started = False
    while i < len(txt):
        c = txt[i]
        if c.isdigit():
            j = i
            while j < len(txt) and txt[j].isdigit():
                j += 1
            num = int(txt[i:j])
            i, started = j, True
        elif c == "/":
            den = 2
            i += 1
            if i < len(txt) and txt[i].isdigit():
                j = i
                while j < len(txt) and txt[j].isdigit():
                    j += 1
                den = int(txt[i:j])
                i = j
            started = True
        elif c == ".":
            dots += 1
            i += 1
            started = True
        else:
            break
    mult = num / den
    for d in range(dots):
        mult += mult / (2 ** (d + 1))
    return (mult if started else 1.0), i


def parse_voice(text, want, collect_chords=False):
    """解析指定声部，返回 (音符, 每单位tick, 头字段, 和弦符号[(start_units, "Fm7")])。"""
    hdr = parse_headers(text)
    Lnum, Lden = hdr["L"]
    unit_ticks = TPQ * 4.0 * Lnum / Lden   # 一个默认时值 = 多少 tick
    units_per_bar = (hdr["M"][0] / hdr["M"][1]) / (Lnum / Lden)
    _, keyacc = key_signature(hdr["K"])

    voices = {}
    cur = None
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("%"):
            continue
        mv = re.match(r"^V:\s*([^\s]+)", s)
        if mv:
            cur = mv.group(1)
            voices.setdefault(cur, "")
            continue
        if re.match(r"^[A-Za-z]:", s) and not mv:
            continue
        if cur is None:
            cur = want
            voices.setdefault(cur, "")
        voices[cur] += s + " "

    if want not in voices:
        want = max(voices, key=lambda k: len(voices[k])) if voices else want
    body = voices.get(want, "")
    # 去掉装饰音、注释（引号内的和弦符号在循环里按位置采集）
    body = re.sub(r"\{[^}]*\}", " ", body)
    body = re.sub(r"%[^\n]*", " ", body)

    notes = []
    chords = []
    pos = 0.0
    i = 0
    bar_acc = dict(keyacc)   # 每小节重置临时升降号
    while i < len(body):
        c = body[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == '"':
            j = body.find('"', i + 1)
            if j < 0:
                break
            if collect_chords:
                chords.append((pos, body[i + 1:j].strip()))
            i = j + 1
            continue
        if c in "|:][":
            if c == "|":
                bar_acc = dict(keyacc)
            i += 1
            continue
        if c == "Z":   # 整小节休止
            i += 1
            mult, i = parse_duration(body, i)
            pos += units_per_bar * mult
            bar_acc = dict(keyacc)
            continue
        acc = 0
        if c in "^_=":
            if c == "^":
                acc = 1
            elif c == "_":
                acc = -1
            i += 1
            while i < len(body) and body[i] in "^_=":
                if body[i] == "^":
                    acc += 1
                elif body[i] == "_":
                    acc -= 1
                i += 1
            if i >= len(body):
                break
            c = body[i]
        if c in "z x".replace(" ", ""):
            i += 1
            mult, i = parse_duration(body, i)
            pos += mult
            continue
        if c.upper() not in PITCH:
            i += 1
            continue
        letter = c.upper()
        octv = 4 if c.isupper() else 5
        i += 1
        while i < len(body) and body[i] in ",'":
            octv += 1 if body[i] == "'" else -1
            i += 1
        mult, i = parse_duration(body, i)
        # 临时/调号升降
        if acc != 0:
            pc = (PITCH[letter] + acc) % 12
            bar_acc[letter] = acc
        else:
            pc = (PITCH[letter] + bar_acc.get(letter, 0)) % 12
        midi = 12 * (octv + 1) + pc
        dur = mult
        if i < len(body) and body[i] == "-":   # 连音线：与下一同音合并（简化：延长时值）
            i += 1
        if 0 <= midi <= 127 and dur > 0:
            notes.append((pos, dur, int(midi)))
        pos += dur
    return notes, unit_ticks, hdr, chords


def _fill_track(tr, events, channel):
    """events = [(tick, 0/1, pitch, velocity)]，按 tick 写入 delta。"""
    last = 0
    for tick, kind, pitch, vel in sorted(events, key=lambda x: (x[0], x[1])):
        delta = max(0, int(tick) - last)
        tr.append(mido.Message("note_on" if kind else "note_off", note=int(pitch),
                               velocity=int(vel), channel=int(channel), time=delta))
        last = int(tick)


# ---------------------------------------------------------------- 鼓型库
# YuE2 的 ABC 本来就没有鼓轨（正常现象）。所以鼓是「按 ABC 的节拍网格演奏出来的」：
# 用 ABC 的小节/拍位置当鼓点时间轴，用律动型决定底鼓/军鼓/踩镲落在哪几拍。
# 拍点用 16 分音符网格（ABC 的 L:1/16 → 一小节 16 格）。
#
# 律动 id 与《Beat变量库.json》「律动」池一一对应。
DRUM_PATTERNS = {
    # 直四拍：底鼓 1/3、军鼓 2/4、八分踩镲
    "straight":   dict(kick=[0, 8], snare=[4, 12], hat=[0, 2, 4, 6, 8, 10, 12, 14]),
    # 半速：底鼓 1、军鼓 3（trap 常用）
    "halftime":   dict(kick=[0, 10], snare=[8], hat=[0, 2, 4, 6, 8, 10, 12, 14]),
    # 双倍踩镲：十六分踩镲
    "doublehats": dict(kick=[0, 8], snare=[4, 12], hat=list(range(16))),
    # 摇摆八分
    "swung":      dict(kick=[0, 6], snare=[4, 12], hat=[0, 3, 6, 9, 12, 15]),
    # 切分
    "broken":     dict(kick=[0, 7, 10], snare=[4, 12], hat=list(range(16))),
    # 三连底鼓
    "triplet":    dict(kick=[0, 5, 10], snare=[4, 12], hat=[0, 4, 8, 12]),
    # 四踩底鼓 + 反拍踩镲
    "fourfloor":  dict(kick=[0, 4, 8, 12], snare=[4, 12], hat=[2, 6, 10, 14]),
    # dembow：底鼓切分、军鼓在 3
    "dembow":     dict(kick=[0, 7, 10], snare=[8], hat=[0, 2, 4, 6, 8, 10, 12, 14]),
    # 交错节奏
    "poly":       dict(kick=[0, 5, 10], snare=[4, 12], hat=[0, 2, 4, 6, 8, 10, 12, 14]),
}
GM_KICK, GM_SNARE, GM_HAT, GM_OPEN, GM_CLAP = 36, 38, 42, 46, 39


def build_abc_drum_midi(abc_path, mid_path, pattern="straight",
                        velocity=100, seed=7, tempo_bpm=None):
    """按 ABC 的小节/拍位置演奏出一整条鼓轨。

    鼓型库统一按 4/4 的 16 分音符网格（一小节 16 格）编写，与 ABC 的 L 无关，
    所以 L:1/8、L:1/32 也能落在正确拍点上。非 4/4 目前会明确报错。
    tempo_bpm 为 None 时用 ABC 的 Q，否则用外部推导速度（通常来自音频小节长）。
    返回 {"小节": n, "鼓点": n, "秒": sec, "BPM": bpm}。
    """
    pat = DRUM_PATTERNS.get(pattern)
    if pat is None:
        raise RuntimeError(f"未知律动型 {pattern}，可用：{'、'.join(sorted(DRUM_PATTERNS))}")
    text = Path(abc_path).read_text(encoding="utf-8", errors="replace")
    mel_ins, _unit_ticks, hdr, chords_ins = parse_voice(text, "Ins", collect_chords=True)
    mel_vocal, _, _, chords_vocal = parse_voice(text, "Vocal", collect_chords=True)
    all_notes = mel_ins + mel_vocal
    all_chords = chords_ins + chords_vocal
    Lnum, Lden = hdr["L"]
    units_per_bar = (hdr["M"][0] / hdr["M"][1]) / (Lnum / Lden)   # 一小节多少个 L 单位
    steps_per_bar = int(round(hdr["M"][0] * 16 / hdr["M"][1]))    # 4/4 = 16 格
    if steps_per_bar != 16:
        raise RuntimeError(
            f"鼓型库按 4/4 的 16 分音符网格编写，当前拍号 "
            f"{hdr['M'][0]}/{hdr['M'][1]} 不支持；可改用 --鼓源 none，或先把 ABC 转成 4/4"
        )
    bpm = float(tempo_bpm or hdr["Q"])
    step_ticks = TPQ / 4.0
    total_units = 0.0
    for start, dur, _p in all_notes:
        total_units = max(total_units, start + dur)
    for pos, _n in all_chords:
        total_units = max(total_units, pos)
    if all_chords:
        total_units = max(total_units, max(p for p, _ in all_chords) + units_per_bar)
    total_bars = max(1, int(round(total_units / units_per_bar)))

    rng = random.Random(seed)
    ev = []

    def put(step, note, vel):
        t0 = int(round(step * step_ticks))
        t1 = t0 + max(1, int(round(step_ticks * 0.5)))
        ev.append((t0, 1, note, vel))
        ev.append((t1, 0, note, 0))

    for bar in range(total_bars):
        base = bar * steps_per_bar
        for s in pat["kick"]:
            put(base + s, GM_KICK, velocity)
        for s in pat["snare"]:
            put(base + s, GM_SNARE, velocity - 8)
        for s in pat["hat"]:
            put(base + s, GM_HAT, max(40, velocity - 26 + rng.randint(-4, 4)))

    mid = mido.MidiFile(ticks_per_beat=TPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="Drums", time=0))
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    tr.append(mido.MetaMessage("time_signature", numerator=hdr["M"][0],
                               denominator=hdr["M"][1], time=0))
    tr.append(mido.Message("program_change", program=0, channel=9, time=0))
    _fill_track(tr, ev, 9)
    Path(mid_path).parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(mid_path))
    return {"小节": total_bars, "鼓点": len(ev) // 2, "秒": mid.length,
            "律动": pattern, "BPM": bpm}


BASS_PROGRAM = 33   # MIDI program_change 33 -> GM 34 Fingered Bass
# 每小节固定贝斯型：(16 分网格位置, 相对根音的半音)
BASS_PATTERN = ((0, 0), (6, 0), (8, 7), (12, 12))


def 和弦根音(name, low=28, high=43):
    """从 "Fm7" / "Bb" 里取根音，落在 low~high 的贝斯音区。"""
    m = re.match(r"^([A-Ga-g])([#b]?)(.*)$", str(name or "").strip())
    if not m:
        return None
    acc = 1 if m.group(2) == "#" else (-1 if m.group(2) == "b" else 0)
    pc = (PITCH[m.group(1).upper()] + acc) % 12
    pitch = 36 + pc                 # C2=36
    while pitch > high:
        pitch -= 12
    while pitch < low:
        pitch += 12
    return pitch


def build_bass_midi(abc_path, mid_path, tempo_bpm=None):
    """按 ABC 和弦符号生成一条锁死的根音贝斯轨（GM 34 Fingered Bass）。

    每小节固定四个点：1 拍根音、2.5 拍根音、3 拍五度、4 拍高八度。
    和弦变化时按当前和弦重新取根音；返回 {"音符","和弦","小节","秒","BPM"}。
    """
    import bisect
    text = Path(abc_path).read_text(encoding="utf-8", errors="replace")
    notes, unit_ticks, hdr, chords = parse_voice(text, "Vocal", collect_chords=True)
    if not chords:
        _, _, _, chords = parse_voice(text, "Ins", collect_chords=True)
    if not chords:
        raise RuntimeError("ABC 里没有和弦符号，无法生成贝斯")
    Lnum, Lden = hdr["L"]
    units_per_bar = (hdr["M"][0] / hdr["M"][1]) / (Lnum / Lden)
    bpm = float(tempo_bpm or hdr["Q"])
    total_units = max(
        [s + d for s, d, _ in notes] + [p for p, _ in chords] + [units_per_bar]
    )
    total_bars = max(1, int(round(total_units / units_per_bar)))

    segments = []
    for k, (pos, name) in enumerate(chords):
        end_pos = chords[k + 1][0] if k + 1 < len(chords) else pos + units_per_bar
        start = int(round(pos * unit_ticks))
        end = int(round(end_pos * unit_ticks))
        if end > start:
            segments.append((start, end, name))
    segments.sort(key=lambda x: x[0])
    if not segments:
        raise RuntimeError("ABC 和弦位置无效，无法生成贝斯")
    starts = [s for s, _, _ in segments]

    def 当前和弦(tick):
        idx = bisect.bisect_right(starts, tick) - 1
        if idx < 0:
            return segments[0][2]
        return segments[idx][2]

    step_ticks = TPQ / 4.0
    events = []
    for bar in range(total_bars):
        for step, interval in BASS_PATTERN:
            tick = int(round((bar * 16 + step) * step_ticks))
            root = 和弦根音(当前和弦(tick))
            if root is None:
                continue
            pitch = root + interval
            while pitch > 43:
                pitch -= 12
            while pitch < 28:
                pitch += 12
            vel = 92 if interval == 0 else 84
            end = tick + max(1, int(round(step_ticks * 0.8)))
            events.append((tick, 1, pitch, vel))
            events.append((end, 0, pitch, 0))

    mid = mido.MidiFile(ticks_per_beat=TPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("track_name", name="Bass", time=0))
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    tr.append(mido.MetaMessage("time_signature", numerator=hdr["M"][0],
                               denominator=hdr["M"][1], time=0))
    tr.append(mido.Message("program_change", program=BASS_PROGRAM, channel=2, time=0))
    _fill_track(tr, events, 2)
    Path(mid_path).parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(mid_path))
    return {"音符": len(events) // 2, "和弦": len(chords), "小节": total_bars,
            "秒": mid.length, "BPM": bpm}
