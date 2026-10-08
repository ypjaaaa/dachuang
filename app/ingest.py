"""入库管道:音频/录屏视频 → 转写 → 分块 → 嵌入 → FAISS 向量库(或模拟会议文本)

新流程(带会议注册):
  1. ASR/解析得到带时间戳段落
  2. 分块 + 嵌入 + 入库(每条知识块带 meeting_id)
  3. 入库成功后调用 meetings.register_meeting 落盘「原始转写稿」并登记会议
     → Web 端即可查看原文、生成文档、删除该会议

兼容说明: 返回值由 int 改为 dict {chunks, title, segments, meeting_id, ...},
旧调用方(ui.py / server.py / CLI)已同步更新。
"""
import re
import uuid
from pathlib import Path

from . import config, meetings
from .asr import transcribe
from .chunk import chunk_segments
from .embed import embed_texts
from .store import get_store


# ---------- 模拟会议文本解析函数 ----------
def parse_mock_meeting(file_path: str) -> list:
    """
    解析 .txt 模拟会议文件，直接生成带时间戳的 chunks
    字段名与音频流程保持一致：start / end
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取标题和日期
    title_match = re.search(r'会议标题[：:]\s*(.+)', content)
    date_match = re.search(r'会议日期[：:]\s*(.+)', content)
    title = title_match.group(1).strip() if title_match else "未命名会议"
    date = date_match.group(1).strip() if date_match else ""

    # 提取所有带时间戳的行 [HH:MM:SS]
    pattern = r'\[(\d{2}:\d{2}:\d{2})\]\s*(.+)'
    matches = re.findall(pattern, content)

    chunks = []
    for time_str, text in matches:
        h, m, s = map(int, time_str.split(':'))
        start_seconds = h * 3600 + m * 60 + s

        chunks.append({
            "id": str(uuid.uuid4()),
            "text": text.strip(),
            "start": start_seconds,       # 与音频流程字段名一致
            "end": start_seconds + 5,     # 模拟每段持续5秒
            "meeting_title": title,
            "meeting_date": date
        })
    return chunks, content


# ---------- 主入库函数 ----------
def ingest(audio_path: str, title: str = "", date: str = "",
           *, meeting_id: str = "", file_name: str = "", md5: str = "") -> dict:
    """处理单个音频/录屏视频/文本文件入库，返回 {chunks, title, segments, meeting_id}

    meeting_id 非空时走「会议模式」: 落盘原始转写稿 + 登记注册表(供原文/文档/删除使用)
    """
    segments = []      # ASR 段落(音频/视频流程才有)
    raw_text = ""      # 原始转写稿文本
    kind = "audio"

    # ---------- 根据文件类型分流 ----------
    if str(audio_path).endswith('.txt'):
        # 🟢 模拟会议文本：直接解析，跳过 Whisper
        kind = "txt"
        print(f"[1/3] 解析模拟会议: {audio_path} ...")
        chunks, raw_text = parse_mock_meeting(audio_path)
        print(f"      解析完成，{len(chunks)} 个段落")
        # 如果没传 title/date，从解析结果里补
        if not title and chunks:
            title = chunks[0].get("meeting_title", "未命名会议")
        if not date and chunks:
            date = chunks[0].get("meeting_date", "")
    else:
        # 🔵 音频/录屏视频文件：走 Whisper 转写 + 分块
        kind = "video" if (audio_path or "").lower().endswith(
            (".mov", ".mp4", ".mkv", ".avi", ".m4v", ".webm", ".flv", ".ts", ".wmv", ".3gp")) else "audio"
        print(f"[1/4] 转写: {audio_path} ...")
        segments = transcribe(audio_path)
        print(f"      转写完成，{len(segments)} 个段落")
        raw_text = meetings.segments_to_text(segments)

        print("[2/4] 分块 ...")
        chunks = chunk_segments(segments)
        print(f"      共 {len(chunks)} 个知识块")

    # ---------- 嵌入 + 入库（两种模式共用） ----------
    print("[3/4] 嵌入 ...")
    texts = [c["text"] for c in chunks]
    vecs = embed_texts(texts)

    print("[4/4] 入库 FAISS ...")
    rows = []
    for c, v in zip(chunks, vecs):
        rows.append({
            "text": c["text"],
            "start": c.get("start", 0),
            "end": c.get("end", c.get("start", 0) + 5),
            "source": str(audio_path),
            "title": title or c.get("meeting_title", "会议"),
            "date": date or c.get("meeting_date", ""),
            "meeting_id": meeting_id or None,   # 会议模式:整场可追溯/可删除
        })
    n = get_store().add(vecs, rows)
    print(f"      入库完成，共 {n} 条")

    # ---------- 会议模式:落盘原文 + 登记(入库成功后才登记,失败不产生孤儿记录) ----------
    if meeting_id:
        chars = sum(len(c["text"]) for c in chunks)
        duration = round(max((s.get("end", 0) for s in segments), default=0), 1) or None
        meetings.register_meeting(
            meeting_id=meeting_id,
            title=title or "会议",
            date=date or "",
            file_name=file_name or Path(audio_path).name,
            md5=md5 or "",
            raw_text_=raw_text,
            chunk_count=n,
            chars=chars,
            duration=duration,
            kind=kind,
        )
        print(f"      ✅ 已登记会议 {meeting_id}(原文 {len(raw_text)} 字)")

    return {
        "chunks": n,
        "title": title or "会议",
        "date": date or "",
        "segments": segments,
        "meeting_id": meeting_id or None,
    }


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m app.ingest <音频/录屏文件> [标题] [日期]")
        print("  或: python -m app.ingest <会议.txt> [标题] [日期]")
        sys.exit(1)
    title = sys.argv[2] if len(sys.argv) > 2 else ""
    date = sys.argv[3] if len(sys.argv) > 3 else ""
    result = ingest(sys.argv[1], title, date)
    print(f"入库完成:{result['chunks']} 个知识块;标题:{result['title']}")
