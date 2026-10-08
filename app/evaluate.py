"""检索评测:用标注测试集量化"问答检索准确率"(PPT 验收指标 ≥80%)

用法: python -m app.evaluate
测试集格式: (问题, 期望命中的 [来源标题, 起始秒], 备注)
hit@k:期望段落出现在 top-k 检索结果中即算命中。
"""
from .query import retrieve

# 基于现有知识库(会议.m4a / 达摩院示例 / 歌曲)的标注测试集
TEST_SET = [
    ("组会里HBase查询变慢的原因是什么?", [["组会录音测试", 46.28]], "原因段落"),
    ("查询性能问题的修复方案是什么?", [["组会录音测试", 77.98]], "修复方案段落"),
    ("CPU达不到90%是怎么回事?", [["组会录音测试", 33.28]], "问题描述段落"),
    ("前端过滤条件没有被强制执行,导致了什么问题?", [["组会录音测试", 46.28]], "根因段落"),
    ("达摩院推出的语音识别模型是做什么的?", [["达摩院语音识别体验", 0.56]], "达摩院段落"),
    ("这首歌的歌词描述了什么场景?", [["夏天的风(Live)", 28.34]], "歌曲段落"),
]


def evaluate(top_k: int = 4) -> dict:
    hits_total = 0
    details = []
    for q, expects, note in TEST_SET:
        results = retrieve(q, top_k=top_k)
        hit_keys = {(r["title"], r["start"]) for r in results}
        expected_keys = {(t, s) for t, s in expects}
        ok = expected_keys.issubset(hit_keys)
        hits_total += ok
        details.append((q, note, ok, [(r["title"], r["start"], r["score"]) for r in results]))
    acc = hits_total / len(TEST_SET)
    print(f"测试题数: {len(TEST_SET)} | top_k={top_k}")
    for q, note, ok, res in details:
        mark = "✅" if ok else "❌"
        print(f"{mark} [{note}] {q}")
        for t, s, sc in res:
            print(f"      -> {t} @{s}秒 score={sc}")
    print(f"\n检索准确率: {hits_total}/{len(TEST_SET)} = {acc*100:.1f}% (目标 ≥80%)")
    return {"accuracy": acc, "hits": hits_total, "total": len(TEST_SET)}


if __name__ == "__main__":
    evaluate()
