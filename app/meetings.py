"""会议注册表 + 转写稿落盘(仿 meeting-ai-master 的 embedder/transcripts 管理)

每场入库的会议(音频/录屏视频/模拟文本)在 data/meetings.json 里登记一条记录,
原始转写稿存到 data/transcripts/{meeting_id}.txt,向量知识块则由 store 管理
(每条知识块元数据带 meeting_id,可整场删除/重组清洗稿)。

说明:
- meeting_id 规则同 meeting-ai-master: 原文件名(消毒) + 时间戳,天然唯一、可进 URL。
- 旧库里的历史数据没有 meeting_id,不出现在会议列表,但问答仍可检索到。
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import config
from .store import get_store


# ---------- 注册表持久化 ----------

def _registry_path() -> Path:
    return config.DATA_DIR / "meetings.json"


def _read_registry() -> list[dict]:
    p = _registry_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_registry(items: list[dict]):
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------- id / 时间戳工具 ----------

_ID_BAD = re.compile(r"[^\w.\-\u4e00-\u9fff]+")


def sanitize_id(name: str, limit: int = 40) -> str:
    """把文件名/标题消毒成可进 URL、可做文件名的 id 片段"""
    s = _ID_BAD.sub("_", str(name or "").strip()).strip("_")
    return (s or "meeting")[:limit]


def new_id(stem: str) -> str:
    """生成唯一会议 id: 消毒文件名 + 时间戳(同 meeting-ai-master 风格)"""
    return f"{sanitize_id(stem)}_{int(time.time())}"


def fmt_ts(seconds: float) -> str:
    """秒 → mm:ss(小时并进分钟,同 meeting-ai-master 原稿格式)"""
    sec = max(0, int(seconds))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


def segments_to_text(segments: list[dict]) -> str:
    """带时间戳段落 → 可读原文稿,如: [00:03 - 00:08] 今天开会讨论方案"""
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{fmt_ts(seg.get('start', 0))} - {fmt_ts(seg.get('end', 0))}] {text}")
    return "\n".join(lines)


# ---------- 原始转写稿文件 ----------

def _raw_path(meeting_id: str) -> Path:
    return config.TRANSCRIPT_DIR / f"{sanitize_id(meeting_id)}.txt"


def save_raw_transcript(meeting_id: str, text: str):
    p = _raw_path(meeting_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text or "", encoding="utf-8")


def raw_text(meeting_id: str) -> str | None:
    p = _raw_path(meeting_id)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


# ---------- 注册 / 列表 / 删除 ----------

def register_meeting(*, meeting_id: str, title: str, date: str, file_name: str,
                     md5: str = "", raw_text_: str = "", chunk_count: int = 0,
                     chars: int = 0, duration: float | None = None,
                     kind: str = "audio", owner: int | None = None) -> dict:
    """入库成功后登记一场会议(写注册表 + 落盘原始稿);owner 为上传者用户 id"""
    save_raw_transcript(meeting_id, raw_text_)
    rec = {
        "id": meeting_id,
        "title": title or "会议",
        "date": date or "",
        "file": file_name or "",
        "md5": md5 or "",
        "kind": kind,               # audio(录音) / video(录屏) / txt(模拟文本)
        "chunks": chunk_count,
        "chars": chars,
        "duration": duration,
        "owner": owner,             # 拥有者用户 id(None=历史数据)
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    items = [r for r in _read_registry() if r.get("id") != meeting_id]
    items.append(rec)
    _write_registry(items)
    return rec


def list_meetings(owner: int | None = None) -> list[dict]:
    """会议列表(按入库时间倒序);owner 为空=全部(管理员),否则只列该用户的会议"""
    docs = get_store().all()
    by_id: dict[str, list[dict]] = {}
    for d in docs:
        mid = d.get("meeting_id")
        if mid:
            by_id.setdefault(mid, []).append(d)

    out = []
    for r in _read_registry():
        if owner is not None and r.get("owner") != owner:
            continue
        ds = by_id.get(r.get("id"), [])
        item = dict(r)
        item["chunks"] = len(ds)
        item["chars"] = sum(len(d.get("text") or "") for d in ds) or item.get("chars", 0)
        item["has_raw"] = _raw_path(r.get("id", "")).exists()
        item["has_source"] = bool(r.get("source_path")) and source_file(r.get("id", "")) is not None
        out.append(item)
    out.sort(key=lambda x: x.get("created") or "", reverse=True)
    return out


def meeting_ids_of_owner(owner: int) -> list[str]:
    """某用户拥有(或可检索)的全部会议 id,供问答/检索限定范围"""
    return [r["id"] for r in _read_registry() if r.get("owner") == owner]


def set_owner(meeting_id: str, owner: int):
    """给会议补记归属者(上传入库时登记先于知道请求用户,故由 server 调用)"""
    update_meeting(meeting_id, owner=owner)


def update_meeting(meeting_id: str, **fields) -> dict | None:
    """更新会议记录的可选字段(owner / source_path / source_name / source_size …)"""
    items = _read_registry()
    found = None
    for it in items:
        if it.get("id") == meeting_id:
            it.update({k: v for k, v in fields.items() if v is not None})
            found = it
    if found is not None:
        _write_registry(items)
    return found


def source_file(meeting_id: str) -> Path | None:
    """会议对应的原始录音/录屏文件(供导出);不存在或越界返回 None"""
    rec = get_meeting(meeting_id) or {}
    rel = rec.get("source_path")
    if not rel:
        return None
    try:
        p = (config.BASE_DIR / rel).resolve()
        p.relative_to(config.DATA_DIR.resolve())   # 安全:只允许导出 data/ 下的文件
    except (ValueError, OSError):
        return None
    return p if p.exists() else None


def all_docs() -> list[dict]:
    """向量库全部知识块(管理员统计/全库问答用)"""
    return get_store().all()


def get_meeting(meeting_id: str) -> dict | None:
    for r in _read_registry():
        if r.get("id") == meeting_id:
            return r
    return None


def find_by_md5(md5: str, owner: int | None = None) -> dict | None:
    """按文件 MD5 查会议;owner 非空时只在该用户范围内查(按用户去重)"""
    if not md5:
        return None
    for r in _read_registry():
        if r.get("md5") != md5:
            continue
        if owner is not None and r.get("owner") != owner:
            continue
        return r
    return None


def cleaned_text(meeting_id: str) -> str:
    """知识库里的内容(清洗稿):该会议全部知识块按时间顺序拼接"""
    docs = [d for d in get_store().all() if d.get("meeting_id") == meeting_id]
    if not docs:
        return ""
    docs.sort(key=lambda d: (d.get("start") or 0, d.get("end") or 0))
    return "\n".join((d.get("text") or "").strip() for d in docs if (d.get("text") or "").strip())


def delete_meeting(meeting_id: str) -> bool:
    """删除会议:向量库知识块 + 注册表条目 + 原始稿文件(同 meeting-ai-master)"""
    removed_docs = get_store().remove(lambda d: d.get("meeting_id") == meeting_id)
    items = [r for r in _read_registry() if r.get("id") != meeting_id]
    existed = len(items) != len(_read_registry())
    if existed:
        _write_registry(items)
    raw_p = _raw_path(meeting_id)
    if raw_p.exists():
        raw_p.unlink()
    return removed_docs > 0 or existed
