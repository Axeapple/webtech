import httpx

from urllib.parse import parse_qs
from django.conf import settings

from .models import User


class WebsocketAuthMiddleware:
    """
    Custom middleware that checks that the client is authenticated.
    """

    def __init__(self, app):
        """
        Constructor called upon server's start. It stores the asgi app 
            and initialises the authentication service url for later use.
        """
        self.app = app
        self.auth_api = settings.USER_AUTH_API

    async def __call__(self, scope, receive, send):
        """
        This method is called before establishing a websocket connection. It proceeds to validate 
            the access token issued by the authentication microservice and creates a new key in the scope 
            dictionary to use in the notification consumer. If the validation fails, the key created will 
            reflect that to deny unauthenticated/unauthorized connections, and thereby, enhance security.
        """
        scope['user_auth'] = False 
        query_string = parse_qs(
            scope['query_string'].decode()
        )
        if 'Authorization' in query_string.keys():
            is_authenticated = await self.is_authenticated(
                query_string['Authorization'][0],
                scope['path']
            )
            if is_authenticated:
                scope['user_auth'] = True
        return await self.app(scope, receive, send)
    
    async def is_authenticated(self, token: str, path: str) -> bool:
        """
        Sends a request to the authentication service in order to validate the token 
            sent by the client. The authentication would fail if the token is not valid, 
            the email isn't verified, or the client tries to subscribe to another channel.

        Parameters:
            token (str): The access token generated by the authentication service.
            path (str): The websocket path that the client is attempting to connect to.
        Returns:
            bool: True or False depending on whether the authentication is validated.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url=self.auth_api + token
            )
            data = response.json()
            if not 'error' in data.keys():
                if data['verified_email']:
                    user_id = await self.get_user_id(
                        data['email']
                    )
                    allowed = await self.is_designated_channel(
                        path, user_id
                    )
                    if allowed:
                        return True
                    return False
                return False
            return False
            
    @staticmethod
    async def get_user_id(email: str) -> str:
        """
        Database query to retrieve the user id based on their verified email address. 
            The id is a part of the websocket path, therefore, it's essential to prevent 
            authenticated users from connecting to other users notification channels.

        Parameters:
            email (str): The email address of the authenticated user.
        Returns:
            str: The user id, or 'Anonymous' if the user is not registered in the DB.
        """
        try:
            user = await User.objects.aget(email=email)
            return str(user.pk)
        except User.DoesNotExist:
            return 'Anonymous'
    
    @staticmethod
    async def is_designated_channel(path: str, user_id: str) -> bool:
        """
        Checks that the path of the websocket that the user is trying to connect to 
            matches the path of their assigned websocket. This ensures that each user 
            can only access their designated channel.

        Parameters:
            path (str): The path of the websocket the user is trying to connect to.
            user_id (str): The current user id, used to construct their designated websocket path.
        Returns:
            bool: True if the user is connecting to their designated channel, or False if not.
        """
        user_designated_channel = '/ws/notification/' + user_id + '/'
        if path == user_designated_channel:
            return True
        return False