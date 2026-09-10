FROM python:3.12-slim
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
COPY experiments/v265_prior/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY experiments /app/experiments
ARG CODE_COMMIT
ENV V265_CODE_COMMIT=$CODE_COMMIT
CMD ["python", "-m", "experiments.v265_selfhost.dryrun", "/results/run", "--require-2gib"]
