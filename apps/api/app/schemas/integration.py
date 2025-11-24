"""Integration schemas for third-party service connections."""

from typing import Optional
from pydantic import BaseModel, Field


# Request Schemas


class IntegrationConnectRequest(BaseModel):
    """Schema for connecting an integration.

    Attributes:
        redirect_uri: Optional redirect URI for OAuth callback
    """

    redirect_uri: Optional[str] = Field(None, description="OAuth redirect URI")


# Response Schemas


class OAuthURLResponse(BaseModel):
    """Schema for OAuth authorization URL response.

    Attributes:
        auth_url: URL to redirect user for OAuth authorization
        state: OAuth state parameter for security
    """

    auth_url: str = Field(..., alias="authUrl", description="OAuth authorization URL")
    state: str = Field(..., description="OAuth state parameter")

    model_config = {"populate_by_name": True}


class IntegrationStatusResponse(BaseModel):
    """Schema for integration connection status.

    Attributes:
        service: Service name
        connected: Whether the service is connected
        connected_at: Timestamp when connection was established
    """

    service: str
    connected: bool
    connected_at: Optional[str] = None

    model_config = {"from_attributes": True}


class IntegrationListResponse(BaseModel):
    """Schema for list of user integrations.

    Attributes:
        integrations: List of integration statuses
    """

    integrations: list[IntegrationStatusResponse]
