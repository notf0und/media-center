FROM python:3.11-slim

WORKDIR /app

# Install mempalace, Flask, and sudo
RUN apt-get update && apt-get install -y --no-install-recommends sudo && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir mempalace flask

# Allow mempalace user to run commands without password
RUN echo "mempalace ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/mempalace && \
    chmod 0440 /etc/sudoers.d/mempalace

# Copy the Flask wrapper app and static files
COPY app.py /app/app.py
COPY static/ /app/static/
COPY entrypoint.sh /app/entrypoint.sh

# Create data directory
RUN mkdir -p /data/palace && chmod +x /app/entrypoint.sh

EXPOSE 5000

ENV PALACE_DIR=/data/palace

CMD ["/app/entrypoint.sh"]
