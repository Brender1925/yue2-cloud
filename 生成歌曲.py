# -*- coding: utf-8 -*-
"""生成 Beat 底轨 + ABC 谱（云端 RunningHub / 本地 ComfyUI 二选一）。

云端：纯标准库（urllib/json），不依赖 numpy 等。
读 配置/云端配置.json 的 api_key 与 workflow_id（账户私有凭据）、
配置/示例配置.json 的风格节点映射，提交工作流任务
（请求体只上传 style，其余节点一律不动），轮询到完成，下载音频与乐谱。

本地：读 配置/本地配置.json 的 ComfyUI 地址与工作流 JSON，
同样只把 style 写入风格节点，其余保持导出原样，POST /prompt 后轮询 /history 拉回产物。

用法：
  python 生成歌曲.py [--后端 cloud|local] [--output 生成测试] [--style "..."]
  后端默认读 配置/本地配置.json 的 后端 字段。
  不传 --style 时，用 工作流/文生音乐带谱_api.json 里 27 号节点的默认提示词。
"""
import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import unquote
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
HOST = "www.runninghub.cn"
CREATE = "/task/openapi/create"
QUERY = "/task/openapi/outputs"
风格节点ID = "27"


def 读json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def post(path, payload, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://{HOST}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def 默认style():
    """读工作流快照里风格节点的默认提示词。"""
    wf = 读json(PROJECT / "工作流/文生音乐带谱_api.json")
    return wf[风格节点ID]["inputs"]["value"]


def 提交(api_key, wf_id, node_map, style, timeout=120):
    """请求体只上传拼装好的 style；其余节点、参数一律不动，
    全部由工作流里的默认值负责——任何额外修改（哪怕是空值）都会影响生成结果。"""
    nodeInfoList = [{"nodeId": node_map["风格"]["nodeId"],
                     "fieldName": node_map["风格"]["fieldName"],
                     "fieldValue": style}]
    body = {"apiKey": api_key, "workflowId": wf_id, "nodeInfoList": nodeInfoList}
    print(f"[提交] style={style!r}")
    return post(CREATE, body, timeout=timeout)


def 查询(api_key, task_id, timeout=120):
    return post(QUERY, {"apiKey": api_key, "taskId": task_id}, timeout=timeout)


def 取状态(q):
    found = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower() in ("status", "taskstatus", "state", "task_status"):
                    if v is not None:
                        found.append(str(v))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(q)
    return found


def 收集文件(q):
    cands = []

    def walk(o):
        if isinstance(o, dict):
            u = o.get("url") or o.get("fileUrl")
            if u:
                cands.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(q)
    return cands


def 下载(url, dest):
    # 文件在 CDN（volces.com 等）上，绝不能带 runninghub 的 Host 头
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


def 本地生成(base_url, workflow_path, style, out_dir, node_map,
             轮询间隔=3, 超时秒=2400):
    """本地 ComfyUI 生成：只把 style 写入风格节点，其余保持导出原样。

    POST /prompt 提交 → 轮询 /history/<prompt_id> → /view 拉回音频与乐谱。
    """
    import uuid
    base = base_url.rstrip("/")
    graph = 读json(workflow_path)
    # 只改风格节点的值，其余节点、参数全部不动
    风格节点 = node_map["风格"]
    graph[风格节点["nodeId"]]["inputs"][风格节点["fieldName"]] = style
    print(f"[本地提交] style={style!r}")

    client_id = uuid.uuid4().hex
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": graph, "client_id": client_id}).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode("utf-8"))
    prompt_id = resp.get("prompt_id")
    if not prompt_id:
        print(f"[本地提交失败] {json.dumps(resp, ensure_ascii=False)}")
        sys.exit(1)
    print(f"[prompt_id] {prompt_id}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 超时秒
    files = None
    while time.time() < deadline:
        time.sleep(轮询间隔)
        try:
            with urllib.request.urlopen(f"{base}/history/{prompt_id}", timeout=30) as r:
                hist = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"[轮询] {e}", flush=True)
            continue
        entry = hist.get(prompt_id)
        if not entry:
            continue
        status = (entry.get("status") or {}).get("status_str", "")
        if status == "error":
            print("[失败] 本地 ComfyUI 执行出错")
            sys.exit(2)
        outputs = entry.get("outputs") or {}
        files = []
        for node_out in outputs.values():
            for items in node_out.values():
                if isinstance(items, list):
                    files += [it for it in items
                              if isinstance(it, dict) and it.get("filename")]
        if files:
            break
        print("[轮询] 运行中...", flush=True)
    if not files:
        print("[超时] 本地生成未在限定时间内完成"); sys.exit(3)

    音频数 = 谱数 = 0
    for it in files:
        params = urllib.parse.urlencode({
            "filename": it["filename"], "subfolder": it.get("subfolder", ""),
            "type": it.get("type", "output")})
        name = Path(it["filename"]).name
        dest = out / name
        try:
            下载(f"{base}/view?{params}", dest)
        except Exception as e:
            print(f"[下载失败] {it['filename']}: {e}")
            continue
        ext = dest.suffix.lower()
        if ext == ".txt":
            谱数 += 1
            print(f"[乐谱] {dest}")
        elif ext in (".mp3", ".wav", ".flac"):
            音频数 += 1
            print(f"[音频] {dest}")
        else:
            print(f"[其他] {dest}")
    print(f"[完成] 音频={音频数} 乐谱={谱数} -> {out}")


def 主(argv=None):
    ap = argparse.ArgumentParser(description="生成 Beat 底轨 + ABC 谱（云端/本地）")
    ap.add_argument("--后端", choices=("cloud", "local"), default=None,
                    help="cloud=RunningHub 云端，local=本地 ComfyUI；默认读 配置/本地配置.json 的 后端")
    ap.add_argument("--output", default="生成测试")
    ap.add_argument("--style", default=None)
    ap.add_argument("--超时秒", type=int, default=None,
                    help="轮询总超时，默认取配置（云端 2400 / 本地 2400）")
    args = ap.parse_args(argv)

    ex = 读json(PROJECT / "配置/示例配置.json")
    node_map, 接口 = ex["节点"], ex.get("接口", {})
    请求超时 = int(接口.get("请求超时秒", 120))
    轮询间隔 = int(接口.get("轮询间隔秒", 10))

    if args.style:
        style = args.style
    else:
        style = 默认style()
        print(f"[默认提示词] 取自工作流快照 27 号节点：{style[:60]}...")

    本地 = 读json(PROJECT / "配置/本地配置.json")
    后端 = args.后端 or 本地.get("后端", "cloud")

    if 后端 == "local":
        lc = 本地.get("本地ComfyUI", {})
        本地生成(lc.get("base_url", "http://127.0.0.1:8188"),
                PROJECT / lc.get("workflow_json", "工作流/文生音乐带谱_api.json"),
                style, args.output, node_map,
                轮询间隔=int(lc.get("轮询间隔秒", 3)),
                超时秒=args.超时秒 or int(lc.get("单任务超时秒", 2400)))
        return

    # ---- 云端 RunningHub ----
    cfg = 读json(PROJECT / "配置/云端配置.json")
    接口 = cfg.get("接口", {})
    api_key = 接口.get("api_key", "")
    wf_id = 接口.get("workflow_id", "")
    if not api_key:
        print("[错误] 未填写 api_key：请在 配置/云端配置.json 的 接口.api_key 填入"
              "你自己的 RunningHub API key。")
        sys.exit(1)
    if not wf_id:
        print("[错误] 未提供 workflow_id：请在 配置/云端配置.json 填入 接口.workflow_id。"
              "工作流需上传到自己的 RunningHub 账户并手动成功运行一次。")
        sys.exit(1)

    r = 提交(api_key, wf_id, node_map, style, timeout=请求超时)
    print("[提交返回]", json.dumps(r, ensure_ascii=False))
    if r.get("code") not in (0, None) or not r.get("data"):
        code = r.get("code")
        if code == 380 or "not exists" in str(r.get("msg", "")).lower():
            print("[提交失败] code 380: 该 workflow 在 API 下不存在。")
            print("  原因 (RunningHub 官方要求): 目标工作流必须在网页端【手动成功运行过至少一次】才会对 API 激活。")
            print("  解决: 登录与 API key 同一账户的 RunningHub → 打开此工作流 → 在网页里跑一次且成功 → 再重跑本脚本。")
            print("  若已跑过仍报此错，多半是【工作流与 API key 不在同一账户】，请核对。")
        else:
            print(f"[提交失败] {r.get('msg')} (code={code})")
        sys.exit(1)
    data = r["data"]
    task_id = data.get("taskId") or r.get("taskId")
    if not task_id:
        print("[错误] 未拿到 taskId，提交可能失败"); sys.exit(1)
    print(f"[taskId] {task_id}")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + (args.超时秒 or int(接口.get("单任务超时秒", 2400)))
    done = False
    连续错误 = 0
    while time.time() < deadline:
        time.sleep(轮询间隔)
        try:
            q = 查询(api_key, task_id, timeout=请求超时)
        except Exception as e:
            连续错误 += 1
            print(f"[轮询网络错误 {连续错误}/5] {e}", flush=True)
            if 连续错误 >= 5:
                print("[失败] 连续 5 次查询失败，放弃"); sys.exit(4)
            continue
        连续错误 = 0
        sts = 取状态(q)
        print(f"[轮询] status={sts} raw={json.dumps(q, ensure_ascii=False)[:1200]}", flush=True)
        if any(s.upper().startswith("FAIL") for s in sts):
            print("[失败] 任务失败，停止"); sys.exit(2)
        # v1 /task/openapi/outputs 顶层无 status，靠 code==0 且 data 非空判定完成
        data = q.get("data")
        if q.get("code") in (0, None) and isinstance(data, list) and data:
            done = True
            break

    if not done:
        print("[超时] 未在限定时间内完成"); sys.exit(3)

    files = 收集文件(q)
    print(f"[结果] 共 {len(files)} 个产出文件")
    音频数 = 谱数 = 0
    for f in files:
        url = f.get("url") or f.get("fileUrl")
        if not url:
            continue
        name = unquote(url.rstrip("/").split("/")[-1])
        ext = Path(name).suffix.lower()
        dest = out / name
        try:
            下载(url, dest)
        except Exception as e:
            print(f"[下载失败] {url}: {e}")
            continue
        if ext == ".txt":
            谱数 += 1
            print(f"[乐谱] {dest}")
        elif ext in (".mp3", ".wav", ".flac"):
            音频数 += 1
            print(f"[音频] {dest}")
        else:
            print(f"[其他] {dest}")
    print(f"[完成] 音频={音频数} 乐谱={谱数} -> {out}")


if __name__ == "__main__":
    主()
