FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ライブラリを先に入れる（app.py だけ変えたときはこの層がキャッシュされ、ビルドが速い）
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .
COPY .streamlit .streamlit

# root では動かさない
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8501

# ヘルスチェックは ALB のターゲットグループ（/_stcore/health）で行う
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
