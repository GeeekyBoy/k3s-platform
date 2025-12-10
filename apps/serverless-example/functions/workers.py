"""
Queue-triggered Worker Functions

These functions process messages from Valkey queues and scale based
on queue depth. They scale to zero when no messages are pending.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from k3sfn import serverless, queue_trigger, Context

logger = logging.getLogger(__name__)


@serverless(
    memory="512Mi",
    cpu="200m",
    min_instances=0,
    max_instances=10,
    timeout=60,
)
@queue_trigger(
    queue_name="tasks",
    batch_size=5,
    visibility_timeout=60,
)
async def process_tasks(messages: List[Dict[str, Any]], context: Context) -> None:
    """
    Process tasks from the queue.

    Scales based on queue:tasks list length in Valkey.
    Processes up to 5 messages at a time for efficiency.
    """
    logger.info(f"Processing {len(messages)} tasks (invocation: {context.invocation_id})")

    for msg in messages:
        task_id = msg.get("id", "unknown")
        task_type = msg.get("type", "default")
        payload = msg.get("payload", {})

        logger.info(f"Processing task {task_id} of type {task_type}")

        # Simulate processing
        await asyncio.sleep(0.5)

        logger.info(f"Task {task_id} completed")


@serverless(
    memory="1Gi",  # More memory for email processing
    cpu="250m",
    min_instances=0,
    max_instances=5,
    timeout=120,
)
@queue_trigger(
    queue_name="emails",
    batch_size=1,  # Process one email at a time for reliability
    visibility_timeout=120,
)
async def send_emails(messages: List[Dict[str, Any]], context: Context) -> None:
    """
    Send emails from the queue.

    Lower batch size for reliability - one email at a time.
    Higher timeout for external API calls.
    """
    for msg in messages:
        email_to = msg.get("to", "")
        subject = msg.get("subject", "")
        body = msg.get("body", "")

        logger.info(f"Sending email to {email_to}: {subject}")

        # Simulate email sending
        await asyncio.sleep(1)

        logger.info(f"Email sent to {email_to}")


@serverless(
    memory="2Gi",  # High memory for image processing
    cpu="1",  # Full CPU core
    min_instances=0,
    max_instances=3,  # Limited due to resource intensity
    timeout=300,
)
@queue_trigger(
    queue_name="images",
    batch_size=1,
    visibility_timeout=300,
)
async def process_images(messages: List[Dict[str, Any]], context: Context) -> None:
    """
    Process images from the queue.

    High resource allocation for image processing.
    Limited instances due to CPU/memory intensity.
    Long timeout for large image processing.
    """
    for msg in messages:
        image_url = msg.get("url", "")
        operation = msg.get("operation", "resize")

        logger.info(f"Processing image: {image_url} (operation: {operation})")

        # Simulate image processing
        await asyncio.sleep(2)

        logger.info(f"Image processed: {image_url}")
