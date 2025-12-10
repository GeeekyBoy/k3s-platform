"""
Schedule-triggered Functions

These functions run on a cron schedule. They're implemented as
Kubernetes CronJobs rather than long-running deployments.
"""

import logging
from datetime import datetime
from typing import Any

from k3sfn import serverless, schedule_trigger, Context

logger = logging.getLogger(__name__)


@serverless(
    memory="256Mi",
    cpu="100m",
    timeout=300,
)
@schedule_trigger(
    cron="0 * * * *",  # Every hour at minute 0
    timezone="UTC",
)
async def hourly_metrics(context: Context) -> None:
    """
    Collect hourly metrics.

    Runs every hour to aggregate metrics and store results.
    Implemented as a CronJob.
    """
    logger.info(f"Collecting hourly metrics at {context.timestamp}")

    # Simulate metrics collection
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "cpu_usage": 45.2,
        "memory_usage": 62.8,
        "request_count": 1234,
    }

    logger.info(f"Metrics collected: {metrics}")


@serverless(
    memory="512Mi",
    cpu="200m",
    timeout=600,
)
@schedule_trigger(
    cron="0 0 * * *",  # Every day at midnight
    timezone="UTC",
)
async def daily_cleanup(context: Context) -> None:
    """
    Daily cleanup job.

    Runs at midnight UTC to clean up old data,
    expired sessions, and temporary files.
    """
    logger.info(f"Starting daily cleanup at {context.timestamp}")

    # Simulate cleanup operations
    cleaned = {
        "expired_sessions": 42,
        "temp_files": 128,
        "old_logs": 15,
    }

    logger.info(f"Cleanup complete: {cleaned}")


@serverless(
    memory="1Gi",
    cpu="500m",
    timeout=3600,  # 1 hour timeout for reports
)
@schedule_trigger(
    cron="0 6 * * 1",  # Every Monday at 6 AM
    timezone="America/New_York",
)
async def weekly_report(context: Context) -> None:
    """
    Generate weekly reports.

    Runs every Monday morning to generate and send weekly reports.
    Higher resources and timeout for report generation.
    """
    logger.info(f"Generating weekly report at {context.timestamp}")

    # Simulate report generation
    report = {
        "period": "weekly",
        "generated_at": datetime.utcnow().isoformat(),
        "total_users": 5432,
        "active_users": 3210,
        "revenue": 12345.67,
    }

    logger.info(f"Weekly report generated: {report}")
