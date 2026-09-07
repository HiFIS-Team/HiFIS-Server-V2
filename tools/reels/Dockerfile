# 추첨 게임 영상을 찍는 일꾼 — 헤드리스 크롬 + ffmpeg
#
# **API 이미지와 따로 둔다.** 크롬이 1.5GB 라 API 에 얹으면 배포할 때마다
# 그만큼을 다시 받는다. 이건 한 달에 세 번 도는 잡이라 따로 두는 게 맞다.
#
# 태그를 playwright 버전에 맞춘다 — 이미지 안 브라우저와 `package.json` 의
# playwright 가 어긋나면 뜰 때 '브라우저를 설치하라' 고 죽는다.
FROM mcr.microsoft.com/playwright:v1.56.1-noble

# ffmpeg — playwright 가 들고 있는 것은 VP8 만 있어서 H.264 를 못 굽는다
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json* ./
# `--omit=dev` — `ffmpeg-static` 은 맥에서 재 볼 때만 쓴다 (여기는 apt ffmpeg)
RUN npm install --omit=dev --no-audit --no-fund
COPY render.mjs server.mjs ./

ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "server.mjs"]
