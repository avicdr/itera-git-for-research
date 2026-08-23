FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY researchgit ./researchgit
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "researchgit.main:app", "--host", "0.0.0.0", "--port", "8000"]
