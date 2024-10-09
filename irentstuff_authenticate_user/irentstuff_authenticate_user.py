"""Script to authenticate the requestor's role relative to the item (owner or renter/buyer)"""

import json
import logging
import os
import requests
from jose import jwt, jwk

log = logging.getLogger()
log.setLevel(logging.INFO)

COGNITO_POOL_ID = os.getenv("COGNITO_POOL_ID")
COGNITO_REGION = os.getenv("COGNITO_REGION")
APP_CLIENT_ID = os.getenv("APP_WEB_CLIENT_ID")


def get_cognito_jwks():
    jwks_url = f'https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_POOL_ID}/.well-known/jwks.json'
    response = requests.get(jwks_url)
    return response.json()


def authenticate_user(event, context):

    # Get the JWT token from the query parameters
    try:
        token = event["headers"]["Authorization"]
    except Exception as e:
        log.info(f"Token not found: {e}")
        token = None

    if token is None:
        return {
            'statusCode': 403,
            'body': json.dumps('Token is missing')
        }

    try:
        # Get Cognito's JWKS
        jwks = get_cognito_jwks()

        # Get the header of the JWT token
        headers = jwt.get_unverified_header(token)
        kid = headers['kid']  # Get the key ID from the token's header

        # Find the correct key in the JWK set
        key = next(item for item in jwks['keys'] if item['kid'] == kid)

        # Verify the token using the key
        public_key = jwk.construct(key)
        log.info("Token verified")

        # Decode and verify the token (with audience verification)
        decoded_token = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            audience=APP_CLIENT_ID
        )
        log.info("Token decoded")

        # Extract the 'username' from the claims
        username = decoded_token.get('cognito:username')
        user_id = decoded_token.get('sub')  # 'sub' is the user ID (UUID)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Token is valid',
                'username': username,
                'user_id': user_id
            })
        }

    except Exception as e:
        return {
            'statusCode': 403,
            'body': json.dumps(f'Invalid token: {str(e)}')
        }
