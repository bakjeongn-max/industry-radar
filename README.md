# industry-radar

자동차 · 건설 · 식품 · 컨설팅 4개 산업의 뉴스를 매일 수집해
Claude로 **산업 스터디 노트**를 생성하고 마크다운 로그에 누적하는 파이프라인.

```
industry-radar/
├── sources.yaml            ← 산업별 소스 목록 (여기만 고쳐도 대부분 커버)
├── prompts/
│   ├── _base.md            ← 공통 출력 규칙
│   ├── 자동차.md 건설.md 식품.md 컨설팅.md   ← 산업별 관점·태그 체계
├── collect.py              ← 수집 → 요약 → 적재
├── logs/{산업}.md          ← 결과물 (날짜별 누적)
├── .state/                 ← 중복 방지용 링크 해시 (건드릴 필요 없음)
├── index.html              ← 산업별 최신 리포트 열람·다운로드(MD/Word) 웹페이지
└── .github/workflows/daily.yml
```

---

## 1. 로컬에서 먼저 돌려보기

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."

python collect.py --check      # ① 피드가 살아있는지 점검 (API 호출 없음)
python collect.py --dry-run    # ② 뭐가 긁히는지 확인 (API 호출 없음)
python collect.py              # ③ 실제 요약·적재
python collect.py --weekly     # ④ 주간 롤업
python collect.py --only 식품  # 특정 산업만
```

**반드시 ①번부터 하세요.** `rss` 타입 주소는 기관 사정으로 자주 바뀝니다.
죽은 피드가 나오면 `sources.yaml`에서 지우고 `gnews` 항목으로 대체하면 됩니다.
`gnews`(Google News RSS)는 주소가 자동 조립되어 항상 동작합니다.

## 2. GitHub Actions로 무인화

1. 이 폴더를 **public 저장소**로 push (GitHub Pages 무료 사용을 위해 public 필요.
   뉴스 요약 결과만 공개되고 `ANTHROPIC_API_KEY`는 Actions Secret이라 노출되지 않음)
2. Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` 등록
3. 끝. 평일 07:00 KST 수집, 금요일 18:00 KST 주간 롤업이 자동 실행되고
   결과가 `logs/`에 커밋됩니다.

수동 실행은 Actions 탭 → Run workflow → mode에 `check`/`weekly` 입력.

## 3. 웹페이지 (`index.html`)

산업 탭을 선택하면 `logs/{산업}.md`에서 **가장 최근 노트 1건**만 추출해 보여주고,
`MD` / `Word` 버튼으로 그 리포트를 파일로 내려받을 수 있습니다.

- Settings → Pages → Source를 `main` 브랜치 `/ (root)`로 지정하면
  `https://{계정}.github.io/industry-radar/`에서 바로 열립니다.
- 별도 빌드 과정 없이 정적 파일이라 `logs/`가 커밋될 때마다 자동으로 최신 내용이 반영됩니다.
- Word 다운로드는 실제 `.docx`가 아니라 Word가 인식하는 HTML 기반 `.doc`입니다
  (외부 라이브러리 의존 없이 브라우저에서 바로 생성).

## 4. 튜닝 포인트

| 원하는 것 | 고칠 곳 |
|---|---|
| 소스 추가·교체 | `sources.yaml` → `industries.{산업}.feeds` |
| 산업 추가 | `sources.yaml`에 블록 추가 + `prompts/{산업명}.md` 생성 |
| 요약 관점 변경 | `prompts/{산업}.md` |
| 출력 형식 변경 | `prompts/_base.md` |
| 수집량 조절 | `sources.yaml` → `defaults.max_items_per_feed` |
| 실행 시각 | `.github/workflows/daily.yml` → cron (UTC 기준) |

`prompts/*.md`가 이 파이프라인의 실질적인 핵심입니다.
2~3주 돌려보고 노트가 밋밋하면 소스가 아니라 **지침을 손보세요.**

## 5. 자동화 밖에 두어야 하는 것

`sources.yaml`의 `manual_watchlist` 항목은 RSS가 없어 자동 수집이 어렵습니다.
다만 **정보 밀도는 뉴스보다 훨씬 높습니다.** 특히:

- **한경 컨센서스** — 증권사 산업분석 PDF. 주 1회 자동차/건설/음식료 섹터만 훑어도 뉴스 한 달치 값어치
- **DART 사업보고서** — "사업의 내용" 챕터가 사실상 산업 개론서

이건 주 1회 직접 받아서 Claude에 붙여 읽는 편이 낫습니다.

## 6. 주의

- 유료 DB·회원제 사이트는 약관상 자동 수집을 금지하는 곳이 많습니다.
  공식 RSS/오픈API를 제공하는 소스만 넣으세요.
- 인스타그램은 공식 API로 타 계정 콘텐츠 수집이 막혀 있어 제외했습니다.
- API 비용은 4개 산업 × 평일 기준 월 수천 원 수준이지만,
  `max_items_per_feed`를 키우면 빠르게 늘어납니다.
