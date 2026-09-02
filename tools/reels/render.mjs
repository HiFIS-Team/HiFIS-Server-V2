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
import { createWriteStream } from 'node:fs';
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
 * 게임 한 판을 찍어 프레임으로 남긴다.
 *
 * 프레임은 **크롬이 그리는 대로** 온다(가변 간격). 몇 시에 온 프레임인지를
 * 같이 남겨 두었다가 ffmpeg 이 고정 30fps 로 다시 깐다 — 안 그러면 크롬이
 * 잠깐 버벅인 자리가 영상에서 빨라진다.
 */
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
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: READY_MS });

    // 추첨을 받아오고 게임 채비가 끝날 때까지
    await page.waitForFunction(() => window.__reels?.ready === true, null, { timeout: READY_MS });
    onLog('준비됨');

    const cdp = await page.context().newCDPSession(page);
    /** 프레임이 온 시각(초) — 길이를 여기서 잰다 */
    const stamps = [];
    let writing = Promise.resolve();
    let n = 0;

    cdp.on('Page.screencastFrame', ({ data, sessionId, metadata }) => {
      const i = n++;
      stamps.push(metadata.timestamp);
      // **받는 순서대로 디스크에 쓴다** — 다 들고 있으면 50초짜리가 수백 MB 다
      writing = writing.then(() =>
        writeFile(path.join(dir, `f${String(i).padStart(6, '0')}.jpg`), Buffer.from(data, 'base64')),
      );
      cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
    });

    await cdp.send('Page.startScreencast', {
      format: 'jpeg',
      quality: 92,
      maxWidth: WIDTH,
      maxHeight: HEIGHT,
      everyNthFrame: 1,
    });

    // 여기서부터 게임이 굴러간다
    await page.evaluate(() => window.__reelsStart?.());
    const t0 = Date.now();

    while (Date.now() - t0 < MAX_SEC * 1000) {
      if (await page.evaluate(() => window.__reels?.done === true)) break;
      await page.waitForTimeout(200);
    }
    const secs = (Date.now() - t0) / 1000;

    await cdp.send('Page.stopScreencast').catch(() => {});
    await writing;
    onLog(`프레임 ${n}장 · ${secs.toFixed(1)}초 · 평균 ${(n / secs).toFixed(1)}fps`);
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
