# Deployment - Docker & Production Setup

Complete guide for deploying the Deen backend to production using Docker and EC2.

## Table of Contents

- [Overview](#overview)
- [Docker Setup](#docker-setup)
- [Environment Configuration](#environment-configuration)
- [EC2 Deployment](#ec2-deployment)
- [Database Setup](#database-setup)
- [Monitoring & Logging](#monitoring--logging)
- [Troubleshooting](#troubleshooting)

## Overview

### Deployment Architecture

```mermaid
graph TB
    Internet[Internet] --> Caddy[Caddy Reverse Proxy<br/>:80, :443]
    Caddy --> Backend[FastAPI Backend<br/>:8000]
    Backend --> PostgreSQL[(PostgreSQL RDS)]
    Backend --> Redis[(Redis)]
    Backend --> Pinecone[(Pinecone Vector DB)]
    Backend --> Anthropic[Anthropic API]
    Backend --> Cognito[AWS Cognito]
```

### Components

- **Application**: FastAPI in Docker container
- **Reverse Proxy**: Caddy for HTTPS termination
- **Database**: PostgreSQL (RDS recommended)
- **Cache**: Redis (ElastiCache or self-hosted)
- **Vector DB**: Pinecone (SaaS)
- **Authentication**: AWS Cognito
- **LLM**: Anthropic Claude API

## Docker Setup

### Dockerfile

**File**: `Dockerfile`

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run with gunicorn for production
CMD ["gunicorn", "main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

### Docker Compose

**File**: `docker-compose.yml`

```yaml
version: '3.8'

services:
  backend:
    build: .
    container_name: deen-backend
    ports:
      - "8000:8000"
    environment:
      - ENV=production
    env_file:
      - .env
    restart: unless-stopped
    depends_on:
      - caddy
    networks:
      - deen-network

  caddy:
    image: caddy:2
    container_name: deen-caddy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    restart: unless-stopped
    networks:
      - deen-network

volumes:
  caddy_data:
  caddy_config:

networks:
  deen-network:
    driver: bridge
```

### Caddy Configuration

**File**: `caddy/Caddyfile`

```
# Production configuration
your-domain.com {
    reverse_proxy backend:8000
    
    # Enable gzip compression
    encode gzip
    
    # Security headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        X-XSS-Protection "1; mode=block"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
    
    # Logs
    log {
        output file /var/log/caddy/access.log
    }
}

# Development configuration (optional)
:80 {
    reverse_proxy backend:8000
}
```

## Environment Configuration

### Production .env File

Create `.env` file with production values:

```bash
# Environment
ENV=production

# Anthropic Configuration
ANTHROPIC_API_KEY=your_production_key
LARGE_LLM=claude-sonnet-4-6
SMALL_LLM=claude-haiku-4-5-20251001

# Pinecone Configuration
PINECONE_API_KEY=your_production_key
DEEN_DENSE_INDEX_NAME=deen-prod-dense
DEEN_SPARSE_INDEX_NAME=deen-prod-sparse
DENSE_RESULT_WEIGHT=0.8
SPARSE_RESULT_WEIGHT=0.2
REFERENCE_FETCH_COUNT=10

# Redis Configuration (ElastiCache or self-hosted)
REDIS_URL=redis://your-redis-host:6379/0
REDIS_KEY_PREFIX=prod:chat
REDIS_TTL_SECONDS=12000
REDIS_MAX_MESSAGES=30

# Database Configuration (RDS)
DATABASE_URL=postgresql://user:password@your-rds-endpoint:5432/deen
DB_HOST=your-rds-endpoint.region.rds.amazonaws.com
DB_PORT=5432
DB_NAME=deen
DB_USER=your_db_user
DB_PASSWORD=your_secure_password

# AWS Cognito
COGNITO_REGION=us-east-1
COGNITO_POOL_ID=us-east-1_PRODUCTION

# CORS Configuration
CORS_ALLOW_ORIGINS=https://your-frontend.com,https://www.your-frontend.com
```

### Security Best Practices

1. **Never commit .env to git** - Add to `.gitignore`
2. **Use strong passwords** - Generate random secure passwords
3. **Rotate secrets regularly** - Update API keys periodically
4. **Use IAM roles** - For AWS services (avoid access keys)
5. **Restrict CORS origins** - Only allow your frontend domain

## EC2 Deployment

### EC2 Instance Setup

**Recommended Instance**:
- Type: `t3.medium` or larger
- vCPUs: 2+
- RAM: 4GB+
- Storage: 20GB+ SSD

**Security Group Rules**:
- Port 22: SSH (your IP only)
- Port 80: HTTP (0.0.0.0/0)
- Port 443: HTTPS (0.0.0.0/0)

### Initial Setup

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@ec2-ip-address

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo apt install docker-compose -y

# Clone repository
cd ~
git clone https://github.com/your-repo/deen-backend.git
cd deen-backend

# Create .env file
nano .env
# Paste production environment variables

# Build and start services
docker compose build --no-cache
docker compose up -d

# Check logs
docker logs --tail=200 deen-backend
docker logs --tail=200 deen-caddy
```

### Deployment Commands

**Quick Reference** (canonical copy in README — keep the two in sync):

```bash
# Navigate to project
cd ~/deen-backend

# Pull latest code
git pull

# Stop services
docker compose down

# Optional: Clean up (recommended on small instances)
docker system prune -af

# Rebuild with no cache
docker compose build --no-cache

# Run database migrations BEFORE starting the new version — new code must
# never race a missing table (e.g. DEE-67's reference_translations).
# Throwaway container from the freshly built image; no-op when there are
# no new migrations.
docker compose run --rm api alembic upgrade head

# Start services
docker compose up -d

# Check logs
docker logs --tail=200 deen-backend
docker logs --tail=200 deen-caddy

# Check service status
docker ps
```

### Auto-restart on Failure

Docker Compose `restart: unless-stopped` ensures:
- Services restart on crash
- Services start on EC2 reboot
- Manual stops remain stopped

### Health Monitoring

```bash
# Check if services are running
docker ps

# Check backend health
curl http://localhost:8000/health

# Check database connectivity
curl http://localhost:8000/_debug/db

# View real-time logs
docker logs -f deen-backend
```

## Database Setup

### PostgreSQL RDS

**Recommended Settings**:
- Instance class: `db.t3.small` or larger
- Storage: 20GB GP2 (auto-scaling enabled)
- Multi-AZ: Yes (for production)
- Public access: No (use VPC)
- Backup retention: 7 days

**Security Group**:
- Port 5432: PostgreSQL (from EC2 security group only)

**Connection**:
```bash
DATABASE_URL=postgresql://user:password@rds-endpoint:5432/deen
```

### Running Migrations

Migrations are part of every deploy (see Deployment Commands above) and must
run **before** the new app version starts serving:

```bash
# Standard: throwaway container from the freshly built image
docker compose run --rm api alembic upgrade head
```

To run them against an already-running container (ad-hoc, e.g. catching up
after a deploy that skipped the step):

```bash
docker exec -it deen-backend alembic upgrade head
```

### Database Backups

**RDS Automated Backups**:
- Enabled by default
- Retention: 7 days (configurable)
- Daily snapshots

**Manual Backup**:
```bash
# Create snapshot from AWS Console or CLI
aws rds create-db-snapshot \
  --db-instance-identifier your-db \
  --db-snapshot-identifier manual-backup-2024-01-15
```

## Monitoring & Logging

### Application Logs

```bash
# View backend logs
docker logs deen-backend

# Follow logs in real-time
docker logs -f deen-backend

# View last 200 lines
docker logs --tail=200 deen-backend

# View Caddy logs
docker logs deen-caddy
```

### Log Rotation

Docker handles log rotation automatically, but you can configure:

```yaml
# In docker-compose.yml
services:
  backend:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### CloudWatch Integration

For production monitoring, consider AWS CloudWatch:

```bash
# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/linux/amd64/latest/AmazonCloudWatchAgent.zip
unzip AmazonCloudWatchAgent.zip
sudo ./install.sh

# Configure agent to ship Docker logs
```

### Monitoring Checklist

- [ ] Application is responding (health endpoint)
- [ ] Database connectivity working
- [ ] No error spikes in logs
- [ ] Memory/CPU usage reasonable
- [ ] Disk space available

## SSL/TLS Configuration

### Automatic HTTPS with Caddy

Caddy automatically:
1. Obtains SSL certificates from Let's Encrypt
2. Renews certificates before expiration
3. Redirects HTTP to HTTPS
4. Handles HTTPS termination

**Requirements**:
- Domain pointing to EC2 public IP
- Ports 80 and 443 open
- Proper DNS configuration

### Manual Certificate Renewal

Caddy handles this automatically, but if needed:

```bash
docker exec -it deen-caddy caddy reload --config /etc/caddy/Caddyfile
```

## Performance Optimization

### Gunicorn Workers

**Current Configuration**:
```dockerfile
CMD ["gunicorn", "main:app", \
     "--workers", "4", \              # Number of worker processes
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120"]              # Request timeout
```

**Worker Count Formula**:
```
workers = (2 * CPU_CORES) + 1
```

For 2 vCPU instance: 5 workers
For 4 vCPU instance: 9 workers

### Database Connection Pooling

**Current Settings** (in `db/session.py`):
```python
engine = create_engine(
    DATABASE_URL,
    pool_size=10,          # Base pool size
    max_overflow=20,       # Additional connections if needed
    pool_recycle=3600      # Recycle connections hourly
)
```

Adjust based on:
- Number of Gunicorn workers
- Expected concurrent requests
- Database connection limits

### Caching Strategy

**Redis Configuration**:
- TTL: 12000 seconds (3.3 hours) for chat history
- Max messages: 30 per session
- Automatic cleanup via TTL

**Optimize**:
- Increase TTL for less frequent cleanup
- Decrease max messages for memory savings
- Add caching for frequently accessed data

## Scaling Strategies

### Horizontal Scaling

**Load Balancer Setup**:
1. Create Application Load Balancer (ALB)
2. Add multiple EC2 instances
3. Configure health checks
4. Update DNS to point to ALB

**Session Persistence**:
- Redis handles session storage
- Any backend instance can serve request
- No sticky sessions needed

### Vertical Scaling

**Increase Instance Size**:
- Larger EC2 instance (more CPU/RAM)
- Increase Gunicorn workers
- Increase database connection pool

### Database Scaling

**RDS Scaling**:
- Increase instance class (vertical)
- Add read replicas (horizontal reads)
- Enable Multi-AZ (high availability)

## Troubleshooting

### Service Won't Start

```bash
# Check container status
docker ps -a

# View startup logs
docker logs deen-backend

# Check configuration
docker exec -it deen-backend env | grep DATABASE

# Restart service
docker compose restart backend
```

### Database Connection Issues

```bash
# Test connectivity from container
docker exec -it deen-backend python -c "
from db.session import engine
with engine.connect() as conn:
    result = conn.execute(text('SELECT 1'))
    print('Database connected!')
"

# Check environment variables
docker exec -it deen-backend env | grep DB_
```

### Memory Issues

```bash
# Check memory usage
docker stats

# If out of memory, prune unused resources
docker system prune -af

# Reduce Gunicorn workers
# Edit Dockerfile, rebuild, restart
```

### SSL Certificate Issues

```bash
# Check Caddy logs
docker logs deen-caddy

# Verify domain DNS
nslookup your-domain.com

# Reload Caddy config
docker exec -it deen-caddy caddy reload --config /etc/caddy/Caddyfile
```

## Rollback Strategy

### Quick Rollback

```bash
# If new deployment has issues

# 1. Check current git commit
git log -1

# 2. Revert to previous commit
git reset --hard PREVIOUS_COMMIT_HASH

# 3. Rebuild and restart
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Database Rollback

```bash
# Revert last migration
docker exec -it deen-backend alembic downgrade -1

# Or revert to specific version
docker exec -it deen-backend alembic downgrade MIGRATION_ID
```

## Maintenance

### Regular Tasks

**Weekly**:
- Check logs for errors
- Monitor disk space
- Review application performance

**Monthly**:
- Update dependencies
- Review and rotate secrets
- Check for security updates
- Database backups verification

**Quarterly**:
- Review and optimize database queries
- Analyze usage patterns
- Plan capacity upgrades
- Security audit

### Updating Dependencies

```bash
# Update requirements.txt with new versions
pip list --outdated

# Update requirements.txt
nano requirements.txt

# Rebuild Docker image
docker compose build --no-cache

# Test in development first!
# Then deploy to production
```

## Cost Optimization

### AWS Cost Considerations

**EC2**:
- Use t3 instances (burstable, cheaper)
- Consider Reserved Instances for 1-3 year commitment
- Use Spot Instances for non-critical workloads

**RDS**:
- Right-size instance based on usage
- Use Aurora Serverless for variable workloads
- Enable storage auto-scaling

**Data Transfer**:
- Minimize cross-region transfers
- Use CloudFront for static assets

**Redis**:
- Consider self-hosted on EC2 vs ElastiCache
- Right-size instance

## See Also

- [Architecture Documentation](ARCHITECTURE.md) - System design
- [Database Documentation](DATABASE.md) - Database setup
- [Authentication Documentation](AUTHENTICATION.md) - AWS Cognito setup
- [API Reference](API_REFERENCE.md) - API endpoints
