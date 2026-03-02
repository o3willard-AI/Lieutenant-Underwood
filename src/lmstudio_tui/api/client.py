"""LM Studio API client."""

import json
import logging
from collections.abc import AsyncGenerator
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
    quantization: str = "-"
    max_context_length: int = 0
    loaded_context_length: int = 0
    instance_id: Optional[str] = None  # Required for unload


class LMStudioClient:
    """HTTP client for LM Studio API."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1234,
        timeout: Optional[float] = None,
        token: Optional[str] = None,
    ):
        """Initialize the client.

        Args:
            host: Hostname or IP of the LM Studio server.
            port: Port number for the API.
            timeout: Request timeout in seconds (default: 10.0).
            token: Bearer token for API authentication (optional).
        """
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout if timeout is not None else 10.0
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=headers,
        )

    @classmethod
    def from_config(cls, config: ServerConfig) -> "LMStudioClient":
        """Create client from server configuration.

        Reads the API token from disk if ``config.resolved_api_token_path``
        exists and contains a non-empty string.

        Args:
            config: ServerConfig instance with connection details.

        Returns:
            Configured LMStudioClient instance.
        """
        token: Optional[str] = None
        token_path = config.resolved_api_token_path
        if token_path and token_path.exists():
            try:
                token = token_path.read_text().strip() or None
            except OSError as e:
                logger.warning(f"Could not read API token from {token_path}: {e}")

        return cls(
            host=config.host,
            port=config.port,
            timeout=config.timeout,
            token=token,
        )

    async def get_models(self) -> list[ModelInfo]:
        """Get list of available models with loaded status.

        Uses /api/v1/models which provides size, quantization, and loaded_instances.

        Returns:
            List of ModelInfo objects.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        try:
            # Use v1 API for complete model info
            response = await self._client.get("/api/v1/models")
            response.raise_for_status()
            data = response.json()

            models = []
            for item in data.get("models", []):
                model_id = item.get("key", "")
                model_name = item.get("display_name", model_id)
                size = item.get("size_bytes", 0)
                
                # Get quantization name from object
                quant_obj = item.get("quantization", {})
                quantization = quant_obj.get("name", "-")
                
                max_context = item.get("max_context_length", 0)
                
                # Check loaded_instances for loaded state and instance_id
                loaded_instances = item.get("loaded_instances", [])
                loaded = len(loaded_instances) > 0
                instance_id = None
                loaded_context = 0
                
                if loaded and loaded_instances:
                    instance_id = loaded_instances[0].get("id")
                    config = loaded_instances[0].get("config", {})
                    loaded_context = config.get("context_length", 0)

                models.append(
                    ModelInfo(
                        id=model_id,
                        name=model_name,
                        size=size,
                        loaded=loaded,
                        quantization=quantization,
                        max_context_length=max_context,
                        loaded_context_length=loaded_context,
                        instance_id=instance_id,
                    )
                )

            return models
        except httpx.HTTPError as e:
            logger.error(f"Failed to get models: {e}")
            raise

    async def load_model(
        self,
        model_id: str,
        context_length: Optional[int] = None,
        gpu_offload: Optional[int] = None
    ) -> bool:
        """Load a model into memory.

        POST /v1/models/load

        Args:
            model_id: Identifier of the model to load.
            context_length: Context window size (defaults to 8192 if not specified).
            gpu_offload: Percentage of layers to offload to GPU (0-100, negative for max).

        Returns:
            True if the model was loaded successfully.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        logger.info(f"API: load_model called with model_id={model_id}, context_length={context_length}, gpu_offload={gpu_offload}")
        try:
            logger.info(f"API: POST {self.base_url}/api/v1/models/load (timeout=120s)")

            # Build request payload per LM Studio API docs
            # https://lmstudio.ai/docs/developer/rest/load
            payload: dict[str, Any] = {
                "model": model_id,
                "context_length": context_length if context_length is not None else 8192,
                "flash_attention": True,
            }

            # Add GPU offload if specified
            if gpu_offload is not None:
                if gpu_offload < 0:
                    payload["gpu_offload"] = "max"
                else:
                    payload["gpu_offload"] = gpu_offload

            # Load can take 30-120 seconds for large models
            response = await self._client.post(
                "/api/v1/models/load",
                json=payload,
                timeout=120.0,
            )
            logger.info(f"API: Response status={response.status_code}")
            response.raise_for_status()
            logger.info(f"API: Model {model_id} loaded successfully")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"API: Failed to load model {model_id}: {e}")
            logger.error(f"API: Response body: {e.response.text}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"API: Failed to load model {model_id}: {e}")
            raise

    async def unload_model(self, instance_id: str) -> bool:
        """Unload a model from memory.

        POST /api/v1/models/unload

        Args:
            instance_id: Instance ID of the loaded model (from loaded_instances[].id).

        Returns:
            True if the model was unloaded successfully.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        try:
            logger.info(f"API: Unloading model with instance_id={instance_id}")
            response = await self._client.post(
                "/api/v1/models/unload",
                json={"instance_id": instance_id},
            )
            logger.info(f"API: Unload response status={response.status_code}, body={response.text}")
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to unload model with instance_id={instance_id}: {e}")
            raise

    async def get_loaded_models(self) -> list[ModelInfo]:
        """Get list of currently loaded models.

        Returns:
            List of loaded ModelInfo objects.
        """
        models = await self.get_models()
        return [m for m in models if m.loaded]

    async def chat_completion(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Send chat completion request with streaming support.

        Uses LM Studio's /v1/chat/completions endpoint (OpenAI-compatible).
        Yields text chunks as they arrive for real-time display.

        Args:
            model_id: The model identifier to use.
            messages: List of message dicts with "role" and "content" keys.
            temperature: Sampling temperature (0.0 - 2.0).
            max_tokens: Max tokens to generate (-1 for no limit).
            stream: Whether to stream the response.

        Yields:
            Text chunks as they arrive from the API.

        Raises:
            httpx.HTTPError: If the request fails.
        """
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens

        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                timeout=300.0,  # 5 minute timeout for long generations
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue

                    data = line[6:]  # Remove "data: " prefix

                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse SSE chunk: {data}")
                        continue

        except httpx.HTTPError as e:
            logger.error(f"Chat completion failed: {e}")
            raise

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self._client.aclose()

    async def __aenter__(self) -> "LMStudioClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
