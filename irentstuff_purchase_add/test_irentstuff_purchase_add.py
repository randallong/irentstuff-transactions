import json
import os
import pymysql
import pytest
import requests

from unittest import TestCase
from unittest.mock import patch, MagicMock

from irentstuff_purchase_add import (
    invoke_auth_lambda,
    connect_to_db,
    send_message,
    response_headers,
    get_item,
    check_item_rental_status,
    create_purchases_table,
    add_purchase
)


class TestAuthLambda:
    @patch("irentstuff_purchase_add.lambda_client.invoke")
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

    @patch("irentstuff_purchase_add.lambda_client.invoke")
    def test_invoke_auth_lambda_failure(self, mock_invoke):
        # Mock failed Lambda invocation
        mock_response = MagicMock()
        mock_response['StatusCode'] = 500
        mock_payload = {
            'body': json.dumps({"error": "authentication failed"})
        }
        mock_response['Payload'].read.return_value = json.dumps(mock_payload)

        mock_invoke.return_value = mock_response
        jwt_token = "invalid_jwt_token"

        # Call the function and expect it to raise an exception
        with pytest.raises(Exception) as exc_info:
            invoke_auth_lambda(jwt_token)

        mock_invoke.assert_called_once_with(
            FunctionName='irentstuff-authenticate-user',
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "headers": {
                    "Authorization": jwt_token
                }
            })
        )
        assert str(exc_info.value) == 'Authentication failed: {"error": "authentication failed"}'


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

    @patch("irentstuff_purchase_add.create_connection")  # Mock the WebSocket connection
    @patch("irentstuff_purchase_add.log")  # Mock logging
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

    @patch("irentstuff_purchase_add.create_connection", side_effect=Exception("Connection failed"))  # Mock failure
    @patch("irentstuff_purchase_add.log")
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
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
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
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_headers(content_type)
        assert result == expected_headers
        assert result['Content-Type'] == 'text/html'


class TestGetItem:
    @patch("requests.get")
    def test_get_item_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"item_id": "123", "name": "Test Item"}
        mock_get.return_value = mock_response

        result = get_item("123")

        mock_get.assert_called_once_with("https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/123")
        assert result == {"item_id": "123", "name": "Test Item"}

    @patch("requests.get")
    def test_get_item_failure(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Item not found"
        mock_get.return_value = mock_response

        result = get_item("123")

        mock_get.assert_called_once_with("https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/123")
        assert result == {"status_code": 404, "body": "Item not found"}

    @patch("requests.get")
    def test_get_item_exception(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API failure")

        result = get_item("123")

        mock_get.assert_called_once_with("https://pxgwc7gdz1.execute-api.ap-southeast-1.amazonaws.com/dev/items/123")
        assert result == {
            "status_code": 500,
            "headers": response_headers('text/plain'),
            "body": "Error occurred while making API call: API failure"
        }


class TestCheckItemRentalStatus:
    def test_check_item_rental_status_with_active_rentals(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchall.return_value = [("rental_1", "item_1", "renter_1", "active")]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = check_item_rental_status(mock_conn, "item_1")

        # Assertions
        mock_cursor.execute.assert_called_once()
        args, _ = mock_cursor.execute.call_args

        assert args[1] == ("item_1",)  # Check that the correct parameters were passed
        assert result == {
            "status_code": 403,
            "headers": response_headers('text/plain'),
            "body": "Active rentals found for item_id item_1: [('rental_1', 'item_1', 'renter_1', 'active')]"
        }

    def test_check_item_rental_status_with_no_active_rentals(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        result = check_item_rental_status(mock_conn, "item_1")

        # Assertions
        mock_cursor.execute.assert_called_once()  # Check that execute was called once
        args, _ = mock_cursor.execute.call_args  # Get the arguments passed to execute

        assert args[1] == ("item_1",)  # Check that the correct parameters were passed
        assert result == {
            "status_code": 200,
            "headers": response_headers('text/plain'),
            "body": "No active rentals found for item_id item_1"
        }

    def test_check_item_rental_status_database_error(self):
        # Mock the transactions connection and cursor
        mock_conn = MagicMock()

        # Set up the mock cursor to raise a MySQLError
        mock_conn.cursor.side_effect = pymysql.MySQLError("Database connection error")

        # Call the function with the mocked connection and a test item_id
        result = check_item_rental_status(mock_conn, "item_1")

        # Assertions
        assert result == {
            "status_code": 500,
            "headers": response_headers('text/plain'),
            "body": "An error occurred while querying the database: Database connection error"
        }


class TestCreatePurchasesTable:
    def test_create_purchases_table(self):
        # Mock the transactions connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Set the cursor to return the mock cursor when __enter__ is called
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Call the function with the mocked connection
        create_purchases_table(mock_conn)

        # Assertions
        mock_cursor.execute.assert_called_once()  # Ensure execute was called once
        args, _ = mock_cursor.execute.call_args  # Get the arguments passed to execute

        # Define the expected SQL query
        expected_create_table_sql = """
            CREATE TABLE IF NOT EXISTS Purchases (
            purchase_id INT AUTO_INCREMENT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            owner_id VARCHAR(255) NOT NULL,
            buyer_id VARCHAR(255) NOT NULL,
            item_id INT NOT NULL,
            purchase_date DATE NULL,
            status VARCHAR(255) NOT NULL,
            purchase_price DECIMAL(10, 2) NOT NULL
    )
        """.strip()  # Stripping whitespace for comparison

        # Check that the correct SQL query was executed
        print(expected_create_table_sql)
        print(args[0].strip())
        assert args[0].strip() == expected_create_table_sql

        # Ensure that commit was called on the connection
        mock_conn.commit.assert_called_once()


class TestAddPurchaseFunctions(TestCase):

    @patch("irentstuff_purchase_add.invoke_auth_lambda")
    @patch("irentstuff_purchase_add.get_item")
    @patch("irentstuff_purchase_add.check_item_rental_status")
    @patch("irentstuff_purchase_add.create_purchase_entry")
    @patch("irentstuff_purchase_add.connect_to_db")
    def test_add_purchase_success(self, mock_connect, mock_check_item_rental_status, mock_create_purchase_entry, mock_get_item, mock_invoke_auth_lambda):
        # Arrange
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_check_item_rental_status.return_value = {
            "status_code": 200,
            "headers": response_headers('text/plain'),
            "body": "No active rentals found for item_id item_1"
        }
        mock_get_item.return_value = {"availability": "available", "owner": "owner1"}
        mock_invoke_auth_lambda.return_value = {"message": "Token is valid", "username": "buyer1"}

        event = {
            "pathParameters": {"item_id": "1"},
            "headers": {"Authorization": "Bearer token"},
            "body": json.dumps({
                "users": {
                    "owner_id": "owner1",
                    "buyer_id": "buyer1"
                },
                "purchase_details": {
                    "purchase_price": 100.00
                }
            })
        }
        context = {}

        mock_create_purchase_entry.return_value = {
            "status_code": 200,
            "body": json.dumps({"purchase_id": 1})
        }

        # Act
        response = add_purchase(event, context)

        # Assert
        self.assertIsNotNone(response, "Response should not be None")
        mock_create_purchase_entry.assert_called_once()

    @patch("irentstuff_purchase_add.invoke_auth_lambda")
    @patch("irentstuff_purchase_add.get_item")
    def test_add_purchase_invalid_token(self, mock_get_item, mock_invoke_auth_lambda):
        # Arrange
        mock_get_item.return_value = {"availability": "available", "owner": "owner1"}
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is invalid",
            "username": "test_user"
            }

        event = {
            "pathParameters": {"item_id": "1"},
            "headers": {"Authorization": "Bearer token"},
            "body": json.dumps({})
        }
        context = {}

        # Act
        response = add_purchase(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 401)
        self.assertIn("Your user token is invalid.", response["body"])

    @patch("irentstuff_purchase_add.invoke_auth_lambda")
    @patch("irentstuff_purchase_add.get_item")
    def test_add_purchase_owner_cannot_buy_own_item(self, mock_get_item, mock_invoke_auth_lambda):
        # Arrange
        mock_get_item.return_value = {"availability": "available", "owner": "owner1"}
        mock_invoke_auth_lambda.return_value = {"message": "Token is valid", "username": "owner1"}

        event = {
            "pathParameters": {"item_id": "1"},
            "headers": {"Authorization": "Bearer token"},
            "body": json.dumps({})
        }
        context = {}

        # Act
        response = add_purchase(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("You cannot purchase your own item.", response["body"])
