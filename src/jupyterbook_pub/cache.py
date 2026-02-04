"""
Various caching utilities.

Since we serve a lot of static files, we will rely heavily on caching
to make sure we can serve a ton of users very cheaply.
"""

import json
import hashlib
from repoproviders.resolvers.base import MaybeExists, Repo
from repoproviders.resolvers.serialize import to_dict
from base64 import urlsafe_b64encode


def make_rendered_cache_key(repo: Repo, base_url: str) -> str:
    answer = MaybeExists(repo)
    key = {"answer": to_dict(answer), "base_url": base_url}
    return urlsafe_b64encode(hashlib.sha256(json.dumps(key).encode()).digest()).decode()


def make_checkout_cache_key(repo: Repo) -> str:
    answer = MaybeExists(repo)
    return urlsafe_b64encode(hashlib.sha256(json.dumps(to_dict(answer)).encode()).digest()).decode()
