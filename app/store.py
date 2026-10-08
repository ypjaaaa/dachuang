"""轻量向量存储:FAISS(内存内积索引)+ pickle 持久化

替代 Milvus Lite —— 规避其 grpc keepalive/并发锁不稳定的问题。
数据量小(几百条知识块),FAISS 更快更稳,零连接管理。

v2:额外持久化每条记录对应的向量,支持「删除某场会议」后重建索引。
"""
import pickle
from pathlib import Path

import faiss
import numpy as np

from . import config


class VectorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.dim = config.VECTOR_DIM
        self.index = faiss.IndexFlatIP(self.dim)   # 内积;向量已归一化 → 等价余弦
        self.docs: list[dict] = []                  # 与 index 位置一一对应的元数据
        self.vectors: list | None = []              # 与 index 位置一一对应的向量(None=旧格式待重建)
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        idx_file = self.path / "index.pkl"
        if not idx_file.exists():
            return
        try:
            with open(idx_file, "rb") as f:
                obj = pickle.load(f)
            if isinstance(obj, tuple) and len(obj) == 3:
                self.index, self.docs, self.vectors = obj
            elif isinstance(obj, tuple) and len(obj) == 2:
                # 旧格式 (index, docs):向量未保存 → 置 None,首次增删时用嵌入模型重建
                self.index, self.docs = obj
                self.vectors = None
            else:
                self.docs, self.vectors = [], []
        except Exception:
            # 文件损坏时从空库开始,避免服务起不来
            self.docs, self.vectors = [], []

    def _save(self):
        if self.vectors is None:
            return  # 旧格式未重建前不落盘,避免把向量清空
        with open(self.path / "index.pkl", "wb") as f:
            pickle.dump((self.index, self.docs, self.vectors), f)

    def _ensure_vectors(self):
        """旧数据无向量时,用嵌入模型为全部 doc 补算一次(仅升级时触发一次)"""
        if self.vectors is not None:
            return
        if not self.docs:
            self.vectors = []
            return
        from .embed import embed_texts
        self.vectors = [np.asarray(v, dtype="float32") for v in embed_texts([d["text"] for d in self.docs])]
        self._save()

    # ---------- 操作 ----------
    def add(self, vectors, metadatas: list[dict]) -> int:
        if not vectors:
            return 0
        self._ensure_vectors()
        self.index.add(np.asarray(vectors, dtype="float32"))
        self.docs.extend(metadatas)
        self.vectors.extend(np.asarray(v, dtype="float32") for v in vectors)
        self._save()
        return len(metadatas)

    def remove(self, predicate) -> int:
        """删除所有满足 predicate(doc) 的记录,返回删除条数"""
        self._ensure_vectors()
        keep = [(d, v) for d, v in zip(self.docs, self.vectors) if not predicate(d)]
        removed = len(self.docs) - len(keep)
        if removed:
            self.docs = [d for d, _ in keep]
            self.vectors = [v for _, v in keep]
            self.index = faiss.IndexFlatIP(self.dim)
            if self.vectors:
                self.index.add(np.asarray(self.vectors, dtype="float32"))
            self._save()
        return removed

    def search(self, query_vec, top_k: int) -> list[dict]:
        if not self.docs:
            return []
        scores, idxs = self.index.search(
            np.asarray([query_vec], dtype="float32"), min(top_k, len(self.docs)))
        out = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0 or idx >= len(self.docs):
                continue
            d = dict(self.docs[idx])
            d["score"] = round(float(score), 4)
            out.append(d)
        return out

    def all(self) -> list[dict]:
        return list(self.docs)

    def clear(self):
        self.index = faiss.IndexFlatIP(self.dim)
        self.docs = []
        self.vectors = []
        self._save()


_store: VectorStore | None = None


def get_store() -> VectorStore:
    """全局单例向量库"""
    global _store
    if _store is None:
        _store = VectorStore(config.MILVUS_DIR / "faiss_kb")  # 复用 data/milvus_lite 目录改名
    return _store
