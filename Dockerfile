FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

ENV HOST=0.0.0.0
ENV PORT=8080
ENV FETCH_LIVE=1
ENV ALLOW_FIXTURE_POLL=0
EXPOSE 8080

CMD ["python", "-m", "app"]
