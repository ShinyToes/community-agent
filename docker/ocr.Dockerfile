FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim && rm -rf /var/lib/apt/lists/*
USER 65534:65534
ENTRYPOINT ["tesseract"]
