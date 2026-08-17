#!/usr/bin/env python3
"""industry-radar: RSS/GNews 수집 -> Claude 요약 -> logs/{산업}.md 적재"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.yaml"
PROMPTS_DIR = ROOT / "prompts"
LOGS_DIR = ROOT / "logs"
STATE_DIR = ROOT / ".state"

GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
REQUEST_TIMEOUT = 10
REQUEST_HEADERS = {"User-Agent": "industry-radar/1.0"}
MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
KST = timezone(timedelta(hours=9))


def today_kst() -> datetime:
    """GitHub Actions 러너는 시스템 시간이 UTC라 datetime.now()를 그대로 쓰면
    07:00 KST 실행분이 전날 날짜로 찍힌다. 항상 KST 기준으로 오늘을 계산한다."""
    return datetime.now(KST).replace(tzinfo=None)


def load_sources() -> dict:
    with SOURCES_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def feed_url(feed: dict) -> str:
    if feed["type"] == "gnews":
        return GNEWS_BASE.format(query=quote(feed["query"]))
    return feed["url"]


def fetch_feed(url: str):
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=REQUEST_HEADERS)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def entry_published(entry):
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def link_hash(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()


def load_state(industry: str) -> set:
    path = STATE_DIR / f"{industry}.json"
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as f:
        return set(json.load(f).get("seen", []))


def save_state(industry: str, seen: set) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"{industry}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump({"seen": sorted(seen)}, f, ensure_ascii=False, indent=2)


def check_feed(feed: dict) -> tuple:
    url = feed_url(feed)
    try:
        parsed = fetch_feed(url)
    except requests.RequestException as e:
        return False, f"요청 실패: {e}"
    if parsed.bozo and not parsed.entries:
        return False, f"파싱 실패: {parsed.bozo_exception}"
    if not parsed.entries:
        return False, "항목 없음"
    return True, f"{len(parsed.entries)}건"


def collect_feed_items(feed: dict, max_items: int, cutoff: datetime) -> list:
    url = feed_url(feed)
    try:
        parsed = fetch_feed(url)
    except requests.RequestException:
        return []
    items = []
    for entry in parsed.entries:
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue
        published = entry_published(entry)
        if published and published < cutoff:
            continue
        items.append({
            "title": title.strip(),
            "link": link.strip(),
            "published": published.isoformat() if published else None,
            "source": feed["name"],
        })
        if len(items) >= max_items:
            break
    return items


def collect_industry(cfg: dict, defaults: dict, seen: set) -> list:
    lookback_days = cfg.get("lookback_days", defaults.get("lookback_days", 2))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    max_items = defaults.get("max_items_per_feed", 15)
    collected = []
    for feed in cfg["feeds"]:
        for item in collect_feed_items(feed, max_items, cutoff):
            h = link_hash(item["link"])
            if h in seen:
                continue
            item["hash"] = h
            collected.append(item)
    return collected


def cmd_check(sources: dict, only) -> None:
    total_dead = 0
    for name, cfg in sources["industries"].items():
        if only and name not in only:
            continue
        print(f"\n=== {cfg.get('emoji', '')} {name} ===")
        for feed in cfg["feeds"]:
            ok, detail = check_feed(feed)
            status = "OK  " if ok else "DEAD"
            print(f"  [{status}] ({feed['type']:5s}) {feed['name']:20s} {detail}")
            if not ok:
                total_dead += 1
    print()
    if total_dead:
        print(f"경고: 죽은 피드 {total_dead}건. sources.yaml에서 제거 후 gnews 항목으로 대체하세요.")
        sys.exit(1)
    print("모든 피드 정상.")


def cmd_dry_run(sources: dict, only) -> None:
    defaults = sources.get("defaults", {})
    for name, cfg in sources["industries"].items():
        if only and name not in only:
            continue
        seen = load_state(name)
        items = collect_industry(cfg, defaults, seen)
        print(f"\n=== {cfg.get('emoji', '')} {name} ({len(items)}건, 신규만) ===")
        for item in items:
            print(f"  - [{item['source']}] {item['title']}")
            print(f"    {item['link']}")
        if not items:
            print("  (신규 항목 없음)")


def build_daily_system_prompt(industry: str) -> str:
    base = (PROMPTS_DIR / "_base.md").read_text(encoding="utf-8")
    specific = (PROMPTS_DIR / f"{industry}.md").read_text(encoding="utf-8")
    return f"{base}\n\n---\n\n{specific}"


def summarize_daily(client, industry: str, items: list, date_str: str) -> str:
    system_prompt = build_daily_system_prompt(industry)
    articles = "\n\n".join(
        f"제목: {it['title']}\n출처: {it['source']}\nURL: {it['link']}"
        for it in items
    )
    user_content = (
        f"오늘 날짜: {date_str}\n산업: {industry}\n\n"
        f"아래는 오늘 수집된 기사 목록이다. 지침에 따라 노트를 작성하라.\n\n{articles}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def make_client():
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY 환경변수가 없습니다.", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def cmd_run(sources: dict, only) -> None:
    client = make_client()
    defaults = sources.get("defaults", {})
    date_str = today_kst().strftime("%Y-%m-%d")

    for name, cfg in sources["industries"].items():
        if only and name not in only:
            continue
        seen = load_state(name)
        items = collect_industry(cfg, defaults, seen)
        if not items:
            print(f"[{name}] 신규 항목 없음, 스킵")
            continue
        print(f"[{name}] {len(items)}건 요약 중...")
        note = summarize_daily(client, name, items, date_str)
        LOGS_DIR.mkdir(exist_ok=True)
        log_path = LOGS_DIR / f"{name}.md"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{note.strip()}\n")
        seen.update(item["hash"] for item in items)
        save_state(name, seen)
        print(f"[{name}] logs/{name}.md 에 적재 완료")


def cmd_weekly(sources: dict, only) -> None:
    client = make_client()
    date_str = today_kst().strftime("%Y-%m-%d")
    cutoff = today_kst() - timedelta(days=7)
    section_re = re.compile(r"^## (\d{4}-\d{2}-\d{2}) · ", re.MULTILINE)

    for name in sources["industries"]:
        if only and name not in only:
            continue
        log_path = LOGS_DIR / f"{name}.md"
        if not log_path.exists():
            print(f"[{name}] 로그 없음, 스킵")
            continue
        content = log_path.read_text(encoding="utf-8")
        matches = list(section_re.finditer(content))
        recent_chunks = []
        for i, m in enumerate(matches):
            try:
                day = datetime.strptime(m.group(1), "%Y-%m-%d")
            except ValueError:
                continue
            if day < cutoff:
                continue
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            recent_chunks.append(content[start:end].strip())
        if not recent_chunks:
            print(f"[{name}] 최근 7일 내 노트 없음, 스킵")
            continue

        print(f"[{name}] 최근 {len(recent_chunks)}일치 롤업 생성 중...")
        base_prompt = (PROMPTS_DIR / "_base.md").read_text(encoding="utf-8")
        specific_prompt = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        system_prompt = (
            f"{base_prompt}\n\n---\n\n{specific_prompt}\n\n---\n\n"
            "지금은 일간 노트가 아니라 주간 롤업이다. 출력 형식의 '## {날짜} · {산업명}'을 "
            "'## {날짜} · {산업명} · 주간 롤업'으로 바꾸고, 아래 여러 날짜의 일간 노트를 종합해 "
            "이번 주 산업 흐름을 재구성하라. 하루짜리 반복 언급은 통합하고, 이번 주에만 보이는 "
            "패턴이나 방향 전환이 있으면 강조하라."
        )
        joined = "\n\n".join(recent_chunks)
        user_content = f"오늘 날짜: {date_str}\n산업: {name}\n\n{joined}"
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        note = "".join(block.text for block in response.content if block.type == "text")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{note.strip()}\n")
        print(f"[{name}] 주간 롤업 적재 완료")


def main() -> None:
    parser = argparse.ArgumentParser(description="industry-radar collector")
    parser.add_argument("--check", action="store_true", help="피드 생존 여부만 점검 (API 호출 없음)")
    parser.add_argument("--dry-run", action="store_true", help="수집될 항목만 표시 (API 호출 없음)")
    parser.add_argument("--weekly", action="store_true", help="주간 롤업 생성")
    parser.add_argument("--only", action="append", default=None, help="특정 산업만 처리 (여러 번 지정 가능)")
    args = parser.parse_args()

    sources = load_sources()
    only = set(args.only) if args.only else None
    if only:
        valid = set(sources["industries"].keys())
        unknown = only - valid
        if unknown:
            print(f"알 수 없는 산업: {', '.join(unknown)} (사용 가능: {', '.join(valid)})", file=sys.stderr)
            sys.exit(1)

    if args.check:
        cmd_check(sources, only)
    elif args.dry_run:
        cmd_dry_run(sources, only)
    elif args.weekly:
        cmd_weekly(sources, only)
    else:
        cmd_run(sources, only)


if __name__ == "__main__":
    main()
