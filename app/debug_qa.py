"""诊断脚本:跑一次完整问答,把错误完整保存到 qa_debug.txt(供排查)"""
import sys, traceback, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from app.query import answer
    print("开始问答(约 1-2 分钟)...")
    r = answer("组会里HBase查询变慢的原因是什么?")
    print("✅ 问答成功:")
    print(r["answer"][:200])
    for c in r["citations"]:
        print(f"  [{c['start']}-{c['end']}秒] {c['title']}")
except Exception:
    out = Path("qa_debug.txt")
    with open(out, "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    print(f"❌ 问答失败,完整错误已保存到: {out.resolve()}")
    print("请把上面这行路径告诉我,我会读取分析。")
