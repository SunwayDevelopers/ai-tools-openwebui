"""
NOTE: This vector database integration is community-supported and maintained on a best-effort basis.
"""

import logging
from typing import Optional
from urllib.parse import urlparse

from open_webui.config import (
    QDRANT_API_KEY,
    QDRANT_COLLECTION_PREFIX,
    QDRANT_GRPC_PORT,
    QDRANT_HNSW_M,
    QDRANT_ON_DISK,
    QDRANT_PREFER_GRPC,
    QDRANT_TIMEOUT,
    QDRANT_URI,
)
from open_webui.env import ENABLE_MULTI_TENANCY
from open_webui.retrieval.vector.main import (
    GetResult,
    SearchResult,
    VectorDBBase,
    VectorItem,
)
from qdrant_client import QdrantClient as Qclient
from qdrant_client.http.models import PointStruct
from qdrant_client.models import models

NO_LIMIT = 999999999

log = logging.getLogger(__name__)


class QdrantClient(VectorDBBase):
    def __init__(self):
        # Per-tenant underlying clients (multi-tenancy), keyed by (url, api_key).
        self._tenant_clients: dict = {}
        self.collection_prefix = QDRANT_COLLECTION_PREFIX
        self.QDRANT_URI = QDRANT_URI
        self.QDRANT_API_KEY = QDRANT_API_KEY
        self.QDRANT_ON_DISK = QDRANT_ON_DISK
        self.PREFER_GRPC = QDRANT_PREFER_GRPC
        self.GRPC_PORT = QDRANT_GRPC_PORT
        self.QDRANT_TIMEOUT = QDRANT_TIMEOUT
        self.QDRANT_HNSW_M = QDRANT_HNSW_M

        if not self.QDRANT_URI:
            self.client = None
            return

        # Unified handling for either scheme
        parsed = urlparse(self.QDRANT_URI)
        host = parsed.hostname or self.QDRANT_URI
        http_port = parsed.port or 6333  # default REST port

        if self.PREFER_GRPC:
            self.client = Qclient(
                host=host,
                port=http_port,
                grpc_port=self.GRPC_PORT,
                prefer_grpc=self.PREFER_GRPC,
                api_key=self.QDRANT_API_KEY,
                timeout=self.QDRANT_TIMEOUT,
            )
        else:
            self.client = Qclient(
                url=self.QDRANT_URI,
                api_key=self.QDRANT_API_KEY,
                timeout=QDRANT_TIMEOUT,
            )

    # ── Multi-tenancy: per-tenant collection prefix + underlying client ──
    #
    # Single chokepoint. Every method composes the physical collection name via
    # _physical_name() and talks to the connection via _qc(); with multi-tenancy
    # off both resolve to today's behaviour (the shared prefix + the single
    # client built in __init__). With it on, they read the tenant's brokered
    # Qdrant prefix/url/api_key from the request ContextVar and FAIL CLOSED if it
    # is absent — so no query can ever run without a tenant scope.

    def _collection_prefix(self) -> str:
        if not ENABLE_MULTI_TENANCY:
            return self.collection_prefix
        from open_webui.utils.tenant import TenantContextError, require_tenant_context

        prefix = require_tenant_context().connection.qdrant.collection_prefix
        if not prefix:
            raise TenantContextError('Tenant has no Qdrant collection prefix (fail-closed).')
        return prefix

    def _physical_name(self, collection_name: str) -> str:
        prefix = self._collection_prefix()
        if not prefix:
            return collection_name
        # Tenant prefixes are conventionally supplied with a trailing separator
        # (e.g. 'acme_sales_'); the shared default ('open-webui') is not.
        sep = '' if prefix.endswith('_') else '_'
        return f'{prefix}{sep}{collection_name}'

    def _client_for(self, url: str, api_key: Optional[str]):
        key = (url, api_key or '')
        client = self._tenant_clients.get(key)
        if client is None:
            client = Qclient(url=url, api_key=api_key, timeout=self.QDRANT_TIMEOUT)
            self._tenant_clients[key] = client
        return client

    def _qc(self):
        """Return the underlying qdrant client for the current scope."""
        if not ENABLE_MULTI_TENANCY:
            if self.client is None:
                raise RuntimeError('Qdrant is not configured (QDRANT_URI is unset).')
            return self.client
        from open_webui.utils.tenant import require_tenant_context

        qdrant = require_tenant_context().connection.qdrant
        return self._client_for(qdrant.url, qdrant.api_key)

    def _result_to_get_result(self, points) -> GetResult:
        ids = []
        documents = []
        metadatas = []

        for point in points:
            payload = point.payload
            ids.append(point.id)
            documents.append(payload['text'])
            metadatas.append(payload['metadata'])

        return GetResult(
            **{
                'ids': [ids],
                'documents': [documents],
                'metadatas': [metadatas],
            }
        )

    def _create_collection(self, collection_name: str, dimension: int):
        collection_name_with_prefix = self._physical_name(collection_name)
        self._qc().create_collection(
            collection_name=collection_name_with_prefix,
            vectors_config=models.VectorParams(
                size=dimension,
                distance=models.Distance.COSINE,
                on_disk=self.QDRANT_ON_DISK,
            ),
            hnsw_config=models.HnswConfigDiff(
                m=self.QDRANT_HNSW_M,
            ),
        )

        # Create payload indexes for efficient filtering
        self._qc().create_payload_index(
            collection_name=collection_name_with_prefix,
            field_name='metadata.hash',
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=False,
                on_disk=self.QDRANT_ON_DISK,
            ),
        )
        self._qc().create_payload_index(
            collection_name=collection_name_with_prefix,
            field_name='metadata.file_id',
            field_schema=models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=False,
                on_disk=self.QDRANT_ON_DISK,
            ),
        )
        log.info(f'collection {collection_name_with_prefix} successfully created!')

    def _create_collection_if_not_exists(self, collection_name, dimension):
        if not self.has_collection(collection_name=collection_name):
            self._create_collection(collection_name=collection_name, dimension=dimension)

    def _create_points(self, items: list[VectorItem]):
        return [
            PointStruct(
                id=item['id'],
                vector=item['vector'],
                payload={'text': item['text'], 'metadata': item['metadata']},
            )
            for item in items
        ]

    def has_collection(self, collection_name: str) -> bool:
        return self._qc().collection_exists(self._physical_name(collection_name))

    def delete_collection(self, collection_name: str):
        return self._qc().delete_collection(collection_name=self._physical_name(collection_name))

    def search(
        self,
        collection_name: str,
        vectors: list[list[float | int]],
        filter: Optional[dict] = None,
        limit: int = 10,
    ) -> Optional[SearchResult]:
        # Search for the nearest neighbor items based on the vectors and return 'limit' number of results.
        if limit is None:
            limit = NO_LIMIT  # otherwise qdrant would set limit to 10!

        query_response = self._qc().query_points(
            collection_name=self._physical_name(collection_name),
            query=vectors[0],
            limit=limit,
        )
        get_result = self._result_to_get_result(query_response.points)
        return SearchResult(
            ids=get_result.ids,
            documents=get_result.documents,
            metadatas=get_result.metadatas,
            # qdrant distance is [-1, 1], normalize to [0, 1]
            distances=[[(point.score + 1.0) / 2.0 for point in query_response.points]],
        )

    def query(self, collection_name: str, filter: dict, limit: Optional[int] = None):
        # Construct the filter string for querying
        if not self.has_collection(collection_name):
            return None
        try:
            if limit is None:
                limit = NO_LIMIT  # otherwise qdrant would set limit to 10!

            field_conditions = []
            for key, value in filter.items():
                field_conditions.append(
                    models.FieldCondition(key=f'metadata.{key}', match=models.MatchValue(value=value))
                )

            points = self._qc().scroll(
                collection_name=self._physical_name(collection_name),
                scroll_filter=models.Filter(should=field_conditions),
                limit=limit,
            )
            return self._result_to_get_result(points[0])
        except Exception as e:
            log.exception(f"Error querying a collection '{collection_name}': {e}")
            return None

    def get(self, collection_name: str) -> Optional[GetResult]:
        # Get all the items in the collection.
        points = self._qc().scroll(
            collection_name=self._physical_name(collection_name),
            limit=NO_LIMIT,  # otherwise qdrant would set limit to 10!
        )
        return self._result_to_get_result(points[0])

    def insert(self, collection_name: str, items: list[VectorItem]):
        # Insert the items into the collection, if the collection does not exist, it will be created.
        self._create_collection_if_not_exists(collection_name, len(items[0]['vector']))
        points = self._create_points(items)
        self._qc().upload_points(self._physical_name(collection_name), points)

    def upsert(self, collection_name: str, items: list[VectorItem]):
        # Update the items in the collection, if the items are not present, insert them. If the collection does not exist, it will be created.
        self._create_collection_if_not_exists(collection_name, len(items[0]['vector']))
        points = self._create_points(items)
        return self._qc().upsert(self._physical_name(collection_name), points)

    def delete(
        self,
        collection_name: str,
        ids: Optional[list[str]] = None,
        filter: Optional[dict] = None,
    ):
        # Delete by point ID: the point ID is the item's id (see _create_points).
        # Filtering on metadata.id silently misses points whose payload omits an
        # id (e.g. memories), leaving orphaned vectors behind.
        if ids:
            return self._qc().delete(
                collection_name=self._physical_name(collection_name),
                points_selector=models.PointIdsList(points=ids),
            )

        field_conditions = []
        if filter:
            for key, value in filter.items():
                field_conditions.append(
                    models.FieldCondition(
                        key=f'metadata.{key}',
                        match=models.MatchValue(value=value),
                    )
                )

        return self._qc().delete(
            collection_name=self._physical_name(collection_name),
            points_selector=models.FilterSelector(filter=models.Filter(must=field_conditions)),
        )

    def reset(self):
        # Resets the database. This will delete all collections and item entries.
        # Tenant-scoped: only collections under THIS scope's prefix are deleted,
        # so a reset can never wipe another tenant's collections.
        prefix = self._collection_prefix()
        collection_names = self._qc().get_collections().collections
        for collection_name in collection_names:
            if collection_name.name.startswith(prefix):
                self._qc().delete_collection(collection_name=collection_name.name)
