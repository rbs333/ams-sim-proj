FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir httpx

# Copy simulation scripts
COPY load_runner.py orchestrator.py ./

# Create results directory
RUN mkdir -p /results

# Default command runs the load runner
ENTRYPOINT ["python"]
CMD ["load_runner.py"]

