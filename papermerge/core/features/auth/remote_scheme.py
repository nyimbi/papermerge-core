from fastapi import Request

from papermerge.core.features.users import schema
from papermerge.core.config import get_settings


class RemoteUserScheme:

    async def __call__(self, request: Request) -> schema.RemoteUser | None:
        settings = get_settings()

        # Remote-User auth is opt-in and must only be honoured when the
        # request comes from a trusted reverse proxy (e.g. OAuth2-Proxy).
        # This prevents unauthenticated clients from forging the forwarded
        # identity headers.
        if not settings.remote_user_enabled:
            return None

        client_host = request.client.host if request.client else None
        if not settings.trusted_proxies or client_host not in settings.trusted_proxies:
            return None

        user_header_name = settings.remote_user_header
        groups_header_name = settings.remote_groups_header
        roles_header_name = settings.remote_roles_header
        name_header_name = settings.remote_name_header
        email_header_name = settings.remote_email_header

        username = request.headers.get(user_header_name)
        groups = request.headers.get(groups_header_name, "")
        roles = request.headers.get(roles_header_name, "")
        name = request.headers.get(name_header_name, "")
        email = request.headers.get(email_header_name, "")

        if not username:
            return None

        return schema.RemoteUser(
            username=username,
            groups=groups.split(","),
            roles=roles.split(","),
            name=name,
            email=email,
        )
