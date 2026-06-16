import threading

from opensearchpy import OpenSearch

from indexer.config import os_settings

_client: OpenSearch | None = None
_lock = threading.Lock()


def get_opensearch_client() -> OpenSearch:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = OpenSearch(
                    hosts=[{"host": os_settings.host, "port": os_settings.port}],
                    http_auth=(os_settings.username, os_settings.password),
                    use_ssl=True,
                    verify_certs=os_settings.verify_certs,
                    ssl_show_warn=False,
                )
    return _client
