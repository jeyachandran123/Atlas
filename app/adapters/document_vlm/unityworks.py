"""UnityWorks self-hosted VLM adapter — a LitServe deployment behind an API key.

Speaks a deliberately small contract, which is most of its appeal and all of its
constraints:

    POST {url}                      X-API-Key: <key>
    {"prompt": str, "image_url": str, "max_new_tokens": int}
    -> {"output": str}

Three things follow from that shape, and each is handled here rather than being
allowed to leak upward:

* **One image per call.** The port hands an adapter up to ``DOCUMENT_VLM_MAX_PAGES``
  page images. This endpoint accepts one, so several pages are stitched into a
  single tall image before the call. Stitching is a pixel operation — it neither
  reads the pages nor decides what they mean — so V3 holds. Dropping the extra
  pages instead would be fabrication (V2): an invoice whose totals are on page 2
  would come back confidently wrong.
* **One prompt string.** The port separates ``system`` from ``user``; this
  endpoint has one field, so the two are joined verbatim. Nothing is added
  (V5) — the OCR text is already inside the rendered user prompt.
* **No usage reporting.** The envelope carries no token counts, so ``TokenUsage``
  is returned empty. Zeros would read as fact in a cost dashboard.

The deployment URL is configuration, never code: Lightning cloudspace hostnames
change whenever the space restarts, and a URL baked into a module would make a
routine restart a code change.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

from app.adapters.document_vlm.base import HttpDocumentVLMAdapter, VLMAdapterConfig
from app.document_platform.vlm.errors import (
    DocumentVLMBadRequestError,
    DocumentVLMConfigurationError,
    DocumentVLMInvalidResponseError,
)
from app.document_platform.vlm.ports import (
    CostEstimate,
    DocumentImage,
    TokenUsage,
    VLMExtractionRequest,
)

OUTPUT_FIELD = "output"
"""The single key the deployment answers with."""

_STITCH_MEDIA_TYPE = "image/png"

MAX_STITCHED_PIXELS = 4_000_000
"""Ceiling on a stitched page-stack, ~4 megapixels.

Four A4 pages rendered at 200 DPI stack to roughly 12 megapixels, which
base64-encodes to a payload large enough to be refused by the endpoint or to
exhaust the model's image budget. Downscaling the stack keeps the whole
document in front of the model, which matters more than per-page resolution
once the text is still legible.
"""


class ImageStitchError(Exception):
    """Pages could not be combined — raised below the provider vocabulary.

    Kept provider-neutral because the chat vision path uses the same stitcher
    and speaks a different error language than document extraction does.
    """


def stitch_image_bytes(images: Sequence[bytes]) -> bytes:
    """Stack images vertically into one PNG, scaled to a common width.

    Pure pixels in, pure pixels out — it neither reads the images nor decides
    what they mean, which is what keeps it usable from both the document
    adapter (where V3 forbids interpretation) and the chat path.

    A single image is still re-encoded here; callers that want the original
    bytes untouched should skip this for the one-image case.
    """
    if not images:
        raise ImageStitchError("no images to combine")

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - Pillow is a dependency
        raise ImageStitchError("Pillow is required to combine several images into one") from exc

    try:
        frames = [Image.open(io.BytesIO(data)).convert("RGB") for data in images]
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same failure
        raise ImageStitchError(f"{type(exc).__name__}") from exc

    width = max(frame.width for frame in frames)
    scaled = [
        (
            frame
            if frame.width == width
            else frame.resize(
                (width, max(1, round(frame.height * width / frame.width))), Image.LANCZOS
            )
        )
        for frame in frames
    ]

    height = sum(frame.height for frame in scaled)
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    offset = 0
    for frame in scaled:
        canvas.paste(frame, (0, offset))
        offset += frame.height

    pixels = canvas.width * canvas.height
    if pixels > MAX_STITCHED_PIXELS:
        factor = (MAX_STITCHED_PIXELS / pixels) ** 0.5
        canvas = canvas.resize(
            (max(1, round(canvas.width * factor)), max(1, round(canvas.height * factor))),
            Image.LANCZOS,
        )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


class UnityWorksDocumentVLMAdapter(HttpDocumentVLMAdapter):
    """Adapter for the self-hosted UnityWorks vision-language endpoint."""

    provider = "unityworks"

    # ── request ──────────────────────────────────────────────────────────────

    def _endpoint(self) -> str:
        """The configured URL, used verbatim.

        No path is appended: the setting is the full predict endpoint, and an
        adapter that helpfully appends ``/predict`` would break the first
        deployment that mounts it anywhere else.
        """
        return self._config.endpoint_root

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["X-API-Key"] = self._config.api_key
        return headers

    def _body(self, request: VLMExtractionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "prompt": self._joined_prompt(request),
            "max_new_tokens": request.prompt.max_output_tokens,
        }
        image = self._single_image(request.payload.images)
        if image is not None:
            body["image_url"] = self._data_url(image)
        return body

    @staticmethod
    def _joined_prompt(request: VLMExtractionRequest) -> str:
        """System and user, joined and otherwise untouched (V5)."""
        system = request.prompt.system.strip()
        user = request.prompt.user.strip()
        return f"{system}\n\n{user}" if system else user

    # ── one image ────────────────────────────────────────────────────────────

    def _single_image(self, images: Sequence[DocumentImage]) -> DocumentImage | None:
        """Reduce however many pages arrived to the one this endpoint accepts.

        A single page is passed through untouched — re-encoding it would only
        lose fidelity to prove a point.
        """
        if not images:
            return None
        if len(images) == 1:
            return images[0]
        return self._stitch(images)

    def _stitch(self, images: Sequence[DocumentImage]) -> DocumentImage:
        """Stack pages vertically into one image, scaled to a common width.

        Raises rather than falling back to the first page: a caller that asked
        about a four-page invoice and silently got page one would receive an
        answer that looks complete and is not.
        """
        try:
            combined = stitch_image_bytes([image.data for image in images])
        except ImageStitchError as exc:
            raise DocumentVLMBadRequestError(
                f"the document's {len(images)} page images could not be combined "
                f"into one: {exc}",
                provider=self.provider,
                model=self._config.model,
            ) from exc
        return DocumentImage(data=combined, media_type=_STITCH_MEDIA_TYPE, page=None)

    # ── response ─────────────────────────────────────────────────────────────

    def _read_response(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        """``{"output": ...}`` → text. Usage stays unreported, not zeroed."""
        if OUTPUT_FIELD not in data:
            raise DocumentVLMInvalidResponseError(
                f"the provider's reply had no '{OUTPUT_FIELD}' field; keys were " f"{sorted(data)}",
                raw_excerpt=str(dict(data))[:2000],
                provider=self.provider,
                model=self._config.model,
            )
        return str(data[OUTPUT_FIELD] or ""), TokenUsage(), ""

    # ── health ───────────────────────────────────────────────────────────────

    async def _probe_health(self) -> tuple[bool, dict[str, Any]]:
        """A one-token inference, because there is nothing cheaper to ask.

        This endpoint publishes no catalogue and no health route, so the only
        way to learn that the URL, the key and the model all still work is to
        use them. ``max_new_tokens=1`` keeps that honest without making a
        health poll expensive — and it catches the failure a reachability
        check cannot: a live host that rejects the key.
        """
        response = await self._post(
            self._endpoint(),
            {"prompt": "ping", "max_new_tokens": 1},
            timeout=self._config.health_timeout_seconds,
        )
        detail: dict[str, Any] = {
            "endpoint": self._endpoint(),
            "status_code": response.status_code,
            "credentials": "configured" if self._config.api_key else "missing",
        }
        try:
            body = response.json()
        except ValueError:
            detail["reason"] = "response was not JSON"
            return False, detail

        if not isinstance(body, Mapping) or OUTPUT_FIELD not in body:
            detail["reason"] = f"response had no '{OUTPUT_FIELD}' field"
            return False, detail

        detail["served"] = True
        return True, detail

    # ── cost ─────────────────────────────────────────────────────────────────

    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate:
        """Self-hosted: real infrastructure cost, no per-call price.

        Reported the same way the local provider reports it, so a comparison
        between deployments is a comparison of the same number and not of one
        real price against one invented one.
        """
        return CostEstimate(
            amount=0.0,
            currency="none",
            estimated_prompt_tokens=self._estimate_prompt_tokens(request),
            estimated_completion_tokens=request.prompt.max_output_tokens,
            basis="unityworks: self-hosted deployment, no per-call monetary cost",
        )


def build_unityworks_adapter(settings: Any, **kwargs: Any) -> UnityWorksDocumentVLMAdapter:
    """Factory used by the registry. Reads every value from settings."""
    url = str(getattr(settings, "unityworks_base_url", "") or "").strip()
    if not url:
        raise DocumentVLMConfigurationError(
            "UNITYWORKS_BASE_URL is not set; the deployment URL cannot be "
            "defaulted because it changes whenever the cloudspace restarts"
        )

    api_key = getattr(settings, "unityworks_api_key", "")
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()

    config = VLMAdapterConfig(
        base_url=url,
        model=str(getattr(settings, "unityworks_model", "") or "unityworks-vlm"),
        api_key=str(api_key or ""),
        timeout_seconds=settings.document_vlm_timeout_seconds,
        connect_timeout_seconds=settings.document_vlm_connect_timeout_seconds,
        max_retries=settings.document_vlm_max_retries,
        retry_backoff_seconds=settings.document_vlm_retry_backoff_seconds,
        max_output_tokens=settings.document_vlm_max_output_tokens,
        temperature=settings.document_vlm_temperature,
        health_timeout_seconds=settings.document_vlm_health_timeout_seconds,
    )
    return UnityWorksDocumentVLMAdapter(config, **kwargs)


def describe_unityworks_config(settings: Any) -> dict[str, Any]:
    """This provider's effective configuration, for the operator endpoint.

    ``data_residency: remote`` is the field that decides whether a document may
    be sent here at all: self-hosted is not the same as on-premise, and a site
    that may not export documents needs to read that from one place.
    """
    key = getattr(settings, "unityworks_api_key", "")
    if hasattr(key, "get_secret_value"):
        key = key.get_secret_value()
    return {
        "base_url": str(getattr(settings, "unityworks_base_url", "") or ""),
        "api_key_configured": bool(key),
        "priced": False,
        "data_residency": "remote",
    }


__all__ = [
    "MAX_STITCHED_PIXELS",
    "OUTPUT_FIELD",
    "UnityWorksDocumentVLMAdapter",
    "build_unityworks_adapter",
    "describe_unityworks_config",
]
