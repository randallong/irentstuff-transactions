import json
import os
import pymysql

from unittest import TestCase
from unittest.mock import patch, MagicMock
from irentstuff_purchase_user import (
    connect_to_db,
    response_header,
    get_user_purchases
)


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
            connect_timeout=5,
            cursorclass=pymysql.cursors.DictCursor
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


class TestResponseHeader:
    def test_response_header(self):
        # Test case for when content_type is 'application/json'
        content_type = "application/json"
        expected_header = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_header(content_type)
        assert result == expected_header
        assert result['Content-Type'] == 'application/json'

    def test_response_header_text(self):
        # Test case for when content_type is 'text/html'
        content_type = "text/html"
        expected_header = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Content-Type': content_type
        }

        result = response_header(content_type)
        assert result == expected_header
        assert result['Content-Type'] == 'text/html'


class TestGetUserPurchases(TestCase):
    @patch("irentstuff_purchase_user.connect_to_db")
    def test_get_user_purchases_success_as_owner(self, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        user_id = "test_owner_id"
        purchases_data = [{"purchase_id": 1, "item_name": "Test Item", "owner_id": user_id}]
        mock_cursor.fetchall.return_value = purchases_data

        event = {
            "pathParameters": {"user_id": user_id},
            "queryStringParameters": {"as": "owner"}
        }
        context = {}

        # Act
        response = get_user_purchases(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), purchases_data)

        mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM Purchases WHERE owner_id = %s", user_id
        )
        mock_conn.close.assert_called_once()

    @patch("irentstuff_purchase_user.connect_to_db")
    def test_get_user_purchases_success_as_buyer(self, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        user_id = "test_buyer_id"
        purchases_data = [{"purchase_id": 2, "item_name": "Test Item 2", "buyer_id": user_id}]
        mock_cursor.fetchall.return_value = purchases_data

        event = {
            "pathParameters": {"user_id": user_id},
            "queryStringParameters": {"as": "buyer"}
        }
        context = {}

        # Act
        response = get_user_purchases(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), purchases_data)

        mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM Purchases WHERE buyer_id = %s", user_id
        )
        mock_conn.close.assert_called_once()

    @patch("irentstuff_purchase_user.connect_to_db")
    def test_get_user_purchases_no_purchases(self, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        user_id = "test_owner_id"
        mock_cursor.fetchall.return_value = []  # Simulate no purchases found

        event = {
            "pathParameters": {"user_id": user_id},
            "queryStringParameters": {"as": "owner"}
        }
        context = {}

        # Act
        response = get_user_purchases(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), [])  # Expecting an empty array

        mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM Purchases WHERE owner_id = %s", user_id
        )
        mock_conn.close.assert_called_once()

    @patch("irentstuff_purchase_user.connect_to_db")
    def test_get_user_purchases_invalid_role(self, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        user_id = "test_user_id"
        event = {
            "pathParameters": {"user_id": user_id},
            "queryStringParameters": {"as": "invalid_role"}
        }
        context = {}

        # Act
        response = get_user_purchases(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 400)
        self.assertIn("Unable to get purchases related to", response["body"])

        mock_conn.close.assert_called_once()

    @patch("irentstuff_purchase_user.connect_to_db")
    def test_get_user_purchases_db_error(self, mock_connect):
        # Mock the connection and cursor
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Mock cursor to raise an exception
        mock_conn.cursor.side_effect = pymysql.MySQLError("Database error")

        event = {
            "pathParameters": {"user_id": "test_user_id"},
            "queryStringParameters": {"as": "owner"}
        }
        context = {}

        response = get_user_purchases(event, context)

        self.assertEqual(response["statusCode"], 500)
        self.assertIn("An error occurred while retrieving the purchases:", response["body"])
