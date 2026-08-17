#!/usr/bin/env python3
"""새 산업을 sources.yaml / prompts/{산업}.md / index.html에 스캐폴딩한다.

    python add_industry.py 반도체
    python add_industry.py 컨설팅2 --lookback-days 10 --query "쿼리 OR 쿼리2"

실행 후에도 세 가지는 직접 손봐야 한다:
  1. sources.yaml   — 넣어준 gnews 쿼리 1개는 자리표시자다. 실제 소스로 교체/추가하라.
  2. prompts/{산업}.md — 태그 체계·관점을 채워라. 비워두면 요약 품질이 떨어진다.
  3. python collect.py --check --only {산업}  로 피드가 살아있는지 확인하라.
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.yaml"
PROMPTS_DIR = ROOT / "prompts"
INDEX_FILE = ROOT / "index.html"

SOURCES_MARKER = (
    "\n# =====================================================================\n"
    "#  RSS를 제공하지 않아 자동 수집이 어려운 고가치 소스"
)

PROMPT_TEMPLATE = """# {name} 산업 지침

## 태그 체계 (반드시 하나 이상 선택)
`TODO` `TODO` `TODO` `TODO` `TODO`

## 이 산업을 볼 때의 관점

1. TODO — 이 산업의 밸류체인/구조를 볼 때 가장 먼저 확인할 축.
2. TODO — 현재 이 산업 최대 변수(전환점, 규제, 경쟁구도 등).
3. TODO

## 특별 지시
- TODO — 걸러야 할 마케팅성/노이즈 기사 유형.
"""


def load_sources_text() -> str:
    return SOURCES_FILE.read_text(encoding="utf-8")


def existing_industries() -> set:
    with SOURCES_FILE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return set(data.get("industries", {}).keys())


def build_sources_block(name: str, query: str, lookback_days: int | None) -> str:
    lookback_line = f'    lookback_days: {lookback_days}\n' if lookback_days else ""
    bar = "─" * 33
    return (
        f"\n  # {bar} {name}\n"
        f"  {name}:\n"
        f"{lookback_line}"
        f"    feeds:\n"
        f'      - {{ type: gnews, name: "{name} 업계",   query: "{query}" }}\n'
    )


def insert_sources_block(text: str, block: str) -> str:
    idx = text.find(SOURCES_MARKER)
    if idx == -1:
        # marker가 없으면 파일 끝(수동 워치리스트 섹션 없음)에 그냥 붙인다.
        return text.rstrip("\n") + "\n" + block
    return text[:idx] + block + text[idx:]


def update_index_html(name: str) -> bool:
    text = INDEX_FILE.read_text(encoding="utf-8")
    if f'key: "{name}"' in text:
        return False
    new_entry = f'  {{ key: "{name}" }},\n'
    marker = "const INDUSTRIES = [\n"
    idx = text.find(marker)
    if idx == -1:
        return False
    insert_at = idx + len(marker)
    text = text[:insert_at] + new_entry + text[insert_at:]
    INDEX_FILE.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="새 산업 스캐폴딩")
    parser.add_argument("name", help="산업명 (예: 반도체)")
    parser.add_argument("--query", default=None, help="시작용 gnews 검색어 (기본: '{name} 업계 OR {name} 산업동향')")
    parser.add_argument("--lookback-days", type=int, default=None, help="이 산업만 다른 lookback (기본: 전역값 2일)")
    parser.add_argument("--dry-run", action="store_true", help="파일에 쓰지 않고 결과만 출력")
    args = parser.parse_args()

    name = args.name.strip()
    if not name:
        print("산업명이 비어있습니다.", file=sys.stderr)
        sys.exit(1)

    if name in existing_industries():
        print(f"'{name}'은(는) 이미 sources.yaml에 있습니다.", file=sys.stderr)
        sys.exit(1)

    query = args.query or f"{name} 업계 OR {name} 산업동향"
    sources_block = build_sources_block(name, query, args.lookback_days)
    prompt_content = PROMPT_TEMPLATE.format(name=name)
    prompt_path = PROMPTS_DIR / f"{name}.md"

    if args.dry_run:
        print("=== sources.yaml에 추가될 블록 ===")
        print(sources_block)
        print(f"=== {prompt_path.relative_to(ROOT)} (신규) ===")
        print(prompt_content)
        print(f"=== index.html INDUSTRIES 배열에 {{ key: \"{name}\" }} 추가 ===")
        return

    sources_text = load_sources_text()
    SOURCES_FILE.write_text(insert_sources_block(sources_text, sources_block), encoding="utf-8")
    print(f"[OK] sources.yaml에 '{name}' 블록 추가")

    if prompt_path.exists():
        print(f"[SKIP] {prompt_path.relative_to(ROOT)} 이미 존재, 덮어쓰지 않음")
    else:
        prompt_path.write_text(prompt_content, encoding="utf-8")
        print(f"[OK] {prompt_path.relative_to(ROOT)} 생성")

    if update_index_html(name):
        print(f"[OK] index.html INDUSTRIES 배열에 '{name}' 추가")
    else:
        print("[SKIP] index.html은 이미 반영되어 있거나 마커를 찾지 못함")

    print()
    print("다음을 직접 확인하세요:")
    print(f"  1. sources.yaml → industries.{name}.feeds  (자리표시자 쿼리를 실제 소스로 교체)")
    print(f"  2. prompts/{name}.md  (TODO 채우기)")
    print(f"  3. python collect.py --check --only {name}")


if __name__ == "__main__":
    main()
