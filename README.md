# q-utils

Python(FastAPI) 기반 유틸리티 모음. 도커로 실행하며, 기능은 모듈 단위로 켜고 끌 수 있다.

## 실행 (Docker)

```bash
docker-compose up -d
```

- 웹 UI: http://localhost:8000/

## 제공 기능

| 모듈           | 이름               | 설명                                                              |
| -------------- | ------------------ | ----------------------------------------------------------------- |
| `html_to_pdf`  | HTML/URL → PDF     | HTML 문자열 또는 웹페이지 URL을 PDF로 변환                        |
| `media_ingest` | 오디오/비디오 추출 | 미디어 URL에서 오디오(MP3)·비디오(MP4) 추출, 진행상황 실시간 표시 |

## 모듈 선택

환경변수 `Q_UTILS_MODULES`로 켤 모듈을 고른다(미설정 시 전체).

```bash
# PDF 변환기만 사용
docker-compose run --rm -e Q_UTILS_MODULES=html_to_pdf -p 8000:8000 q-utils

# 또는 docker-compose.override.yml 에 고정
#   environment:
#     - Q_UTILS_MODULES=html_to_pdf
```

활성 모듈은 `GET /modules` 로 확인.

## 사용법

### HTML/URL → PDF

```bash
# HTML → PDF
curl -X POST localhost:8000/convert \
  -H 'Content-Type: application/json' \
  -d '{"html":"<h1>안녕</h1>"}' -o out.pdf

# URL → PDF
curl -X POST localhost:8000/convert_url \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}' -o page.pdf
```

웹 UI에서는 홈 화면의 "HTML 입력 / URL 입력" 섹션에서 바로 변환·미리보기 가능.

### 오디오/비디오 추출

```bash
# 오디오(MP3)
curl -X POST localhost:8000/media/audio \
  -H 'Content-Type: application/json' \
  -d '{"url":"<미디어 URL>"}' -o out.mp3

# 비디오(MP4)
curl -X POST localhost:8000/media/video \
  -H 'Content-Type: application/json' \
  -d '{"url":"<미디어 URL>"}' -o out.mp4
```

웹 UI의 "미디어 추출" 섹션에서 URL 입력 → 진행바로 진행상황을 실시간 확인 후 다운로드.

### CLI — 대량 수집

채널/프로필/재생목록을 통째로 훑어 여러 개를 한 번에 받는다. 웹서버와 무관하게 컨테이너 안에서 실행한다.

```bash
# 이 채널에서 최신 10개를 오디오로
docker-compose run --rm q-utils \
  python -m api.media_ingest.batch "https://youtube.com/@채널" -t audio -n 10 -o ./downloads

# 키워드 검색으로 수집 (유튜브) — identifier 대신 --search
docker-compose run --rm q-utils \
  python -m api.media_ingest.batch --search "로파이 음악" -t audio -n 1 --max-duration 600

# 다운로드 없이 URL 목록만 확인
docker-compose run --rm q-utils \
  python -m api.media_ingest.batch "https://youtube.com/@채널" --crawl-only -n 20
```

| 옵션                          | 기본값              | 설명                                                              |
| ----------------------------- | ------------------- | ----------------------------------------------------------------- |
| `identifier`                  | —                   | **어디서** — 채널/프로필/재생목록 URL (`--search` 쓰면 생략)      |
| `--search`                    | 없음                | **어디서(대체)** — 유튜브 키워드 검색 (예: `--search "재즈"`)     |
| `-n, --limit`                 | 피드=전체 / 검색=20 | **몇 개 성공시킬지** — 목표 성공 개수 (건너뜀은 미포함, 아래 참고) |
| `-t, --type`                  | `video`             | `audio` / `video`                                                 |
| `-o, --output`                | `./downloads`       | 저장 폴더                                                         |
| `--cookies-from-browser`      | 없음                | 로그인 쿠키 사용 (예: `chrome`)                                   |
| `--min-delay` / `--max-delay` | `3` / `7`           | 항목 간 지연(초)                                                  |
| `--retries`                   | `3`                 | 항목별 재시도 횟수                                                |
| `--max-duration`              | 없음                | 이 길이(초) 초과 항목은 **건너뜀** (예: `1200`=20분, 롱믹스 제외) |
| `--min-duration`              | 없음                | 이 길이(초) 미만 항목은 건너뜀                                    |
| `--exclude-title`             | 없음                | 제목이 이 **정규식**에 매칭되면 건너뜀 (예: `"무한반복\|loop\|[0-9]+시간\|수면"`) |
| `--archive`                   | 없음                | 다운로드 기록 파일 경로. 이미 받은 항목은 **다음 실행 때 건너뜀**(중복 방지) |
| `--overfetch`                 | `5`                 | 목표(`-n`) 대비 후보 수집 배수 (건너뜀 대비 백필용)              |
| `--crawl-only`                | off                 | 다운로드 없이 URL 목록만 출력                                     |

- **필터(길이/제목)**: 다운로드 **전에** 메타데이터만으로 걸러지므로 몇 시간짜리·반복 영상을 통째로 받지 않는다. 건너뛴 항목은 결과에서 `skipped`로 집계된다.
- 예) 롱믹스·수면음악 제외: `--max-duration 1200 --exclude-title "무한반복|loop|[0-9]+\s*시간|수면|asmr"`
- **`-n`은 "목표 성공 개수"**: 필터/중복으로 건너뛴 항목은 목표에 세지 않고, 후보를 `--overfetch`배 넉넉히 모아 **다음 항목으로 백필**한다(예: `-n 5`면 최대 `5×5=25`개 후보에서 성공 5개를 채운다). 후보가 소진되면 확보한 만큼만 반환하고 경고한다.
- **중복 방지**: `--archive archive.txt`를 주면 성공한 항목의 ID가 기록되어, 다음 실행 때 그 항목들은 자동으로 건너뛴다(정기 수집에 유용).
- **`-n` 미지정 시**: 피드(채널/재생목록)는 **전체 항목**을, 검색은 "전체"가 없으므로 **기본 20개**를 가져온다.
- `identifier` 또는 `--search` 중 **하나는 필수**.
- 대상은 **유튜브/인스타그램/틱톡**(검색은 유튜브만). 단일 스트림 URL(`.m3u8` 등)은 위의 `/media/*` 엔드포인트로.
- CLI는 **일회성**이다. 정기 실행은 cron 등 외부 스케줄러에 맡긴다.

> ⚠️ 미디어 추출은 접근 권한이 있는 콘텐츠에만 사용하고 대상 사이트의 약관·저작권을 준수할 것.
