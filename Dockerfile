FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# OpenCascade (cadquery-ocp) and VTK link against libGL; python:3.12-slim omits it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Streamlit's documented readiness probe. start-period covers the first CAD import.
HEALTHCHECK --interval=30s --timeout=6s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=5).read().strip()==b'ok' else 1)"

# XSRF/CORS stay on by default. A reverse proxy (Cloudflare Container) sets
# ENABLE_XSRF=false / ENABLE_CORS=false because the forwarded Host and Origin differ.
CMD ["sh", "-c", "python -m src.startup && exec streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT} --server.headless=true --server.enableXsrfProtection=${ENABLE_XSRF:-true} --server.enableCORS=${ENABLE_CORS:-true}"]
