"""智能分块:按时间戳自然段合并 + 超长段递归切分(保留时间戳元数据)"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

MAX_CHARS = 500   # 目标块大小
OVERLAP = 80      # 重叠字符


def chunk_segments(segments: list[dict]) -> list[dict]:
    """把 ASR 段落切成知识块,每块带 start/end 时间戳元数据"""
    chunks = []
    cur_text, cur_start, cur_end = "", None, None

    def flush():
        nonlocal cur_text, cur_start, cur_end
        if not cur_text.strip():
            return
        # 超长段用递归切分器二次切(按标点/换行,带重叠,避免语义断裂)
        if len(cur_text) > MAX_CHARS:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=MAX_CHARS, chunk_overlap=OVERLAP,
                separators=["\n", "。", "！", "？", "；", "，", " ", ""],
            )
            pieces = splitter.split_text(cur_text)
            n = len(pieces)
            for i, piece in enumerate(pieces):
                chunks.append({
                    "text": piece.strip(),
                    "start": round(cur_start + (cur_end - cur_start) * i / max(n, 1), 2),
                    "end": round(cur_start + (cur_end - cur_start) * (i + 1) / max(n, 1), 2),
                })
        else:
            chunks.append({"text": cur_text.strip(), "start": cur_start, "end": cur_end})
        cur_text, cur_start, cur_end = "", None, None

    for seg in segments:
        text = seg["text"]
        if not text:
            continue
        if cur_start is None:
            cur_start = seg["start"]
        # 语义边界:按 ASR 的句子分隔(遇句号/问号等结束符则切)
        cur_end = seg["end"]
        cur_text += text + ("\n" if text.endswith(("。", "！", "？", "!", "?")) else "")
        if len(cur_text) >= MAX_CHARS or text.endswith(("。", "！", "？", "!", "?")):
            flush()

    flush()
    return chunks


if __name__ == "__main__":
    demo = [
        {"start": 0.0, "end": 3.0, "text": "今天我们讨论项目的技术方案。"},
        {"start": 3.0, "end": 6.0, "text": "首先确定使用 RAG 技术。"},
        {"start": 6.0, "end": 10.0, "text": "然后是向量数据库的选型,我们倾向轻量方案。"},
    ]
    for c in chunk_segments(demo):
        print(c)
