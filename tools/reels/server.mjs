/**
 * 영상 만드는 일꾼 — 서버가 HTTP 로 부른다.
 *
 * 헤드리스 크롬과 ffmpeg 이 든 컨테이너라 API 이미지와 따로 둔다. 같이 구우면
 * **API 이미지가 2GB 로 불어서** 배포할 때마다 그걸 다시 받는다.
 *
 * ```
 *   API (workers/draw_videos.py)  --POST /render {token}-->  여기
 *                                 <---------- mp4 -----------
 * ```
 *
 * **호스트에 포트를 안 연다** — 도커 내부망에서만 닿는다. 그래도 열쇠를
 * 하나 받는다(`RENDER_TOKEN`): 같은 서버에 다른 스택이 여럿 올라와 있어서,
 * 어느 하나가 뚫렸을 때 이걸로 남의 페이지를 찍게 만들 수 있으면 안 된다.
 */
import { createServer } from 'node:http';
import { readFile, rm } from 'node:fs/promises';
import path from 'node:path';

import { render, MAX_SEC } from './render.mjs';

const PORT = Number(process.env.PORT || 3000);
const CLIENT = (process.env.CLIENT_BASE_URL || 'http://localhost:3000').replace(/\/$/, '');
const TOKEN = process.env.RENDER_TOKEN || '';
/** 한 번에 한 판만 찍는다 — 크롬 둘이 같이 돌면 프레임이 밀린다 */
let busy = false;

function json(res, code, body) {
  const s = JSON.stringify(body);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(s);
}

const server = createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') return json(res, 200, { ok: true });
  if (req.method !== 'POST' || !req.url.startsWith('/render')) return json(res, 404, { code: 'NOT_FOUND' });
  if (TOKEN && req.headers['x-render-token'] !== TOKEN) return json(res, 401, { code: 'UNAUTHORIZED' });
  if (busy) return json(res, 409, { code: 'BUSY', message: '다른 영상을 만드는 중입니다' });

  let raw = '';
  for await (const c of req) raw += c;
  let token;
  try {
    ({ token } = JSON.parse(raw || '{}'));
  } catch {
    return json(res, 400, { code: 'BAD_JSON' });
  }
  // 주소를 통째로 안 받는다 — 받으면 이 일꾼이 아무 페이지나 찍는 도구가 된다
  if (!token || !/^[A-Za-z0-9_-]{4,64}$/.test(token)) return json(res, 400, { code: 'BAD_TOKEN' });

  busy = true;
  const out = path.join(process.env.TMPDIR || '/tmp', `reels-${Date.now()}.mp4`);
  const t0 = Date.now();
  try {
    await render({
      url: `${CLIENT}/tv/${encodeURIComponent(token)}/reels`,
      out,
      onLog: (m) => console.log(`[${token}] ${m}`),
    });
    const buf = await readFile(out);
    res.writeHead(200, {
      'content-type': 'video/mp4',
      'content-length': buf.length,
      'x-render-seconds': ((Date.now() - t0) / 1000).toFixed(1),
    });
    res.end(buf);
  } catch (e) {
    console.error(`[${token}] 실패`, e);
    json(res, 500, { code: 'RENDER_FAILED', message: String(e && e.message ? e.message : e) });
  } finally {
    await rm(out, { force: true });
    busy = false;
  }
});

// 한 판이 아무리 길어도 [MAX_SEC] 에 굽는 시간을 더한 만큼은 기다려야 한다
server.requestTimeout = (MAX_SEC + 180) * 1000;
server.headersTimeout = server.requestTimeout + 5000;
server.listen(PORT, () => console.log(`영상 일꾼 ${PORT} · 클라이언트 ${CLIENT}`));
