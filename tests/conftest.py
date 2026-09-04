"""Hermetic test configuration for external service boundaries."""

import os


# Production validates payment configuration at import time. Tests replace every
# payment call that could reach the network, so deterministic placeholder values
# keep collection independent of a developer's untracked .env file.
os.environ["RAZORPAY_KEY_ID"] = "test_key"
os.environ["RAZORPAY_KEY_SECRET"] = "test_secret"
