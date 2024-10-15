import json
import os
import pymysql
import pytest
import requests

from datetime import datetime, date
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch, MagicMock

from irentstuff_purchase_update import (
    invoke_auth_lambda,
    connect_to_db,
    send_message,
    response_headers,
    retrieve_updated_purchase,
    update_db,
    update_availability_in_items_db,
    update_purchase_status
)


class TestAuthLambda:
    @patch("irentstuff_purchase_update.lambda_client.invoke")
    def test_invoke_auth_lambda_success(self, mock_invoke):
        # Mock successful Lambda invocation
        mock_payload = {
            'body': json.dumps({"user": "authenticated_user"})
        }
        mock_response = {
            'StatusCode': 200,
            'Payload': MagicMock(read=MagicMock(return_value=json.dumps(mock_payload)))
        }

        mock_invoke.return_value = mock_response
        jwt_token = "test_jwt_token"

        # Call the function
        result = invoke_auth_lambda(jwt_token)

        # Assertions
        mock_invoke.assert_called_once_with(
            FunctionName='irentstuff-authenticate-user',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "headers": {
                    "Authorization": jwt_token
                }
            })
        )

        assert result == {"user": "authenticated_user"}


class TestConnectToDB(TestCase):
    @classmethod
    def setUpClass(cls):
        # Set up environment variables for testing
        os.environ["DB1_USER_NAME"] = "test_user"
        os.environ["DB1_PASSWORD"] = "test_password"
        os.environ["DB1_RDS_PROXY_HOST"] = "test_host"
        os.environ["DB1_NAME"] = "test_db"

    @patch("pymysql.connect")
    def test_connect_to_db_success(self, mock_connect):
        # Mock the connection object
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Call the function
        result = connect_to_db()

        # Assert that the connect function was called with the expected arguments
        mock_connect.assert_called_once_with(
            host=os.environ["DB1_RDS_PROXY_HOST"],
            user=os.environ["DB1_USER_NAME"],
            passwd=os.environ["DB1_PASSWORD"],
            db=os.environ["DB1_NAME"],
            connect_timeout=5
        )

        # Assert that the returned connection is the mocked connection
        self.assertEqual(result, mock_conn)

    @patch("pymysql.connect")
    @patch("sys.exit")  # Mock sys.exit to prevent the script from exiting
    def test_connect_to_db_failure(self, mock_exit, mock_connect):
        # Simulate a MySQL error when trying to connect
        mock_connect.side_effect = pymysql.MySQLError("Connection error")

        # Call the function (no need to expect SystemExit since we're mocking sys.exit)
        connect_to_db()

        # Assert that sys.exit was called with the correct exit code
        mock_exit.assert_called_once_with(1)


class TestSendMessage(TestCase):

    @patch("irentstuff_purchase_update.create_connection")  # Mock the WebSocket connection
    @patch("irentstuff_purchase_update.log")  # Mock logging
    def test_send_message_success(self, mock_log, mock_create_connection):
        # Arrange
        ws_mock = MagicMock()
        mock_create_connection.return_value = ws_mock
        ws_mock.recv.return_value = "Success message"  # Mock receiving a WebSocket response

        content = {
            "token": "test_token",
            "itemId": "test_item",
            "ownerid": "test_owner",
            "renterId": "test_renter",
            "username": "test_user"
        }

        # Act
        response = send_message(content)

        # Assert
        mock_create_connection.assert_called_once_with("wss://6z72j61l2b.execute-api.ap-southeast-1.amazonaws.com/dev/?token=test_token")
        self.assertEqual(response, {
            "statusCode": 200,
            "body": "WebSocket connection initiated"
        })
        ws_mock.send.assert_called_once()  # Ensure the message was sent
        ws_mock.close.assert_called_once()  # Ensure the WebSocket connection was closed
        mock_log.info.assert_called()  # Check that logs were recorded

    @patch("irentstuff_purchase_update.create_connection", side_effect=Exception("Connection failed"))  # Mock failure
    @patch("irentstuff_purchase_update.log")
    def test_send_message_failure(self, mock_log, mock_create_connection):
        # Arrange
        content = {
            "token": "invalid_token"
        }

        # Act
        response = send_message(content)

        # Assert
        self.assertEqual(response, {
            "statusCode": 500,
            "body": "Error encountered: Connection failed"
        })
        mock_log.error.assert_called_once_with("Message failed to send!")


class TestResponseHeaders:
    def test_response_headers(self):
        # Test case for when content_type is 'application/json'
        content_type = "application/json"
        expected_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_headers(content_type)
        assert result == expected_headers
        assert result['Content-Type'] == 'application/json'

    def test_response_headers_text(self):
        # Test case for when content_type is 'text/html'
        content_type = "text/html"
        expected_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_headers(content_type)
        assert result == expected_headers
        assert result['Content-Type'] == 'text/html'


class TestRetrieveUpdatedPurchase(TestCase):
    def test_retrieve_updated_purchase_found(self):
        # Mock the cursor and its fetchone() method
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "purchase_id": "purchase_123",
            "created_at": datetime(2023, 10, 1, 14, 30, 0),
            "updated_at": datetime(2023, 10, 5, 16, 45, 0),
            "owner_id": "owner_001",
            "buyer_id": "buyer_002",
            "item_id": "item_123",
            "status": "active",
            "purchase_price": Decimal('15.00'),
            "purchase_date": datetime(2023, 11, 5, 16, 45, 0),
        }

        # Call the function
        response = retrieve_updated_purchase(mock_cursor, "item_123", "purchase_123")

        # Expected response
        expected_response = {
            "purchase_id": "purchase_123",
            "created_at": "2023-10-01T14:30:00",
            "updated_at": "2023-10-05T16:45:00",
            "owner_id": "owner_001",
            "buyer_id": "buyer_002",
            "item_id": "item_123",
            "status": "active",
            "purchase_price": 15.00,
            "purchase_date": "2023-11-05T16:45:00",
        }

        # Assert the response matches the expected response
        self.assertEqual(response, expected_response)

    def test_retrieve_updated_purchase_not_found(self):
        # Mock the cursor's fetchone() method to return None
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None

        # Call the function
        response = retrieve_updated_purchase(mock_cursor, "item_123", "purchase_999")

        # Expected response for purchase not found
        expected_response = {"error": "Purchase not found"}

        # Assert the response matches the expected response
        self.assertEqual(response, expected_response)


class TestUpdateDB(TestCase):
    @patch("irentstuff_purchase_update.retrieve_updated_purchase")  # Mock the function call for retrieve_updated_purchase
    def test_update_db_status_sold(self, mock_retrieve_updated_purchase):
        # Arrange
        mock_cursor = MagicMock()
        mock_transactions_conn = MagicMock()

        # Set up the mock response for retrieve_updated_purchase
        mock_retrieve_updated_purchase.return_value = {
            "purchase_id": 1,
            "item_id": 2,
            "status": "sold",
            "purchase_date": "2024-10-09"
        }

        # Inputs
        new_status = "sold"
        purchase_id = 1
        item_id = 2

        # Act
        response = update_db(mock_cursor, new_status, purchase_id, item_id, mock_transactions_conn)

        # Assert
        # Check if the correct query was executed for the "sold" status
        mock_cursor.execute.assert_called_once_with(
            "UPDATE Purchases SET status = %s, purchase_date = NOW() WHERE purchase_id = %s AND item_id = %s",
            (new_status, purchase_id, item_id)
        )

        # Ensure the transaction was committed
        mock_transactions_conn.commit.assert_called_once()

        # Check if retrieve_updated_purchase was called with correct parameters
        mock_retrieve_updated_purchase.assert_called_once_with(mock_cursor, item_id, purchase_id)

        # Check the response format and content
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertIn("purchase_id", response["body"])
        self.assertIn("status", response["body"])
        self.assertIn("purchase_date", response["body"])

    @patch("irentstuff_purchase_update.retrieve_updated_purchase")
    def test_update_db_status_not_sold(self, mock_retrieve_updated_purchase):
        # Arrange
        mock_cursor = MagicMock()
        mock_transactions_conn = MagicMock()

        # Set up the mock response for retrieve_updated_purchase
        mock_retrieve_updated_purchase.return_value = {
            "purchase_id": 1,
            "item_id": 2,
            "status": "pending",
            "purchase_date": None
        }

        # Inputs
        new_status = "pending"
        purchase_id = 1
        item_id = 2

        # Act
        response = update_db(mock_cursor, new_status, purchase_id, item_id, mock_transactions_conn)

        # Assert
        # Check if the correct query was executed for the "pending" status
        mock_cursor.execute.assert_called_once_with(
            "UPDATE Purchases SET status = %s WHERE purchase_id = %s AND item_id = %s",
            (new_status, purchase_id, item_id)
        )

        # Ensure the transaction was committed
        mock_transactions_conn.commit.assert_called_once()

        # Check if retrieve_updated_purchase was called with correct parameters
        mock_retrieve_updated_purchase.assert_called_once_with(mock_cursor, item_id, purchase_id)

        # Check the response format and content
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertIn("purchase_id", response["body"])
        self.assertIn("status", response["body"])
        self.assertIn("purchase_date", response["body"])


class TestUpdateAvailabilityInItemsDB(TestCase):

    @patch("requests.patch")  # Mock the requests.patch method
    def test_update_availability_success(self, mock_patch):
        token = "valid_token"
        item_id = "item_123"
        availability = "available"

        # Mock the response object
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Availability updated"}
        mock_patch.return_value = mock_response

        # Call the function
        result = update_availability_in_items_db(token, item_id, availability)

        # Verify that requests.patch was called with the correct parameters
        api_url = f"https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/{item_id}"
        expected_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        expected_payload = {"availability": availability}

        mock_patch.assert_called_once_with(api_url, headers=expected_headers, json=expected_payload)

        # Assert that the result matches the expected response
        expected_result = {"message": "Availability updated"}
        self.assertEqual(result, expected_result)

    @patch("requests.patch")  # Mock the requests.patch method
    def test_update_availability_failure(self, mock_patch):
        token = "valid_token"
        item_id = "item_123"
        availability = "unavailable"

        # Mock the response object to simulate a failure
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_patch.return_value = mock_response

        # Call the function
        result = update_availability_in_items_db(token, item_id, availability)

        # Assert that the result contains the status code and body
        expected_result = {
            "status_code": 400,
            "body": "Bad Request"
        }
        self.assertEqual(result, expected_result)

    @patch("requests.patch")  # Mock the requests.patch method
    def test_update_availability_request_exception(self, mock_patch):
        token = "valid_token"
        item_id = "item_123"
        availability = "available"

        # Simulate a RequestException
        mock_patch.side_effect = requests.exceptions.RequestException("Connection error")

        # Call the function
        result = update_availability_in_items_db(token, item_id, availability)

        # Assert that the result contains the expected error message
        expected_result = {
            "status_code": 500,
            "body": "Error occurred while making API call: Connection error"
        }
        self.assertEqual(result, expected_result)


class TestUpdatePurchaseStatus(TestCase):

    @patch("irentstuff_purchase_update.update_availability_in_items_db")
    @patch("irentstuff_purchase_update.update_db")
    @patch("irentstuff_purchase_update.invoke_auth_lambda")
    @patch("irentstuff_purchase_update.connect_to_db")
    def test_update_purchase_confirm_success(self, mock_connect_to_db, mock_invoke_auth_lambda, mock_update_db, mock_update_availability):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect_to_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mocking database query for fetching purchase
        mock_cursor.fetchone.return_value = {
            "purchase_id": 1,
            "item_id": 1,
            "status": "offered",
            "owner_id": "owner1",
            "buyer_id": "buyer1"
        }

        # Mocking authentication
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "owner1"
        }

        # Mock update_db response
        mock_update_db.return_value = {
            "statusCode": 200,
            "body": json.dumps({"message": "Purchase confirmed"})
        }

        event = {
            "pathParameters": {
                "item_id": "1",
                "purchase_id": "1",
                "action": "confirm"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }
        context = {}

        # Act
        response = update_purchase_status(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("message", json.loads(response["body"]))
        mock_update_db.assert_called_once_with(mock_cursor, "confirmed", "1", "1", mock_conn)
        mock_update_availability.assert_called_once_with("valid_token", "1", availability="pending_purchase")

    @patch("irentstuff_purchase_update.update_availability_in_items_db")
    @patch("irentstuff_purchase_update.update_db")
    @patch("irentstuff_purchase_update.invoke_auth_lambda")
    @patch("irentstuff_purchase_update.connect_to_db")
    def test_update_purchase_cancel_success(self, mock_connect_to_db, mock_invoke_auth_lambda, mock_update_db, mock_update_availability):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect_to_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mocking database query for fetching purchase
        mock_cursor.fetchone.return_value = {
            "purchase_id": 1,
            "item_id": 1,
            "status": "offered",
            "owner_id": "owner1",
            "buyer_id": "buyer1"
        }

        # Mocking authentication
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "buyer1"
        }

        # Mock update_db response
        mock_update_db.return_value = {
            "statusCode": 200,
            "body": json.dumps({"message": "Purchase cancelled"})
        }

        event = {
            "pathParameters": {
                "item_id": "1",
                "purchase_id": "1",
                "action": "cancel"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }
        context = {}

        # Act
        response = update_purchase_status(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("message", json.loads(response["body"]))
        mock_update_db.assert_called_once_with(mock_cursor, "cancelled", "1", "1", mock_conn)
        mock_update_availability.assert_called_once_with("valid_token", "1", availability="available")

    @patch("irentstuff_purchase_update.invoke_auth_lambda")
    @patch("irentstuff_purchase_update.connect_to_db")
    def test_update_purchase_invalid_token(self, mock_connect_to_db, mock_invoke_auth_lambda):
        # Arrange
        mock_conn = MagicMock()
        mock_connect_to_db.return_value = mock_conn

        # Mocking invalid token response
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is invalid",
            "username": None
        }

        event = {
            "pathParameters": {
                "item_id": "1",
                "purchase_id": "1",
                "action": "confirm"
            },
            "headers": {
                "Authorization": "Bearer invalid_token"
            }
        }
        context = {}

        # Act
        response = update_purchase_status(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(response["body"], "Your user token is invalid.")

    @patch("irentstuff_purchase_update.invoke_auth_lambda")
    @patch("irentstuff_purchase_update.connect_to_db")
    def test_update_purchase_not_found(self, mock_connect_to_db, mock_invoke_auth_lambda):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect_to_db.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mocking database query for no purchase found
        mock_cursor.fetchone.return_value = None

        # Mocking authentication
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "buyer1"
        }

        event = {
            "pathParameters": {
                "item_id": "1",
                "purchase_id": "999",
                "action": "confirm"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }
        context = {}

        # Act
        response = update_purchase_status(event, context)
        print(response)

        # Assert
        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(response["body"], "Purchase ID 999 with Item ID 1 not found.")
