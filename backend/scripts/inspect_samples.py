"""临时脚本：查看真实样例文件的解析结果，用于校准端到端测试断言。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.imports.parser import parse_document  # noqa: E402
from app.imports.normalizer import sha256_hex  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"


def main() -> None:
    for name in ("java热门面试.md", "java热门面试-v2.md"):
        raw = (SAMPLES / name).read_bytes()
        parsed = parse_document(
            raw.decode("utf-8"),
            source_filename=name,
            source_hash=sha256_hex(raw),
        )
        print(f"=== {name} ===")
        print(f"标题总数: {len(parsed.headings)}  题目候选: {len(parsed.items)}")
        for item in parsed.items:
            mark = {"question": "Q", "needs_review": "?", "section": "-"}[item.classification]
            print(f"  [{mark}] h{item.level} score={item.score:>3} {item.title}")
            print(f"        path={item.section_path} answer_len={len(item.answer_markdown)}")
        print(f"  warnings: {parsed.warnings}")
        print()


if __name__ == "__main__":
    main()
