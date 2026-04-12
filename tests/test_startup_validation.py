import pytest
from unittest.mock import patch


def test_production_rejects_default_secret():
    with patch("app.config.settings") as mock_settings:
        mock_settings.is_production = True
        mock_settings.SECRET_KEY = "change-me-32-chars-minimum"
        mock_settings.API_KEY = "real-key"
        mock_settings.ADMIN_API_KEY = "real-admin"
        mock_settings.DATABASE_URL = "postgresql+asyncpg://x"
        mock_settings.CORS_ORIGINS = "https://example.com"
        from app.main import _validate_production_config
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            _validate_production_config()


def test_development_allows_defaults():
    with patch("app.config.settings") as mock_settings:
        mock_settings.is_production = False
        from app.main import _validate_production_config
        _validate_production_config()
