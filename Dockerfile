# Docker deployment for local Telegram Bot API. Existing Python runtime remains unchanged until manually switched.
FROM debian:bookworm-slim AS telegram-builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends git cmake g++ make gperf libssl-dev zlib1g-dev libcurl4-openssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --recursive https://github.com/tdlib/telegram-bot-api.git /src/telegram-bot-api \
 && cmake -S /src/telegram-bot-api -B /build -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /build --target telegram-bot-api -j 2

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libssl3 libcurl4 ca-certificates ffmpeg tini patch && rm -rf /var/lib/apt/lists/*
COPY --from=telegram-builder /build/telegram-bot-api /usr/local/bin/telegram-bot-api
WORKDIR /app
COPY . .
# The connected GitHub writer has a 393 KiB single-blob limit. Keep the
# production source tree intact and apply the reviewed Veo delta in-image.
RUN patch --batch --forward -p1 < /app/ops/main_veo.patch
RUN patch --batch --forward -p1 < /app/ops/main_veo_start_guard.patch
RUN patch --batch --forward -p1 < /app/ops/main_veo_recovery.patch
RUN patch --batch --forward -p1 < /app/ops/main_start_welcome.patch
RUN pip install --no-cache-dir -r requirements.txt
RUN chmod +x /app/ops/start_telegram_local.sh
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["/app/ops/start_telegram_local.sh"]
