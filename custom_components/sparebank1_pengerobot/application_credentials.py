"""Application credentials for Sparebank1 Pengerobot integration."""
from homeassistant.core import HomeAssistant
from homeassistant.components.application_credentials import (
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2Implementation,
    LocalOAuth2Implementation,
)
from .const import (
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
)

async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return authorization server for Sparebank1."""
    return AuthorizationServer(
            authorize_url=OAUTH_AUTHORIZE_URL,
            token_url=OAUTH_TOKEN_URL,
    )


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AbstractOAuth2Implementation:
    """Return auth implementation."""
    return LocalOAuth2Implementation(
        hass,
        auth_domain,
        credential.client_id,
        client_secret=credential.client_secret,
        authorize_url=OAUTH_AUTHORIZE_URL,
        token_url=OAUTH_TOKEN_URL,
    )
