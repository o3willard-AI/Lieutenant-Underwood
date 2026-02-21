"""LM Studio API client."""

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from lmstudio_tui.config import ServerConfig

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Information about a model."""

    id: str
    name: str
    size: int  # bytes
    loaded: bool


class LMStudioClient:
    """HTTP client for LM Studio API."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1234,
        timeout: Optional[float] = None,
    ):
        """Initialize the client.

        Args:
            host: Hostname or IP of the LM Studio server.
            port: Port number for the API.
            timeout: Request timeout in seconds (default: 10.0).
        """
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout if timeout is not None else 10.0
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    @classmethod
    def from_config(cls, config: ServerConfig) -> "LMStudioClient":
        """Create client from server configuration.

        Args:
            config: ServerConfig instance with connection details.

        Returns:
            Configured LMStudioClient instance.
        """
        return cls(
            host=config.host,
            port=config.port,
            timeout=config.timeout,
        )

    async def get_models(self) -> list[ModelInfo]:
        """Get list of available models.

        GET /v1/models

        Returns:
            List of ModelInfo objects.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        try:
            response = await self._client.get("/v1/models")
            response.raise_for_status()
            data = response.json()

            models = []
            for item in data.get("data", []):
                # Handle both 'id' and 'model' fields for compatibility
                model_id = item.get("id") or item.get("model", "")
                model_name = item.get("name", model_id)
                size = item.get("size", 0)
                loaded = item.get("loaded", False)

                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model_name,
                        size=size,
                        loaded=loaded,
                    )
                )

            return models
        except httpx.HTTPError as e:
            logger.error(f"Failed to get models: {e}")
            raise

    async def load_model(self, model_id: str) -> bool:
        """Load a model into memory.

        POST /v1/models/load

        Args:
            model_id: Identifier of the model to load.

        Returns:
            True if the model was loaded successfully.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        try:
            response = await self._client.post(
                "/v1/models/load",
                json={"model_id": model_id},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to load model {model_id}: {e}")
            raise

    async def unload_model(self, model_id: str) -> bool:
        """Unload a model from memory.

        POST /v1/models/unload

        Args:
            model_id: Identifier of the model to unload.

        Returns:
            True if the model was unloaded successfully.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        try:
            response = await self._client.post(
                "/v1/models/unload",
                json={"model_id": model_id},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to unload model {model_id}: {e}")
            raise

    async def get_loaded_models(self) -> list[ModelInfo]:
        """Get list of currently loaded models.

        Returns:
            List of loaded ModelInfo objects.
        """
        models = await self.get_models()
        return [m for m in models if m.loaded]

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self._client.aclose()

    async def __aenter__(self) -> "LMStudioClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
