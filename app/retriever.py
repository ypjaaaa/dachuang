"""混合检索:BM25 关键词 + 向量语义 → RRF 融合 → bge-reranker 精排

提升专有名词/人名/缩写类问题的召回(关键词),再用 reranker 精排提高准确率。
数据量小(会议转写几百条),BM25 索引进程内构建一次即可。
"""
from collections import defaultdict

import jieba
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from . import config
from .embed import embed_texts
from .store import get_store

# 中文停用词(精简)
_STOP = set("的了是在有和就都而及与或这那之,。！？；：、\"'‘’“”（）【】[]《》 ")


def tokenize(text: str) -> list[str]:
    return [w for w in jieba.cut(text) if w.strip() and w not in _STOP]


class HybridRetriever:
    """混合检索器:向量 + BM25,RRF 融合后 rerank 精排"""

    def __init__(self):
        self._bm25: BM25Okapi | None = None
        self._corpus: list[dict] = []
        self._reranker = None

    # ---------- 语料与索引 ----------
    def load_corpus(self, meeting_ids: list[str] | None = None):
        """从向量库拉文本构建 BM25 索引

        meeting_ids=None → 全部会议(管理员/历史数据);
        传入会议 id 列表 → 只在该用户的会议内检索(业务系统按用户隔离)。
        每次问答都重载,保证新导入的会议立即可检索。
        """
        docs = get_store().all()
        if meeting_ids is not None:
            allowed = set(meeting_ids)
            docs = [d for d in docs if d.get("meeting_id") in allowed]
        self._corpus = docs
        self._bm25 = (BM25Okapi([tokenize(r["text"]) for r in docs]) if docs else None)

    # ---------- 阶段1:向量 + BM25 双路召回 ----------
    def _vec_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """向量检索,返回 [(corpus_index, score)]"""
        qv = embed_texts([query])[0]
        hits = get_store().search(qv, top_k)
        # 用 (source, start) 映射回 corpus 下标
        key2idx = {(r["source"], r["start"]): i for i, r in enumerate(self._corpus)}
        result = []
        for h in hits:
            idx = key2idx.get((h["source"], h["start"]))
            if idx is not None:
                result.append((idx, h["score"]))
        return result

    def _bm25_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [(i, scores[i]) for i in ranked[:top_k] if scores[i] > 0]

    def _rrf_fuse(self, *ranked_lists: list[tuple[int, float]], k: int = 60) -> list[int]:
        """Reciprocal Rank Fusion:按排名融合多路结果,返回排序后的 corpus 下标"""
        fused: dict[int, float] = defaultdict(float)
        for ranked in ranked_lists:
            for rank, (idx, _) in enumerate(ranked):
                fused[idx] += 1.0 / (k + rank + 1)
        return [i for i, _ in sorted(fused.items(), key=lambda x: x[1], reverse=True)]

    # ---------- 阶段2:rerank 精排 ----------
    def _get_reranker(self) -> CrossEncoder:
        if self._reranker is None:
            self._reranker = CrossEncoder(str(config.RERANK_MODEL), device=config.RERANK_DEVICE)  # CPU:显存留给 LLM
        return self._reranker

    def _rerank(self, query: str, candidates: list[int], top_k: int) -> list[dict]:
        """对候选做交叉编码精排,返回带分数的 top_k 文档"""
        docs = [self._corpus[i] for i in candidates]
        scores = self._get_reranker().predict(
            [[query, d["text"]] for d in docs],
            apply_sigmoid=True, batch_size=8, show_progress_bar=False,
        )
        ordered = sorted(zip(candidates, docs, scores), key=lambda x: x[2], reverse=True)
        return [
            {
                "text": d["text"], "start": d["start"], "end": d["end"],
                "source": d["source"], "title": d["title"],
                "score": round(float(s), 4),
            }
            for _, d, s in ordered[:top_k]
        ]

    # ---------- 主入口 ----------
    def search(self, query: str, top_k: int = config.TOP_K,
               meeting_ids: list[str] | None = None) -> list[dict]:
        """混合检索 + rerank,返回最终结果列表;meeting_ids 用于限定会议范围"""
        self.load_corpus(meeting_ids)
        if not self._corpus:
            return []
        vec = self._vec_search(query, config.VEC_TOP_K)
        bm = self._bm25_search(query, config.BM25_TOP_K)
        fused = self._rrf_fuse(vec, bm)
        if config.RERANK_TOP > 0 and fused:
            return self._rerank(query, fused[:config.RERANK_TOP], top_k)
        # 无 rerank 时:按融合分返回
        return [
            {"text": self._corpus[i]["text"], "start": self._corpus[i]["start"],
             "end": self._corpus[i]["end"], "source": self._corpus[i]["source"],
             "title": self._corpus[i]["title"], "score": 0.0}
            for i in fused[:top_k]
        ]
