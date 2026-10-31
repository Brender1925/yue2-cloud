# -*- coding: utf-8 -*-
"""重奏（锁死鼓 + 贝斯）工程合成。

输入：完整歌曲（mp3/wav/flac）+ ABC 谱 + 英文曲名。
输出固定 7 个工程文件：
  <名称>_谱.txt / <名称>_鼓.mid / <名称>_贝斯.mid
  <名称>_鼓重奏.wav / <名称>_贝斯重奏.wav
  <名称>_完整版.wav / <名称>_高潮版.wav

乐器锁死：鼓走 SoundFont 鼓组（通道 9），贝斯走 GM 34 Fingered Bass。
高潮版直接从 ABC 谱的段落标记（% chorus 等）定位，取约 24 秒；
没有段落标记时退回“小节音符密度”最高的片段。起点一律对齐小节线。
用法：
  python 重奏_鼓贝斯.py <歌曲> --谱 <ABC.txt> --输出 <目录> --名称 <英文名> [--律动 <id>]
"""
import argparse
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from ABC转MIDI import parse_headers, parse_voice, build_abc_drum_midi, build_bass_midi

PROJECT = Path(__file__).resolve().parent
SR = 44100
SF2 = PROJECT / "音源" / "MuseScore_General.sf3"
FLUID = PROJECT / "音源" / "fluid" / "bin" / "fluidsynth.exe"
DRUM_DB = -10.0
BASS_DB = -12.0
CLIMAX_SECONDS = 24.0    # 高潮版时长（要求 20~30 秒，取 24）
FADE_MS = 10
# 段落标记 → 高潮优先级（越大越优先）
SECTION_PRIORITY = {"chorus": 3, "hook": 3, "drop": 3, "refrain": 3,
                    "pre-chorus": 1, "bridge": 1,
                    "verse": 0, "interlude": 0, "intro": -1, "outro": -1}


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))


def edge_fade(y, ms=FADE_MS):
    n = min(len(y) // 2, max(1, int(ms / 1000 * SR)))
    y[:n] *= np.linspace(0, 1, n)
    y[-n:] *= np.linspace(1, 0, n)
    return y


def render_midi(mid, wav):
    if not FLUID.exists():
        raise SystemExit(f"缺少 FluidSynth：{FLUID}")
    if not SF2.exists():
        raise SystemExit(f"缺少音源：{SF2}")
    cmd = [str(FLUID), "-ni", "-F", str(wav), "-r", str(SR), "-O", "float", "-g", "0.9",
           "-o", "synth.reverb.active=0", "-o", "synth.chorus.active=0",
           "-o", "synth.polyphony=1024", str(SF2), str(mid)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"FluidSynth 渲染失败：{r.stderr[-500:]}")
    return wav


def 加载音频(path, sr=SR):
    try:
        y, sr0 = sf.read(str(path), always_2d=True, dtype="float32")
        y = y.mean(axis=1)
        if sr0 != sr:
            g = np.gcd(int(sr0), int(sr))
            y = resample_poly(y, sr // g, sr0 // g).astype(np.float32)
        return np.asarray(y, dtype=np.float32), sr
    except Exception:
        import librosa
        y, _ = librosa.load(str(path), sr=sr, mono=True)
        return np.asarray(y, dtype=np.float32), sr


def 裁到(y, n):
    if len(y) >= n:
        return y[:n].copy()
    return np.pad(y, (0, n - len(y)))


# ---------------------------------------------------------- 谱面高潮

def _谱结构(text):
    """返回 (units_per_bar, total_bars, 每声部按 (start_units,小节) 排序的音符,
            段落列表[(名字, 起始小节, 结束小节)])。"""
    hdr = parse_headers(text)
    Lnum, Lden = hdr["L"]
    upb = (hdr["M"][0] / hdr["M"][1]) / (Lnum / Lden)

    notes = {}
    total_units = 0.0
    for voice in ("Ins", "Vocal"):
        nts, _, _, chords = parse_voice(text, voice, collect_chords=True)
        notes[voice] = sorted(nts, key=lambda x: x[0])
        for s, d, _ in nts:
            total_units = max(total_units, s + d)
        for s, _ in chords:
            total_units = max(total_units, s + upb)
    total_bars = max(1, int(np.ceil(total_units / upb))) if upb else 1

    # 段落标记：标记名 + 它后面第一个非空内容行的序号
    lines = text.splitlines()
    mark_lines = [(i, m.group(1).strip().lower())
                  for i, ln in enumerate(lines)
                  if (m := re.match(r"^\s*%\s*([A-Za-z\- ]+?)\s*$", ln))]

    # 段落起点小节：标记之后、下一个标记之前，任意声部里第一个出现的音符所在小节。
    # 用“行序 → 该行音符起点”需要把音符映射回行，这里改用语义更稳的办法：
    # 逐行按声部游标累加单位（与 parse_voice 同款规则），标记挂当前游标小节。
    voice = None
    curs = {"Ins": 0.0, "Vocal": 0.0}
    sections = []          # (name, start_bar)
    pending = []           # 尚未见到内容行的段落名
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        mm = re.match(r"^%\s*([A-Za-z\- ]+?)\s*$", s)
        if mm:
            pending.append(mm.group(1).strip().lower())
            continue
        mv = re.match(r"^V:\s*(\S+)", s)
        if mv:
            v = mv.group(1).lower()
            voice = "Vocal" if v.startswith("vocal") else ("Ins" if v.startswith("ins") else voice)
            continue
        if re.match(r"^[A-Za-z]:", s):
            continue
        if voice is None:
            continue
        units = _行单位数(s)
        if units <= 0:
            continue
        bar_now = int(curs[voice] // upb) if upb else 0
        while pending:
            sections.append((pending.pop(0), bar_now))
        curs[voice] += units

    # 段落结束小节 = 下一个段落起点，最后一个到全曲末尾
    sec = []
    for i, (name, sb) in enumerate(sections):
        eb = sections[i + 1][1] if i + 1 < len(sections) else total_bars
        sec.append((name, sb, max(sb + 1, eb)))
    return upb, total_bars, sec


def _行单位数(line):
    """一行 ABC 内容包含的 L 单位数（音符/休止），整小节休止 Z 计 16 单位。"""
    units = 0.0
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t\r\n":
            i += 1
        elif c == "Z":
            i += 1
            mult, i = _读时值(line, i)
            units += 16 * mult
        elif c == "z":
            i += 1
            mult, i = _读时值(line, i)
            units += mult
        elif c in "|[]()":
            i += 1
        elif c in "^_=":
            i += 1
        elif c == '"':
            j = line.find('"', i + 1)
            i = n if j < 0 else j + 1
        elif c in "{}":
            i += 1
        else:
            i += 1
            while i < n and line[i] in ",'":
                i += 1
            mult, i = _读时值(line, i)
            if i < n and line[i] == "-":
                i += 1
            units += mult
    return units


def _读时值(txt, i):
    num, den, started, dots = 1, 1, False, 0
    j = i
    while j < len(txt) and txt[j].isdigit():
        started = True
        j += 1
    if started:
        num = int(txt[i:j])
        i = j
    if i < len(txt) and txt[i] == "/":
        i += 1
        j = i
        while j < len(txt) and txt[j].isdigit():
            j += 1
        den = int(txt[i:j]) if j > i else 2
        i = j
    mult = num / den
    while i < len(txt) and txt[i] == ".":
        dots += 1
        i += 1
    for d in range(dots):
        mult += mult / (2 ** (d + 1))
    return mult, i


def _密度最高起点(text, n_bars, total_bars, upb):
    density = {}
    for voice in ("Ins", "Vocal"):
        nts, _, _, _ = parse_voice(text, voice)
        for st, _, _ in nts:
            b = int(st // upb) if upb else 0
            density[b] = density.get(b, 0) + 1
    best_bar, best_score = 0, -1.0
    for b0 in range(0, max(1, total_bars - n_bars + 1)):
        score = sum(density.get(b, 0) for b in range(b0, b0 + n_bars))
        if score > best_score:
            best_bar, best_score = b0, score
    return best_bar


def 谱面高潮起点(text, bar_sec, song_samples):
    """返回 (起点采样, 长度采样, 依据)。"""
    upb, total_bars, sections = _谱结构(text)
    n_bars = max(1, int(np.ceil(CLIMAX_SECONDS / bar_sec)))
    length = min(song_samples, int(round(n_bars * bar_sec * SR)))
    if song_samples <= length:
        return 0, song_samples, "歌曲短于24秒"

    chosen = None
    known = [s for s in sections if s[0] in SECTION_PRIORITY]
    if known:
        best_pri = max(SECTION_PRIORITY[s[0]] for s in known)
        top = [s for s in known if SECTION_PRIORITY[s[0]] == best_pri]
        chosen = top[-1]   # 同名高潮取最后一个

    if chosen:
        name, sb, eb = chosen
        span = eb - sb
        start_bar = sb if span >= n_bars else int(round(sb + span / 2 - n_bars / 2))
        why = f"段落 {name}（第{sb + 1}小节起）"
    else:
        start_bar = _密度最高起点(text, n_bars, total_bars, upb)
        why = "无段落标记，按小节音符密度"

    max_bar = max(0, int(song_samples / (bar_sec * SR)) - n_bars)
    start_bar = max(0, min(start_bar, max_bar))
    start_sample = int(round(start_bar * bar_sec * SR))
    length = min(length, song_samples - start_sample)
    return start_sample, length, why


def 音频高潮起点(audio, sr, bar_sec, song_samples, n_bars):
    """在完整版上用短时能量滑窗取最强连续片段，起点吸附小节线。

    返回 (起点采样, 长度采样, 依据)。纯 numpy，无额外依赖。
    """
    if song_samples <= 0 or len(audio) == 0:
        return 0, song_samples, "空音频"
    dur = int(round(n_bars * bar_sec * sr))
    if song_samples <= dur:
        return 0, song_samples, "歌曲短于24秒"
    win = max(1, int(0.1 * sr))
    energy = np.array([rms(audio[i:i + win]) for i in range(0, len(audio), win)],
                      dtype=np.float64)
    nw = max(1, dur // win)
    best_i, best_e = 0, -1.0
    for i in range(0, len(energy) - nw + 1):
        e = float(energy[i:i + nw].sum())
        if e > best_e:
            best_e, best_i = e, i
    bar_samples = bar_sec * sr
    start_bar = int(round(best_i * win / bar_samples))
    max_bar = max(0, int(song_samples / bar_samples) - n_bars)
    start_bar = max(0, min(start_bar, max_bar))
    start_sample = int(round(start_bar * bar_samples))
    length = min(dur, song_samples - start_sample)
    return start_sample, length, "完整版短时能量最强"


def 校验名称(name):
    if not re.fullmatch(r"[A-Z][a-z]{4,6}", name or ""):
        raise ValueError("曲名必须是 5~7 个英文字母，首字母大写，例如 Varek")
    return name


def 合成工程(song_path, abc_path, out_dir, name, 律动="straight", 高潮="谱面"):
    name = 校验名称(name)
    song_path, abc_path = Path(song_path), Path(abc_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    text = abc_path.read_text(encoding="utf-8", errors="replace")
    hdr = parse_headers(text)
    bpm = float(hdr["Q"] or 120)
    num, den = hdr["M"]
    bar_sec = 60.0 * (num * 4.0 / den) / bpm

    (out / f"{name}_谱.txt").write_text(text, encoding="utf-8")

    drum_mid = out / f"{name}_鼓.mid"
    bass_mid = out / f"{name}_贝斯.mid"
    drum_stat = build_abc_drum_midi(abc_path, drum_mid, pattern=律动, tempo_bpm=bpm)
    bass_stat = build_bass_midi(abc_path, bass_mid, tempo_bpm=bpm)

    drum_raw = out / "_鼓重奏原始.wav"
    bass_raw = out / "_贝斯重奏原始.wav"
    render_midi(drum_mid, drum_raw)
    render_midi(bass_mid, bass_raw)

    song, _ = 加载音频(song_path)
    n = len(song)
    drum, _ = 加载音频(drum_raw)
    bass, _ = 加载音频(bass_raw)
    drum = edge_fade(裁到(drum, n))
    bass = edge_fade(裁到(bass, n))

    song_rms = rms(song)
    drum *= (song_rms * 10 ** (DRUM_DB / 20.0)) / (rms(drum) + 1e-9)
    bass *= (song_rms * 10 ** (BASS_DB / 20.0)) / (rms(bass) + 1e-9)

    mix = song + drum + bass
    gain = song_rms / (rms(mix) + 1e-9)
    if float(np.abs(mix).max() * gain) > 0.97:
        gain *= 0.97 / float(np.abs(mix).max() * gain)
    full = (mix * gain).astype(np.float32)
    drum_out = (drum * gain).astype(np.float32)
    bass_out = (bass * gain).astype(np.float32)
    edge_fade(full)

    drum_path = out / f"{name}_鼓重奏.wav"
    bass_path = out / f"{name}_贝斯重奏.wav"
    full_path = out / f"{name}_完整版.wav"
    climax_path = out / f"{name}_高潮版.wav"
    sf.write(str(drum_path), drum_out, SR, subtype="PCM_24")
    sf.write(str(bass_path), bass_out, SR, subtype="PCM_24")
    sf.write(str(full_path), full, SR, subtype="PCM_24")

    n_bars = max(1, int(np.ceil(CLIMAX_SECONDS / bar_sec)))
    if 高潮 == "能量":
        start, length, why = 音频高潮起点(full, SR, bar_sec, len(full), n_bars)
    else:
        start, length, why = 谱面高潮起点(text, bar_sec, len(full))
    climax = full[start:start + length].copy()
    edge_fade(climax)
    sf.write(str(climax_path), climax, SR, subtype="PCM_24")

    for p in (drum_raw, bass_raw):
        p.unlink(missing_ok=True)

    return {
        "名称": name,
        "谱": str(out / f"{name}_谱.txt"),
        "鼓MIDI": str(drum_mid), "贝斯MIDI": str(bass_mid),
        "鼓重奏": str(drum_path), "贝斯重奏": str(bass_path),
        "完整版": str(full_path), "高潮版": str(climax_path),
        "BPM": bpm, "小节": drum_stat["小节"], "鼓点": drum_stat["鼓点"],
        "贝斯音符": bass_stat["音符"], "和弦": bass_stat["和弦"],
        "歌曲秒": round(n / SR, 2),
        "高潮起始秒": round(start / SR, 2), "高潮秒": round(length / SR, 2),
        "高潮依据": why,
        "峰值": round(float(np.abs(full).max()), 6), "RMS": round(rms(full), 6),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="重奏（锁死鼓+贝斯）工程合成")
    ap.add_argument("歌曲", help="完整歌曲 mp3/wav/flac")
    ap.add_argument("--谱", required=True, help="ABC 乐谱 txt")
    ap.add_argument("--输出", required=True, help="工程输出目录")
    ap.add_argument("--名称", required=True, help="5~7 个英文字母，首字母大写")
    ap.add_argument("--律动", default="straight",
                    help="鼓型 id（straight/halftime/doublehats/swung/broken/triplet/fourfloor/dembow/poly）")
    ap.add_argument("--高潮", default="谱面", choices=["谱面", "能量"],
                    help="高潮版定位：谱面=按 ABC 谱段落/密度；能量=完整版短时能量扫描取听感最强")
    args = ap.parse_args(argv)
    r = 合成工程(args.歌曲, args.谱, args.输出, args.名称, 律动=args.律动, 高潮=args.高潮)
    for key in ("谱", "鼓MIDI", "贝斯MIDI", "鼓重奏", "贝斯重奏", "完整版", "高潮版"):
        print(f"{key}: {r[key]}")
    print(f"{r['名称']}｜{r['歌曲秒']}s｜{r['BPM']} BPM｜"
          f"高潮 {r['高潮起始秒']}s/{r['高潮秒']}s（{r['高潮依据']}）")


if __name__ == "__main__":
    main()
