"""
Example Serverless Functions

This module demonstrates how to use the k3sfn SDK to create
Firebase-style serverless functions that deploy to Kubernetes
with automatic scale-to-zero.
"""

from .api import *
from .workers import *
from .scheduled import *
