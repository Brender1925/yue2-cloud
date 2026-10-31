# -*- coding: utf-8 -*-
"""YuE2 Beat 工厂 · 交互式启动器。

双击 启动器.bat（Windows）或运行 python 启动器.py。
选择后端（云端 RunningHub / 本地 ComfyUI）和数量，其余全自动：
  装配风格（含律动）→ 生成 Beat 底轨 + ABC 谱 → 本地重奏 →
  自动命名 → 输出完整工程包到 Beat售卖/<曲名>/。
流程复用 生成歌曲.py 与 重奏_鼓贝斯.py，不复制业务代码。
"""
import importlib.util
import random
import re
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


def 加载(文件名):
    """按文件路径加载项目脚本为模块（中文文件名不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("yue2_" + 文件名.split(".")[0],
                                                  str(PROJECT / 文件名))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def 随机曲名():
    """生成 5~7 字母、首字母大写、可拼读的随机曲名（如 Bikon / Cliprur）。"""
    开 = ["B", "C", "Cl", "D", "F", "Fl", "G", "Gr", "K", "P",
          "S", "Sn", "T", "Tr", "V", "W"]
    尾 = ["ikon", "ipur", "star", "ulun", "ovik", "emar", "adex", "inis",
          "oral", "ugon", "yvar", "ilin", "omos", "uruk", "idel", "ebum"]
    while True:
        name = random.choice(开) + random.choice(尾)
        if re.fullmatch(r"[A-Z][a-z]{4,6}", name):
            return name


def 新的文件(目录, 扩展名):
    """目录下修改时间最新的指定扩展名文件；没有则返回 None。"""
    files = [p for p in Path(目录).glob(f"*{扩展名}") if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def 检查配置():
    print("\n===== 配置自检 =====")
    ok = True
    try:
        import json
        cfg = json.loads((PROJECT / "配置/云端配置.json").read_text(encoding="utf-8"))
        key = cfg.get("接口", {}).get("api_key", "")
        wf = cfg.get("接口", {}).get("workflow_id", "")
        print(f"  API key      : {'✓ 已填写' if key else '✗ 未填写（配置/云端配置.json）'}")
        print(f"  workflow_id  : {'✓ 已填写' if wf else '✗ 未填写（先上传工作流到自己的 RunningHub 账户）'}")
        ok = ok and bool(key and wf)
    except Exception as e:
        print(f"  ✗ 云端配置读取失败: {e}")
        ok = False
    for m in ("numpy", "soundfile", "mido"):
        try:
            __import__(m)
            print(f"  依赖 {m:<9}: ✓")
        except ImportError:
            print(f"  ✗ 依赖 {m} 缺失 —— 先执行 pip install -r requirements.txt")
            ok = False
    fs = PROJECT / "音源/fluid/bin/fluidsynth.exe"
    sf3 = PROJECT / "音源/MuseScore_General.sf3"
    print(f"  FluidSynth   : {'✓' if fs.exists() else '✗ 缺失 ' + str(fs)}")
    print(f"  SoundFont    : {'✓' if sf3.exists() else '✗ 缺失 ' + str(sf3)}")
    ok = ok and fs.exists() and sf3.exists()
    print("===== 全部就绪 =====" if ok else "===== 有缺失项，按提示处理 =====")
    return ok


# ABC 调式后缀 → (中文名, 相对大调的五度圈偏移)
调式表 = {
    "":    ("大调", 0), "maj": ("大调", 0), "major": ("大调", 0), "ion": ("大调", 0),
    "m":   ("小调", -3), "min": ("小调", -3), "minor": ("小调", -3), "aeo": ("小调", -3),
    "dor": ("多利亚调式", -2),
    "phr": ("弗里吉亚调式", -4),
    "lyd": ("利底亚调式", 1),
    "mix": ("混合利底亚调式", -1),
    "loc": ("洛克里亚调式", -5),
}
# 自然音级字母的基础五度圈位置（升号数；F 为 1 个降号）
音级五度 = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F": -1}


def 解析调性(谱路径):
    """从 ABC 谱 K: 头解析 (音名, 调号, 调式)；解析不出返回全未知。

    调号按五度圈计算升降号数量（含调式偏移），如 K:Bb → 音名"降B"、
    调号"2个降号"、调式"大调"。
    """
    import re
    text = Path(谱路径).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^K:\s*([A-Ga-g])([#b]*)\s*(\S*)\s*$", text, re.M)
    if not m:
        return "未知", "未知", "未知"
    letter = m.group(1).upper()
    变音, 后缀 = m.group(2), m.group(3).lower()
    音名 = ("升" if "#" in 变音 else "降" if "b" in 变音 else "") + letter

    偏移 = sum(7 if c == "#" else -7 for c in 变音)
    调式, 式偏移 = 调式表.get(后缀, ("大调", 0))
    五度 = 音级五度[letter] + 偏移 + 式偏移
    if 五度 > 0:
        调号 = f"{五度}个升号"
    elif 五度 < 0:
        调号 = f"{-五度}个降号"
    else:
        调号 = "无升降号"
    return 音名, 调号, 调式


def 写信息文件(输出目录, 名称, bpm, 曲风, 谱路径):
    """随工程包输出 <名称>_信息.txt：BPM / 音名 / 调号 / 调式 / 曲风。"""
    音名, 调号, 调式 = 解析调性(谱路径)
    信息 = 输出目录 / f"{名称}_信息.txt"
    信息.write_text(
        f"BPM: {bpm}\n音名: {音名}\n调号: {调号}\n调式: {调式}\n曲风: {曲风}\n",
        encoding="utf-8")
    print(f"信息文件: {信息}")


# ============ 回灌链路 ============
# 种子参数（Coral 配方）：第 1 首的提示词从这里拼装；
# 之后每首生成完，从谱面实测 BPM/拍号/调 回灌进参考，滚动影响下一首。
# 曲风与律动谱里读不到（谱只有音符，无音色/鼓组），由这条链固定传递。
基础参考 = {
    "曲风": "Techno",
    "bpm": 132,
    "调描述": "F 小调",
    "律动": "straight 四踩底鼓（four-on-the-floor）",
    "律动id": "fourfloor",  # 本地重奏鼓机对应的鼓型
    "质感段": "工业质感打击乐、金属敲击、催眠合成器琶音序列、噪声纹理",
}
回灌参考 = dict(基础参考)

# 防同质化的细微变化池：每次调用随机取一条，曲风/律动/核心质感不动
氛围变化池 = [
    "暗色仓库氛围",
    "深夜地下俱乐部氛围",
    "雾气弥漫的工业空间氛围",
    "冷峻的混凝土空间氛围",
]
点缀变化池 = [
    "合成弦乐点缀、riser 与白噪声过渡",
    "金属反镲与回声过渡点缀",
    "微弱人声切片点缀、上升音效过渡",
    "钟琴点缀、riser 与噪声扫频过渡",
]


def 读谱参数(谱路径):
    """从 ABC 谱头实测回灌参数：BPM（Q:）、拍号（M:）、调（K:）。

    BPM 半速记谱兜底：读出的值低于 100 时翻倍（并记录原始值）。
    """
    text = Path(谱路径).read_text(encoding="utf-8", errors="replace")
    out = {}
    m = (re.search(r"^Q:\s*\d+/\d+\s*=\s*(\d+)", text, re.M)
         or re.search(r"^Q:\s*(\d+)", text, re.M))
    if m:
        bpm = int(m.group(1))
        if bpm < 100 and bpm * 2 <= 190:
            out["bpm_原始"] = bpm
            bpm *= 2
            out["bpm_半速修正"] = True
        out["bpm"] = bpm
    m = re.search(r"^M:\s*(\S+)", text, re.M)
    if m:
        out["拍号"] = m.group(1)
    音名, 调号, 调式 = 解析调性(谱路径)
    if 音名 != "未知":
        out["调描述"] = f"{音名} {调式}"
    return out


def 组装提示词(参考):
    """由回灌参考拼出 style 提示词。

    防同质化设计：BPM 用回灌值±5 的区间（给模型自由度），
    氛围词与点缀词每次从变化池随机取一条；曲风/律动/核心质感保持不变。
    """
    lo, hi = 参考["bpm"] - 5, 参考["bpm"] + 5
    return (f"参考以下风格创作一首全新曲目：{参考['曲风']}，{lo}-{hi} BPM，"
            f"{参考['调描述']}，{参考['律动']}，极强律动感与节奏感，{参考['质感段']}。"
            "在保持此风格与律动感的前提下，乐器编配更加丰富：分层叠加明亮琶音、"
            "复古模拟合成器主奏、氛围合成器铺底、多层打击乐、"
            f"{random.choice(点缀变化池)}。"
            "严格不使用任何贝斯乐器——无贝斯线、无低音、无 sub bass。"
            f"副歌高潮前置，{random.choice(氛围变化池)}，结构紧凑，loop-friendly，纯音乐无人声。")


def 生成一个Beat(序号, 总数, 后端):
    """单个 Beat 的完整流程：回灌提示词 → 生成（云端/本地）→ 重奏 → 实测回灌。

    生成产物落在 生成测试/<曲名>/ 暂存，出包成功后自动清除；
    失败时保留该目录，便于排查或手动补跑重奏。
    """
    生成 = 加载("生成歌曲.py")
    重奏 = 加载("重奏_鼓贝斯.py")

    print(f"\n{'=' * 46}")
    print(f"  Beat {序号}/{总数}")
    print(f"{'=' * 46}")

    名称 = 随机曲名()

    # 1. 由回灌参考拼提示词（第 1 首 = 种子参数，之后 = 上一首谱面实测）
    style = 组装提示词(回灌参考)
    print(f"[1/3] 回灌参考：曲风={回灌参考['曲风']} BPM={回灌参考['bpm']} "
          f"调={回灌参考['调描述']} 律动={回灌参考['律动id']}")
    print(f"      {style}")

    # 2. 生成 Beat 底轨 + ABC 谱（请求体只上传 style，其余节点由工作流自己负责）
    print(f"[2/3] {'云端' if 后端 == 'cloud' else '本地'}生成 Beat 底轨 + ABC 谱...")
    暂存目录 = PROJECT / "生成测试" / 名称
    暂存目录.mkdir(parents=True, exist_ok=True)
    try:
        生成.主(["--后端", 后端, "--output", str(暂存目录), "--style", style])
    except SystemExit as e:
        if e.code:
            print(f"✗ 生成失败，本首跳过（产物保留在 {暂存目录}）")
            return False
    except Exception as e:
        print(f"✗ 生成异常: {e}（产物保留在 {暂存目录}）")
        return False
    歌曲 = 新的文件(暂存目录, ".mp3")
    谱 = 新的文件(暂存目录, ".txt")
    if not 歌曲 or not 谱:
        print(f"✗ 未找到生成的音频/乐谱，本首跳过（产物保留在 {暂存目录}）")
        return False

    # 3. 重奏（鼓 + 贝斯渲染 → 合成 → 裁高潮）→ 完整工程包
    律动id = 回灌参考["律动id"]
    print(f"[3/3] 本地重奏：曲名={名称} 律动={律动id} ...")
    输出目录 = PROJECT / "Beat售卖" / 名称
    try:
        重奏.main([str(歌曲), "--谱", str(谱),
                   "--输出", str(输出目录), "--名称", 名称,
                   "--律动", 律动id, "--高潮", "谱面"])
    except SystemExit as e:
        if e.code:
            print(f"✗ 本地重奏失败（暂存保留在 {暂存目录}）")
            return False
    except Exception as e:
        print(f"✗ 本地重奏异常: {e}（暂存保留在 {暂存目录}）")
        return False
    # 实测回灌：从工程包里的谱读真实 BPM/拍号/调，更新参考并写入信息文件
    谱路径 = 输出目录 / f"{名称}_谱.txt"
    实测 = 读谱参数(谱路径)
    if 实测.get("bpm_半速修正"):
        print(f"  回灌注记：谱面 Q={实测['bpm_原始']} 为半速记谱，按 {实测['bpm']} 计")
    写信息文件(输出目录, 名称, 实测.get("bpm", 回灌参考["bpm"]),
              回灌参考["曲风"], 谱路径)
    if "bpm" in 实测:
        回灌参考["bpm"] = 实测["bpm"]
    if "拍号" in 实测:
        回灌参考["拍号"] = 实测["拍号"]
    if "调描述" in 实测:
        回灌参考["调描述"] = 实测["调描述"]
    print(f"  回灌 → 下一首参考：BPM={回灌参考['bpm']} "
          f"拍号={回灌参考.get('拍号', '?')} 调={回灌参考['调描述']}")
    shutil.rmtree(暂存目录, ignore_errors=True)
    print(f"✓ Beat 完成 → Beat售卖/{名称}/")
    return True


def 主():
    print("=" * 46)
    print("   YuE2 Beat 工厂 · 启动器")
    print("=" * 46)
    while True:
        print("""
[1] 生成 Beat（选择云端/本地，输入数量，全自动出完整工程包）
[2] 配置自检（凭据 / 依赖 / 音源）
[0] 退出""")
        c = input("请选择: ").strip()
        if c == "1":
            b = input("后端：[1] 云端 RunningHub（回车）  [2] 本地 ComfyUI : ").strip()
            后端 = "local" if b == "2" else "cloud"
            s = input("生成数量（回车=1）: ").strip()
            try:
                n = int(s) if s else 1
            except ValueError:
                print("数量无效，按 1 处理"); n = 1
            if n < 1:
                n = 1
            (PROJECT / "Beat售卖").mkdir(exist_ok=True)
            (PROJECT / "生成测试").mkdir(exist_ok=True)
            回灌参考.clear()
            回灌参考.update(基础参考)  # 每批从种子参数（Coral 配方）重新起步
            成功 = 0
            for i in range(1, n + 1):
                try:
                    ok = 生成一个Beat(i, n, 后端)
                except Exception as e:
                    print(f"✗ 单首异常（不影响后续）: {e}")
                    ok = False
                if ok:
                    成功 += 1
            print(f"\n===== 批次结束：成功 {成功}/{n} =====")
        elif c == "2":
            检查配置()
        elif c == "0":
            print("再见 🎧")
            break
        else:
            print("无效选择")


if __name__ == "__main__":
    主()
