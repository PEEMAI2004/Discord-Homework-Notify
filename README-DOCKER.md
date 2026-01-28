# Docker Deployment Guide

This guide explains how to run the Discord Homework Notify bot using Docker and Docker Compose.

## Prerequisites

- Docker installed ([Get Docker](https://docs.docker.com/get-docker/))
- Docker Compose installed (included with Docker Desktop)
- `.env` file configured (see `.env.sample`)
- Google credentials JSON file

## Quick Start

### 1. Configure Environment Variables

First, make sure your `.env` file is properly configured. You need to update the `GOOGLE_CREDENTIALS_PATH` to point to the container path:

```bash
# In your .env file, set:
GOOGLE_CREDENTIALS_PATH=/app/credentials/google_credentials.json
```

### 2. Update docker-compose.yml

Edit `docker-compose.yml` and update the volume mount to point to your actual Google credentials file:

```yaml
volumes:
  - /path/to/your/google_credentials.json:/app/credentials/google_credentials.json:ro
```

Replace `/path/to/your/google_credentials.json` with the actual path to your credentials file on your host machine.

### 3. Build and Run

```bash
# Build the Docker image
docker-compose build

# Start the bot
docker-compose up -d

# View logs
docker-compose logs -f
```

## Useful Commands

### Start the bot
```bash
docker-compose up -d
```

### Stop the bot
```bash
docker-compose down
```

### View logs
```bash
docker-compose logs -f discord-bot
```

### Restart the bot
```bash
docker-compose restart
```

### Rebuild after code changes
```bash
docker-compose up -d --build
```

## Manual Docker Commands (without Docker Compose)

If you prefer to use Docker directly without Compose:

### Build the image
```bash
docker build -t discord-homework-bot .
```

### Run the container
```bash
docker run -d \
  --name discord-homework-bot \
  --restart unless-stopped \
  --env-file .env \
  -v /path/to/google_credentials.json:/app/credentials/google_credentials.json:ro \
  discord-homework-bot
```

### View logs
```bash
docker logs -f discord-homework-bot
```

## Troubleshooting

### Bot doesn't start
1. Check logs: `docker-compose logs discord-bot`
2. Verify `.env` file has all required variables
3. Ensure Google credentials file path is correct

### Permission errors with credentials file
Make sure the credentials file is readable:
```bash
chmod 644 /path/to/google_credentials.json
```

### Bot can't connect to Discord
- Verify `DISCORD_TOKEN` in `.env` is correct
- Check firewall settings

### Timezone issues
The container is configured to use `Asia/Bangkok` timezone by default. To change it, update the `TZ` environment variable in `docker-compose.yml`.

## Environment Variables

All environment variables should be set in your `.env` file. See `.env.sample` for the complete list of required variables.

**Important:** When running in Docker, set `GOOGLE_CREDENTIALS_PATH=/app/credentials/google_credentials.json` since this is where the credentials will be mounted inside the container.

## Production Deployment

For production deployments:

1. Use secrets management instead of `.env` file
2. Set up proper monitoring and alerting
3. Configure log aggregation
4. Use a container orchestration platform like Kubernetes for better scaling
5. Set up automatic restarts and health checks

## Updates

To update the bot with new code:

```bash
git pull
docker-compose up -d --build
```

This will rebuild the image with the latest code and restart the container.
