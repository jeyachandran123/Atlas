"""An organisation with nothing embedded yet has an empty knowledge base, not a broken one."""

from __future__ import annotations

import pytest

from app.document_platform.semantic.vector_store import ChromaVectorStoreProvider, VectorStoreError
from app.vector_store.chroma_cloud import ChromaCloudError


class ClientRaising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def get_collection(self, name: str):
        raise self.error


@pytest.mark.parametrize("error", [
    # A brand-new Chroma Cloud database, as the live demo first met it.
    ChromaCloudError("Chroma Cloud GET …/dip_default failed with HTTP 404: Collection [dip_default] does not exist",
                     status=404),
    # The local chromadb server's wording.
    ValueError("Collection dip_default does not exist."),
])
async def test_searching_a_collection_that_does_not_exist_finds_nothing(error):
    store = ChromaVectorStoreProvider(client=ClientRaising(error))
    assert await store.search("dip_default", [0.1, 0.2], top_k=5) == []


async def test_any_other_failure_is_still_an_error():
    store = ChromaVectorStoreProvider(client=ClientRaising(
        ChromaCloudError("Chroma Cloud GET …/dip_default failed with HTTP 403: Permission denied.", status=403)
    ))
    with pytest.raises(VectorStoreError):
        await store.search("dip_default", [0.1, 0.2], top_k=5)
