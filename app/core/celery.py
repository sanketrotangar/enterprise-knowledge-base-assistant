# Celery Application Configuration
# ----------------------------------
# Responsibilities:
# - Initialize Celery app with Redis broker/backend
# - Configure task serialization, timeouts, and retry policies
# - Auto-discover tasks from feature modules (e.g. app.features.documents)
#
# Configuration:
# - Broker: Redis (message queue for task dispatch)
# - Backend: Redis (stores task results and state)
# - Serializer: JSON (for cross-language compatibility)
# - Task timeout: 5 minutes (hard limit)
# - Soft timeout: 4 minutes (raises SoftTimeLimitExceeded)
#
# Usage:
#   celery -A app.core.celery:celery_app worker --loglevel=info
