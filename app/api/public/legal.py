"""약관·개인정보처리방침 — **로그인 없는** 공개 페이지.

스토어에 올리려면 **밖에서 열리는 주소**가 있어야 한다. Play 는 `앱 콘텐츠` 에
개인정보처리방침 URL 을 필수로 받고, 애플도 App Store Connect 에서 같은 것을
묻는다. 앱 안에서만 보여 주는 것으로는 그 칸을 못 채운다.

**앱과 같은 md 를 그대로 서빙한다** (`app/web/legal/*.md`). 문서를 두 벌로
적으면 개정할 때 한쪽만 고쳐져서 어긋난다 — 실제로 어긋나면 안 되는 종류의
문서다.

> ⚠️ **원본은 앱 레포의 `assets/legal/` 이다.** 여기 있는 것은 그 복사본이라
> 문서를 고치면 **양쪽을 같이** 올려야 한다. 앱의 `LegalDocument` 버전
> (`legal_screen.dart`)도 같은 규칙이다 — md 첫머리의 `시행일` 과 같은 값을 쓴다.

마크다운 라이브러리를 안 쓴다. 이 두 문서가 쓰는 문법이 **제목·불릿·번호·굵게**
넷뿐이라(표·링크·이미지 없음) 의존성을 하나 늘릴 이유가 없다. 문서에 새 문법을
쓰게 되면 그때 [_to_html] 을 늘리거나 라이브러리를 들인다.
"""

import html
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal"])

_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "legal"

_TITLES = {"privacy": "개인정보처리방침", "terms": "이용약관"}

# 굵게 — 안쪽에 * 가 없는 가장 짧은 짝만 잡는다
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    """한 줄 안쪽 서식 — **굵게** 만 다룬다.

    이스케이프를 **먼저** 하고 태그를 만든다. 순서가 바뀌면 문서에 `<` 가
    들어왔을 때 그대로 태그로 새어 나간다.
    """
    return _BOLD.sub(r"<strong>\1</strong>", html.escape(text))


def _to_html(md: str) -> str:
    """마크다운 → 본문 HTML.

    빈 줄이 문단을 가른다. 목록은 줄이 이어지는 동안 한 덩어리로 묶는다 —
    줄마다 `<ul>` 를 새로 열면 항목 사이가 벌어진다.
    """
    out: list[str] = []
    # 지금 열려 있는 목록 태그 (None 이면 목록 밖)
    open_list: str | None = None
    # 여러 줄에 걸친 문단을 모아 두는 자리
    para: list[str] = []

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            out.append(f"</{open_list}>")
            open_list = None

    def flush_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_para()
            close_list()
            continue

        if heading := re.match(r"^(#{1,6})\s+(.*)$", stripped):
            flush_para()
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        if item := re.match(r"^[-*]\s+(.*)$", stripped):
            flush_para()
            if open_list != "ul":
                close_list()
                out.append("<ul>")
                open_list = "ul"
            out.append(f"<li>{_inline(item.group(1))}</li>")
            continue

        if item := re.match(r"^\d+\.\s+(.*)$", stripped):
            flush_para()
            if open_list != "ol":
                close_list()
                out.append("<ol>")
                open_list = "ol"
            out.append(f"<li>{_inline(item.group(1))}</li>")
            continue

        # 목록 항목이 다음 줄로 이어진 것 — 마지막 <li> 뒤에 붙인다
        if open_list and raw.startswith(" ") and out and out[-1].endswith("</li>"):
            out[-1] = out[-1][: -len("</li>")] + " " + _inline(stripped) + "</li>"
            continue

        close_list()
        para.append(stripped)

    flush_para()
    close_list()
    return "\n".join(out)


# 글꼴을 밖에서 안 받아온다 — 이 페이지는 심사·크롤러가 보는 자리라
# 네트워크가 하나라도 막히면 안 뜨는 것보다 기본 글꼴이 낫다.
_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · HiFIS</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0 auto; padding: 32px 20px 80px; max-width: 720px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      "Helvetica Neue", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    font-size: 16px; line-height: 1.75; color: #191F28; background: #fff;
    word-break: keep-all;
  }}
  h1 {{ font-size: 26px; margin: 0 0 24px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 20px; margin: 40px 0 12px; letter-spacing: -0.01em; }}
  h3 {{ font-size: 17px; margin: 28px 0 8px; }}
  p, li {{ color: #4E5968; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 6px 0; }}
  strong {{ color: #191F28; }}
  footer {{ margin-top: 56px; font-size: 13px; color: #8B95A1; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #E7EBF0; background: #101419; }}
    p, li {{ color: #A8B1BD; }}
    strong {{ color: #E7EBF0; }}
    footer {{ color: #6B7684; }}
  }}
</style>
</head>
<body>
{body}
<footer>피트니스스타 · HiFIS</footer>
</body>
</html>
"""


def _render(name: str) -> HTMLResponse:
    path = _DIR / f"{name}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없어요.")
    body = _to_html(path.read_text(encoding="utf-8"))
    return HTMLResponse(_PAGE.format(title=_TITLES[name], body=body))


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_page() -> HTMLResponse:
    return _render("privacy")


@router.get("/terms", response_class=HTMLResponse, include_in_schema=False)
async def terms_page() -> HTMLResponse:
    return _render("terms")
