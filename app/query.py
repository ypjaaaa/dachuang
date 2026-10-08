"""RAG 问答:混合检索(BM25+向量+rerank) → Prompt 组装 → 本地 LLM 生成(带来源引用)"""
from . import config
from .llm import generate, rewrite_query
from .retriever import HybridRetriever

SYSTEM_PROMPT = """你是会议知识助手,基于提供的会议摘录回答用户问题。
规则:
1. 先回答摘录中能找到的内容(直接、具体地作答);
2. 如果问题里的某些细节(时间、场景、人名等)摘录里没有,在回答末尾用一句话补充:"(注:会议中未提及[该细节])";
3. 只有摘录与问题完全无关时,才回答"会议内容中未找到相关信息"。
不要编造摘录中没有的事实。引用内容时标注 [开始时间-结束时间]。
"""

_retriever = None


def retrieve(query: str, top_k: int = config.TOP_K,
             meeting_ids: list[str] | None = None) -> list[dict]:
    """混合检索 + rerank,返回 [{text, start, end, source, title, score}]

    meeting_ids=None → 全部会议;传会议 id 列表 → 只在该范围内检索(用户隔离)
    """
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    hits = _retriever.search(query, top_k, meeting_ids=meeting_ids)
    filtered = [h for h in hits if h["score"] >= config.MIN_SCORE]
    if filtered:
        return filtered
    # 保底:泛问题(如"会议总结")匹配分天然低,过滤后为空时
    # 返回最相关的段落,让 LLM 判断是否相关,而不是直接"未找到"
    return hits[:top_k]


def build_prompt(query: str, hits: list[dict]) -> tuple[str, str]:
    """返回 (system, user) 两条消息,供 chat 接口使用"""
    system = SYSTEM_PROMPT
    parts = ["以下是会议摘录,请据此回答:\n"]
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[{i}] ({h['start']}-{h['end']}秒, 来自 {h['title']})\n{h['text']}"
        )
    parts.append(f"\n问题: {query}")
    return system, "\n".join(parts)


def answer(query: str, history: list[dict] | None = None, top_k: int = config.TOP_K,
           meeting_ids: list[str] | None = None) -> dict:
    """完整问答,返回 {answer, citations, search_query}

    history: 多轮对话历史 [{"role": "user"/"assistant", "content": ...}, ...]
    meeting_ids: 限定检索范围(None=全部;业务系统里传当前用户拥有的会议 id)
    """
    # 多轮对话:有历史时先重写检索词(追问自动补全上下文)
    search_query = query
    if history:
        search_query = rewrite_query(history, query)
        print(f"[多轮] 原问题: {query}\n[多轮] 重写后: {search_query}")

    hits = retrieve(search_query, top_k, meeting_ids=meeting_ids)
    if not hits:
        # 区分"库为空/无权范围"与"没检索到相关内容",避免误导
        r = HybridRetriever()
        r.load_corpus(meeting_ids)
        if not r._corpus:
            return {"answer": "知识库为空:请先在「① 导入会议」导入你自己的会议录音/录屏。", "citations": []}
        return {
            "answer": f"未在会议内容中找到与「{query}」相关的信息。\n"
                      "建议换个问法,或确认该内容确实在已导入的会议中。",
            "citations": [],
        }
    system, user = build_prompt(search_query, hits)
    ans = generate(system, user)
    citations = [
        {"title": h["title"], "start": h["start"], "end": h["end"],
         "source": h["source"], "score": h["score"]}
        for h in hits
    ]
    return {"answer": ans, "citations": citations, "search_query": search_query}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "今天会议讨论了什么技术方案?"
    r = answer(q)
    print("== 回答 ==")
    print(r["answer"])
    print("\n== 引用来源 ==")
    for c in r["citations"]:
        print(f"  [{c['start']}-{c['end']}秒] {c['title']} (score={c['score']})")
