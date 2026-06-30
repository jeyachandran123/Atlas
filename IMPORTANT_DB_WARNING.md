# ⚠️ CRITICAL: Database Data Preservation

## DO NOT RUN THESE COMMANDS:
```bash
docker-compose down              # This REMOVES containers AND can lose data
docker-compose down -v          # This DELETES volumes AND LOSES ALL DATA
docker volume rm postgres_data  # This PERMANENTLY DELETES database
```

## SAFE COMMANDS:
```bash
# Restart services safely (preserves data)
docker-compose restart

# Restart specific service
docker-compose restart api
docker-compose restart worker

# Stop without removing
docker-compose stop

# Start again
docker-compose up -d

# View logs
docker-compose logs -f api
docker-compose logs -f worker
```

## Database Backup (Run before demo):
```bash
# Backup database
docker exec aic_postgres pg_dump -U postgres ai_coding_assistant > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore if needed
docker exec -i aic_postgres psql -U postgres ai_coding_assistant < backup_YYYYMMDD_HHMMSS.sql
```

## What Happened:
- Running `docker-compose down api` recreated the postgres container
- This created a fresh database with no data
- All conversations and messages were lost

## Prevention:
- Always use `docker-compose restart` instead of `down/up`
- Backup database before any infrastructure changes
- Use docker volumes (already configured)
