FROM python:3.12-slim
WORKDIR /app

# Build with:  docker build --build-arg WITH_FORM=1 -t smart-coach .   to include squat form analysis
ARG WITH_FORM=0
RUN if [ "$WITH_FORM" = "1" ]; then apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*; fi

COPY requirements.txt requirements-form.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$WITH_FORM" = "1" ]; then pip install --no-cache-dir -r requirements-form.txt; fi
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
