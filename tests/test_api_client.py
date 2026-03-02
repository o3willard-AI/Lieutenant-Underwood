"""Tests for the LM Studio API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from lmstudio_tui.api.client import LMStudioClient, ModelInfo
from lmstudio_tui.config import ServerConfig


def test_client_init():
    """Test client initializes with correct base_url."""
    client = LMStudioClient(host="localhost", port=1234)
    assert client.base_url == "http://localhost:1234"
    assert client.timeout == 10.0


def test_client_init_custom_timeout():
    """Test client initializes with custom timeout."""
    client = LMStudioClient(host="192.168.1.100", port=5678, timeout=30.0)
    assert client.base_url == "http://192.168.1.100:5678"
    assert client.timeout == 30.0


def test_client_from_config():
    """Test creating client from ServerConfig."""
    config = ServerConfig(host="remote-server", port=8080, timeout=5.0)
    client = LMStudioClient.from_config(config)
    assert client.base_url == "http://remote-server:8080"
    assert client.timeout == 5.0


@pytest.mark.asyncio
async def test_get_models_mocked():
    """Test get_models with mocked HTTP response matching actual /api/v1/models shape."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "models": [
            {
                "key": "test-model-1",
                "display_name": "Test Model 1",
                "size_bytes": 1000000,
                "quantization": {"name": "Q4_K_M"},
                "max_context_length": 4096,
                "loaded_instances": [
                    {"id": "inst-abc", "config": {"context_length": 4096}}
                ],
            },
            {
                "key": "test-model-2",
                "display_name": "Test Model 2",
                "size_bytes": 2000000,
                "quantization": {"name": "Q8_0"},
                "max_context_length": 8192,
                "loaded_instances": [],
            },
        ]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        models = await client.get_models()

    assert len(models) == 2
    assert models[0].id == "test-model-1"
    assert models[0].name == "Test Model 1"
    assert models[0].size == 1000000
    assert models[0].loaded is True
    assert models[0].instance_id == "inst-abc"
    assert models[1].id == "test-model-2"
    assert models[1].loaded is False
    assert models[1].instance_id is None

    mock_client.get.assert_called_once_with("/api/v1/models")


@pytest.mark.asyncio
async def test_load_model_mocked():
    """Test load_model posts to correct /api/v1/models/load endpoint."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        result = await client.load_model("my-model-id", context_length=8192)

    assert result is True
    mock_client.post.assert_called_once_with(
        "/api/v1/models/load",
        json={"model": "my-model-id", "context_length": 8192, "flash_attention": True},
        timeout=120.0,
    )



@pytest.mark.asyncio
async def test_unload_model_mocked():
    """Test unload_model posts instance_id to /api/v1/models/unload."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        result = await client.unload_model("instance-xyz-123")

    assert result is True
    mock_client.post.assert_called_once_with(
        "/api/v1/models/unload",
        json={"instance_id": "instance-xyz-123"},
    )


@pytest.mark.asyncio
async def test_close():
    """Test closing the client calls aclose."""
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        await client.close()

    mock_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_get_models_http_error():
    """Test get_models raises on HTTP errors."""
    import httpx

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        with pytest.raises(httpx.HTTPError):
            await client.get_models()


@pytest.mark.asyncio
async def test_async_context_manager():
    """Test client works as async context manager."""
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        async with LMStudioClient() as client:
            assert isinstance(client, LMStudioClient)

        mock_client.aclose.assert_called_once()
