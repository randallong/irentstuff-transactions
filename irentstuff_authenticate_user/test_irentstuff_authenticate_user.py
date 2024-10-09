import json
import os
import unittest
from unittest.mock import patch, MagicMock
from irentstuff_authenticate_user import authenticate_user, get_cognito_jwks


class TestAuthenticateUser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Set up environment variables for testing
        os.environ["COGNITO_POOL_ID"] = "test_pool_id"
        os.environ["COGNITO_REGION"] = "us-west-2"
        os.environ["APP_WEB_CLIENT_ID"] = "test_client_id"

    @patch("irentstuff_authenticate_user.requests.get")  # Mock the requests.get call in your module
    @patch("irentstuff_authenticate_user.jwk.construct")
    @patch("irentstuff_authenticate_user.jwt.decode")
    @patch("irentstuff_authenticate_user.jwt.get_unverified_header")
    def test_authenticate_user_success(self, mock_get_header, mock_decode, mock_jwk, mock_requests):
        # Mock the JWKS response
        mock_requests.return_value.json.return_value = {
            "keys": [
                {
                    "kid": "test_kid",
                    "n": "test_n",
                    "e": "test_e"
                }
            ]
        }

        # Mock the JWT token verification and decoding
        mock_get_header.return_value = {"kid": "test_kid"}
        mock_jwk.return_value = MagicMock()
        mock_decode.return_value = {
            "cognito:username": "test_user",
            "sub": "test_user_id"
        }

        event = {
            "headers": {
                "Authorization": "test_jwt_token"
            }
        }
        context = {}

        # Act
        response = authenticate_user(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Token is valid", response["body"])
        self.assertIn("username", response["body"])
        self.assertIn("user_id", response["body"])

    def test_authenticate_user_missing_token(self):
        event = {
            "headers": {}
        }
        context = {}

        # Act
        response = authenticate_user(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 403)
        self.assertIn("Token is missing", response["body"])

    @patch("irentstuff_authenticate_user.requests.get")  # Mock the requests.get call in your module
    def test_authenticate_user_invalid_token(self, mock_requests):
        # Mock the JWKS response
        mock_requests.return_value.json.return_value = {
            "keys": [
                {
                    "kid": "test_kid",
                    "n": "test_n",
                    "e": "test_e"
                }
            ]
        }

        event = {
            "headers": {
                "Authorization": "invalid_jwt_token"
            }
        }
        context = {}

        # Act
        response = authenticate_user(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 403)
        self.assertIn("Invalid token:", response["body"])

    @patch("irentstuff_authenticate_user.requests.get")  # Mock the requests.get call in your module
    def test_get_cognito_jwks_failure(self, mock_requests):
        # Simulate a request failure
        mock_requests.side_effect = Exception("Failed to get JWKS")

        event = {
            "headers": {
                "Authorization": "test_jwt_token"
            }
        }
        context = {}

        # Act
        response = authenticate_user(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 403)
        self.assertIn("Invalid token:", response["body"])
