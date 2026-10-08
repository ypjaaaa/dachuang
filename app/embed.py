"""向量嵌入:bge-large-zh-v1.5,sentence-transformers 本地推理"""
from sentence_transformers import SentenceTransformer

from . import config


_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(
            config.EMBED_MODEL,
            cache_folder=str(config.MODELS_DIR),
            device=config.EMBED_DEVICE,  # CPU:把显存留给 LLM
        )
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量嵌入,返回归一化向量列表"""
    vecs = get_model().encode(
        texts, batch_size=config.EMBED_BATCH,
        normalize_embeddings=True, convert_to_numpy=True,
    )
    return vecs.tolist()
