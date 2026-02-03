"""
Simple file-based JSON cache in .tmp/cache/.
Each entry is a JSON file keyed by hash of the cache key.
"""

import os
import json
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".tmp", "cache")


class FileCache:
    """File-based JSON cache with TTL support."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    def _key_to_path(self, key):
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"{h}.json")

    def get(self, key, ttl=86400):
        """Get cached value if it exists and hasn't expired. ttl in seconds."""
        path = self._key_to_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                entry = json.load(f)
            if time.time() - entry["timestamp"] > ttl:
                os.remove(path)
                return None
            return entry["data"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def set(self, key, data):
        """Store value with current timestamp."""
        path = self._key_to_path(key)
        try:
            with open(path, "w") as f:
                json.dump({"timestamp": time.time(), "data": data}, f)
        except OSError as e:
            logger.error(f"Cache write failed: {e}")

    def invalidate(self, key):
        """Remove a specific cache entry."""
        path = self._key_to_path(key)
        if os.path.exists(path):
            os.remove(path)

    def clear(self):
        """Remove all cached entries."""
        for fname in os.listdir(self.cache_dir):
            if fname.endswith(".json"):
                os.remove(os.path.join(self.cache_dir, fname))

    def get_size(self):
        """Return number of cached entries."""
        return len([f for f in os.listdir(self.cache_dir) if f.endswith(".json")])
