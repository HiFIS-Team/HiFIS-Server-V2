/**
 * 추첨 게임 영상 만들기 — 릴스용 세로 영상(1080×1920).
 *
 * 클라이언트의 `/tv/{token}/reels` 를 헤드리스 크롬으로 열어 화면을 그대로
 * 받아 적고 ffmpeg 으로 mp4 로 굽는다. 게임이 **결정적**이라 여기서 찍은
 * 영상과 매장에 걸린 TV 가 완전히 같은 경기다.
 *
 * ```
 *   페이지 열기 → __reels.ready 를 기다린다 (추첨을 받아오는 동안)
 *              → 화면 받아 적기 시작
 *              → __reelsStart()  ← 여기서부터 게임이 굴러간다
 *              → __reels.done 이 될 때까지
 *              → ffmpeg 으로 mp4
 * ```
 *
 * **왜 게임을 붙잡아 두나** — 안 그러면 추첨을 받아오는 사이에 게임이 이미
 * 시작해서, 녹화를 켜는 순간에는 몇 초가 지나 있다. 영상 앞이 잘린다.
 *
 * 쓰는 법:
 *   node render.mjs --token bj8wqdub --out /tmp/화순.mp4
 *   node render.mjs --token bj8wqdub --frames /tmp/f   (프레임만, ffmpeg 없이)
 */
import { spawn } from 'node:child_process';
import { copyFile, mkdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { chromium } from 'playwright';

/** 릴스 규격 — 인스타가 세로 9:16 을 이 크기로 받는다 */
export const WIDTH = 1080;
export const HEIGHT = 1920;
/** 영상 프레임률 — 30 이면 캔버스 게임이 충분히 매끄럽다 */
export const FPS = 30;
/**
 * 한 판이 아무리 길어도 여기서 끊는다(초).
 *
 * 게임은 20~40초에 결과 7초라 50초면 끝나는데, 페이지가 어딘가에서 멎으면
 * 이 잡이 영영 안 끝난다. **끊는 것이 매달리는 것보다 낫다.**
 */
export const MAX_SEC = 120;
/** 화면이 준비되기를 기다리는 한도(ms) — 추첨을 받아오는 시간이다 */
const READY_MS = 30000;

const FFMPEG = process.env.FFMPEG_PATH || 'ffmpeg';

/** 명령줄 `--이름 값` 을 읽는다 */
function args(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, '')] = argv[i + 1];
  return out;
}

/**
 * 게임 한 판을 찍어 프레임으로 남긴다 — **시계를 멈춰 두고 한 장씩 넘긴다.**
 *
 * 예전에는 크롬이 실시간으로 그리는 화면을 받아 적었는데(screencast), 운영
 * 일꾼은 CPU 가 2개라 1080×1920 을 **평균 18.6fps** 밖에 못 그렸다 — 30fps 로
 * 다시 깔아도 같은 장면이 겹쳐서 **영상이 뚝뚝 끊겼다** (2026-10-01 대표 지적).
 *
 * 이제는 페이지 시계(`page.clock`)를 멈춰 두고 1/30초씩 넘기며 한 장씩 찍는다.
 * 게임은 `requestAnimationFrame` 시각으로 굴러가서, 찍는 데 얼마가 걸리든
 * **프레임 사이가 정확히 1/30초**다. 대신 굽는 데 몇 분이 걸린다 (달에 한 번이다).
 *
 * **CSS 애니메이션은 시계를 안 따른다** — 시상대 카드가 올라오는 것 같은 것.
 * 그대로 두면 찍는 동안 실시간으로 끝나 버려서, 프레임마다 손으로 감는다 ([STEP_CSS]).
 */
const STEP_CSS = `(now) => {
  for (const a of document.getAnimations()) {
    if (a.__v0 === undefined) {
      a.__v0 = now - (Number(a.currentTime) || 0);
      a.pause();
    }
    a.currentTime = now - a.__v0;
  }
}`;

export async function capture({ url, dir, onLog = () => {} }) {
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });

  const browser = await chromium.launch({
    args: ['--hide-scrollbars', '--force-device-scale-factor=1', '--autoplay-policy=no-user-gesture-required'],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
    });
    // **페이지가 뜨기 전에** 시계를 갈아 끼운다 — 뜬 뒤에 걸면 이미 돌기 시작한
    // 타이머·rAF 는 진짜 시계를 탄다
    await page.clock.install();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: READY_MS });
    // **멈춰 둔다** — `install` 만 하면 진짜 시간도 같이 흘러서, 찍는 동안
    // 흐른 시간만큼 영상이 빨라진다 (처음에 1.8배 빨랐다)
    await page.clock.pauseAt(Date.now() + 1000);

    // 추첨을 받아오고 게임 채비가 끝날 때까지 — 시계가 멈춰 있으니 조금씩 밀어 준다
    const readyBy = Date.now() + READY_MS;
    while (!(await page.evaluate(() => window.__reels?.ready === true))) {
      if (Date.now() > readyBy) throw new Error('화면이 준비되지 않았다 (추첨을 못 받아왔다)');
      await page.clock.runFor(100);
      await page.waitForTimeout(100);
    }
    onLog('준비됨');

    await page.evaluate(() => window.__reelsStart?.());
    const step = 1000 / FPS;
    const stamps = [];
    const t0 = Date.now();
    let n = 0;
    for (; n < MAX_SEC * FPS; n++) {
      await page.clock.runFor(step);
      await page.evaluate(`(${STEP_CSS})(${(n + 1) * step})`);
      const buf = await page.screenshot({ type: 'jpeg', quality: 92 });
      await writeFile(path.join(dir, `f${String(n).padStart(6, '0')}.jpg`), buf);
      stamps.push(n / FPS);
      if (await page.evaluate(() => window.__reels?.done === true)) {
        n++;
        break;
      }
    }
    const secs = n / FPS;
    onLog(`프레임 ${n}장 · 영상 ${secs.toFixed(1)}초 · 찍는 데 ${((Date.now() - t0) / 1000).toFixed(0)}초`);
    return { dir, count: n, stamps, seconds: secs };
  } finally {
    await browser.close();
  }
}

/**
 * 뽑아 둔 프레임을 mp4 로 굽는다.
 *
 * 프레임마다 **다음 프레임까지 걸린 시간**을 적어 주고(`concat` 의 `duration`),
 * ffmpeg 이 고정 30fps 로 다시 깐다. 이게 없으면 크롬이 버벅인 구간이
 * 영상에서 빨라진다.
 */
export async function encode({ dir, count, stamps, out }) {
  if (count === 0) throw new Error('찍힌 프레임이 없다');

  const lines = [];
  for (let i = 0; i < count; i++) {
    const next = i + 1 < count ? stamps[i + 1] : stamps[i] + 1 / FPS;
    lines.push(`file 'f${String(i).padStart(6, '0')}.jpg'`);
    lines.push(`duration ${Math.max(1 / 240, next - stamps[i]).toFixed(6)}`);
  }
  // concat 은 마지막 파일을 한 번 더 적어 줘야 그 장을 안 버린다
  lines.push(`file 'f${String(count - 1).padStart(6, '0')}.jpg'`);
  const list = path.join(dir, 'list.txt');
  await writeFile(list, lines.join('\n'));

  await run(FFMPEG, [
    '-y', '-f', 'concat', '-safe', '0', '-i', list,
    '-vf', `scale=${WIDTH}:${HEIGHT}:flags=lanczos,fps=${FPS},format=yuv420p`,
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
    // 인스타가 못 받는 일이 없게 — 널리 도는 프로필로 굽고 헤더를 앞으로 뺀다
    '-profile:v', 'high', '-level', '4.0', '-movflags', '+faststart',
    out,
  ]);
  return out;
}

function run(cmd, argv) {
  return new Promise((ok, no) => {
    const p = spawn(cmd, argv, { stdio: ['ignore', 'ignore', 'pipe'] });
    let err = '';
    p.stderr.on('data', (d) => { err += d; });
    p.on('error', no);
    p.on('close', (code) => (code === 0 ? ok() : no(new Error(`${cmd} ${code}\n${err.slice(-2000)}`))));
  });
}

/**
 * 페이지를 열어 mp4 와 **포스터 한 장**까지 한 번에.
 *
 * 포스터는 **마지막 프레임**이다 — 거기가 폭죽이 다 걷힌 시상대라 한 장으로
 * 그달을 말해 준다. 찍어 둔 프레임을 그냥 복사하므로 **다시 인코딩하지
 * 않는다** (ffmpeg 을 한 번 더 돌리면 1분이 더 든다).
 *
 * 앱이 이걸 화면 히어로로 쓴다 — 영상은 눌렀을 때 튼다.
 */
export async function render({ url, out, poster, work, onLog = () => {} }) {
  const dir = work || path.join(process.env.TMPDIR || '/tmp', `reels-${Date.now()}`);
  try {
    const shot = await capture({ url, dir, onLog });
    await encode({ ...shot, out });
    if (poster) {
      const last = `f${String(shot.count - 1).padStart(6, '0')}.jpg`;
      await copyFile(path.join(dir, last), poster);
    }
    onLog(`구웠다 → ${out}`);
    return out;
  } finally {
    if (!work) await rm(dir, { recursive: true, force: true });
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const a = args(process.argv.slice(2));
  const base = a.client || process.env.CLIENT_BASE_URL || 'http://localhost:3000';
  const url = a.url || `${base}/tv/${encodeURIComponent(a.token)}/reels`;
  const log = (m) => console.log(m);
  if (a.frames) {
    await capture({ url, dir: a.frames, onLog: log }).then((r) =>
      writeFile(path.join(a.frames, 'stamps.json'), JSON.stringify(r.stamps)),
    );
  } else {
    const out = a.out || 'reels.mp4';
    await render({ url, out, poster: a.poster || out.replace(/\.mp4$/, '.jpg'),
                   work: a.work, onLog: log });
  }
}
