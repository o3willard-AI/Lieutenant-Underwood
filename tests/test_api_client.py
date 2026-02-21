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
    """Test get_models with mocked HTTP response."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {
                "id": "test-model-1",
                "name": "Test Model 1",
                "size": 1000000,
                "loaded": True,
            },
            {
                "id": "test-model-2",
                "name": "Test Model 2",
                "size": 2000000,
                "loaded": False,
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
    assert models[1].id == "test-model-2"
    assert models[1].loaded is False

    mock_client.get.assert_called_once_with("/v1/models")


@pytest.mark.asyncio
async def test_load_model_mocked():
    """Test load_model with mocked HTTP response."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        result = await client.load_model("my-model-id")

    assert result is True
    mock_client.post.assert_called_once_with(
        "/v1/models/load",
        json={"model_id": "my-model-id"},
    )


@pytest.mark.asyncio
async def test_unload_model_mocked():
    """Test unload_model with mocked HTTP response."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        result = await client.unload_model("my-model-id")

    assert result is True
    mock_client.post.assert_called_once_with(
        "/v1/models/unload",
        json={"model_id": "my-model-id"},
    )


@pytest.mark.asyncio
async def test_close():
    """Test closing the client."""
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        client = LMStudioClient()
        await client.close()

    mock_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_get_models_http_error():
    """Test get_models handles HTTP errors."""
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
