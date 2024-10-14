import json
import os
import pymysql
import pytest
import requests

from datetime import datetime, date
from unittest import TestCase
from unittest.mock import patch, MagicMock

from irentstuff_rental_add import (
    invoke_auth_lambda,
    connect_to_db,
    send_message,
    response_headers,
    get_item,
    check_item_rental_status,
    create_rental_table,
    create_rental_entry,
    add_rental
)


class TestAuthLambda:
    @patch("irentstuff_rental_add.lambda_client.invoke")
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

    @patch("irentstuff_rental_add.lambda_client.invoke")
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

    @patch("irentstuff_rental_add.create_connection")  # Mock the WebSocket connection
    @patch("irentstuff_rental_add.log")  # Mock logging
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

    @patch("irentstuff_rental_add.create_connection", side_effect=Exception("Connection failed"))  # Mock failure
    @patch("irentstuff_rental_add.log")
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
        expected_query = """
                    SELECT * FROM Rentals
                WHERE item_id = %s AND status NOT IN ('offered', 'cancelled', 'completed')
                """
        assert args[0].strip() == expected_query.strip()
        assert args[1] == ("item_1",)  # Check that the correct parameters were passed
        assert result == {
            "status_code": 403,
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

        # Strip whitespace and compare
        expected_query = """
                    SELECT * FROM Rentals
                WHERE item_id = %s AND status NOT IN ('offered', 'cancelled', 'completed')
                """.strip()  # Stripping the expected query
        assert args[0].strip() == expected_query  # Stripping the actual query

        assert args[1] == ("item_1",)  # Check that the correct parameters were passed
        assert result == {
            "status_code": 200,
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
            "body": "An error occurred while querying the database: Database connection error"
        }


class TestCreateRentalTable:
    def test_create_rental_table(self):
        # Mock the transactions connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Set the cursor to return the mock cursor when __enter__ is called
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Call the function with the mocked connection
        create_rental_table(mock_conn)

        # Assertions
        mock_cursor.execute.assert_called_once()  # Ensure execute was called once
        args, _ = mock_cursor.execute.call_args  # Get the arguments passed to execute

        # Define the expected SQL query
        expected_create_table_sql = """
            CREATE TABLE IF NOT EXISTS Rentals (
            rental_id INT AUTO_INCREMENT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            owner_id VARCHAR(255) NOT NULL,
            renter_id VARCHAR(255) NOT NULL,
            item_id INT NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            status VARCHAR(255) NOT NULL,
            price_per_day DECIMAL(10, 2) NOT NULL,
            deposit DECIMAL(10, 2) NOT NULL
        )
        """.strip()  # Stripping whitespace for comparison

        # Check that the correct SQL query was executed
        assert args[0].strip() == expected_create_table_sql

        # Ensure that commit was called on the connection
        mock_conn.commit.assert_called_once()


class TestCreateRentalEntry:
    def test_create_rental_entry_success(self):
        # Mock the transactions connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Set the cursor to return the mock cursor when __enter__ is called
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Prepare test event and item ID
        event = {
            "body": json.dumps({
                "users": {
                    "owner_id": "owner123",
                    "renter_id": "renter456"
                },
                "rental_details": {
                    "start_date": "2024-10-01",
                    "end_date": "2024-10-10",
                    "price_per_day": 50,
                    "deposit": 100
                }
            })
        }
        item_id = 1

        # Mock the last insert ID and rental query
        mock_cursor.fetchone.side_effect = [
            {"rental_id": 1},  # First call for LAST_INSERT_ID
            {
                "rental_id": 1,
                "owner_id": "owner123",
                "renter_id": "renter456",
                "item_id": item_id,
                "start_date": date(2024, 10, 1),
                "end_date": date(2024, 10, 10),
                "status": "offered",
                "price_per_day": 50,
                "deposit": 100,
                "created_at": datetime(2024, 10, 1, 0, 0, 0),
                "updated_at": datetime(2024, 10, 1, 0, 0, 0)
            }
        ]

        # Call the function being tested
        response = create_rental_entry(mock_conn, event, item_id)

        # Assertions
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["rental_id"] == 1
        assert body["owner_id"] == "owner123"
        assert body["renter_id"] == "renter456"
        assert body["item_id"] == item_id
        assert body["start_date"] == "2024-10-01"
        assert body["end_date"] == "2024-10-10"
        assert body["status"] == "offered"
        assert body["price_per_day"] == 50
        assert body["deposit"] == 100

        # Check that the correct SQL queries were executed
        expected_call = """
        INSERT INTO Rentals (
            owner_id, renter_id, item_id, start_date, end_date, status,
            price_per_day, deposit
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
            "owner123", "renter456", item_id,
            "2024-10-01", "2024-10-10", "offered", 50.0, 100.0
        )

        mock_cursor.execute.assert_any_call(*expected_call)

        mock_cursor.execute.assert_any_call("SELECT LAST_INSERT_ID() as rental_id")
        mock_cursor.execute.assert_any_call("SELECT * FROM Rentals WHERE rental_id = %s", (1,))
        mock_conn.commit.assert_called_once()


class TestAddRental(TestCase):
    @patch("irentstuff_rental_add.invoke_auth_lambda")
    @patch("irentstuff_rental_add.get_item")
    @patch("irentstuff_rental_add.connect_to_db")
    @patch("irentstuff_rental_add.create_rental_entry")
    @patch("irentstuff_rental_add.check_item_rental_status")
    def test_add_rental_success(self, mock_check_item_rental_status, mock_create_rental_entry, mock_connect, mock_get_item, mock_invoke_auth_lambda):
        # Mock the authorization response
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "test_user"
        }

        # Mock item retrieval
        mock_get_item.return_value = {
            "availability": "available",
            "owner": "item_owner"
        }

        # Mock the database connection
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Mock rental creation
        mock_create_rental_entry.return_value = {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": "Rental created successfully"})
        }

        mock_check_item_rental_status.return_value = {
            "status_code": 200,
            "body": "No active rentals found for item_id item_123"
        }

        event = {
            "pathParameters": {
                "item_id": "item_123"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        response = add_rental(event, None)

        expected_response = {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"message": "Rental created successfully"})
        }

        self.assertEqual(response, expected_response)

    @patch("irentstuff_rental_add.get_item")
    @patch("irentstuff_rental_add.invoke_auth_lambda")
    def test_add_rental_invalid_token(self, mock_invoke_auth_lambda, mock_get_item):
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is invalid",
            "username": "test_user"
        }

        mock_get_item.return_value = {
            "availability": "available",
            "owner": "item_owner"
        }

        event = {
            "pathParameters": {
                "item_id": "item_123"
            },
            "headers": {
                "Authorization": "Bearer invalid_token"
            }
        }

        response = add_rental(event, None)

        expected_response = {
            "statusCode": 401,
            "headers": {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type', 'Content-Type': 'text/plain'
                },
            "body": "Your user token is invalid."
        }

        self.assertEqual(response, expected_response)

    @patch("irentstuff_rental_add.invoke_auth_lambda")
    @patch("irentstuff_rental_add.get_item")
    def test_add_rental_renting_own_item(self, mock_get_item, mock_invoke_auth_lambda):
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "item_owner"
        }

        mock_get_item.return_value = {
            "availability": "available",
            "owner": "item_owner"
        }

        event = {
            "pathParameters": {
                "item_id": "item_123"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        response = add_rental(event, None)

        expected_response = {
            "statusCode": 400,
            "headers": {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type', 'Content-Type': 'text/plain'
                },
            "body": "You cannot rent your own item."
        }

        self.assertEqual(response, expected_response)

    @patch("irentstuff_rental_add.invoke_auth_lambda")
    @patch("irentstuff_rental_add.get_item")
    def test_add_rental_item_not_available(self, mock_get_item, mock_invoke_auth_lambda):
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "test_user"
        }

        mock_get_item.return_value = {
            "availability": "active_rental",
            "owner": "item_owner"
        }

        event = {
            "pathParameters": {
                "item_id": "item_123"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        response = add_rental(event, None)

        expected_response = {
            "statusCode": 400,
            "headers": {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type', 'Content-Type': 'text/plain'
                },
            "body": "There are active rentals for this item. You cannot add a new rental."
        }

        self.assertEqual(response, expected_response)

    @patch("irentstuff_rental_add.invoke_auth_lambda")
    @patch("irentstuff_rental_add.get_item")
    @patch("irentstuff_rental_add.connect_to_db")
    @patch("irentstuff_rental_add.create_rental_entry")
    def test_add_rental_db_error(self, mock_create_rental_entry, mock_connect, mock_get_item, mock_invoke_auth_lambda):
        mock_invoke_auth_lambda.return_value = {
            "message": "Token is valid",
            "username": "test_user"
        }

        mock_get_item.return_value = {
            "availability": "available",
            "owner": "item_owner"
        }

        # Simulate a database connection error
        mock_connect.side_effect = Exception("Database connection error")

        event = {
            "pathParameters": {
                "item_id": "item_123"
            },
            "headers": {
                "Authorization": "Bearer valid_token"
            }
        }

        response = add_rental(event, None)

        expected_response = {
            "statusCode": 500,
            "headers": {"Content-Type": "text/plain"},
            "body": "An error occurred while adding the rental: Database connection error"
        }

        self.assertEqual(response, expected_response)
