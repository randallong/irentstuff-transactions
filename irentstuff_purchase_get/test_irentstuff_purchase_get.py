import json
import os
import pymysql

from datetime import date, datetime
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch, MagicMock

from irentstuff_purchase_get import (
    connect_to_db,
    retrieve_updated_purchase,
    get_purchase
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


class TestRetrieveUpdatedPurchase(TestCase):

    def setUp(self):
        self.mock_cursor = MagicMock()

    def test_retrieve_updated_purchase_success(self):
        # Arrange
        item_id = "item_123"
        purchase_id = "purchase_456"
        mock_purchase = {
            "purchase_id": "purchase_456",
            "created_at": datetime(2023, 10, 1, 12, 30),
            "owner_id": "owner_789",
            "buyer_id": "buyer_101",
            "item_id": "item_123",
            "purchase_date": date(2023, 10, 1),
            "status": "completed",
            "purchase_price": Decimal("99.99")
        }

        # Mock fetchone to return a purchase
        self.mock_cursor.fetchone.return_value = mock_purchase

        # Act
        result = retrieve_updated_purchase(self.mock_cursor, item_id, purchase_id)

        # Assert
        expected_response = {
            "purchase_id": "purchase_456",
            "created_at": "2023-10-01T12:30:00",
            "owner_id": "owner_789",
            "buyer_id": "buyer_101",
            "item_id": "item_123",
            "purchase_date": "2023-10-01",
            "status": "completed",
            "purchase_price": 99.99
        }
        self.assertEqual(result, expected_response)
        self.mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM Purchases WHERE item_id = %s AND purchase_id = %s",
            (item_id, purchase_id)
        )

    def test_retrieve_updated_purchase_not_found(self):
        # Arrange
        item_id = "item_123"
        purchase_id = "purchase_456"

        # Mock fetchone to return None
        self.mock_cursor.fetchone.return_value = None

        # Act
        result = retrieve_updated_purchase(self.mock_cursor, item_id, purchase_id)

        # Assert
        expected_response = {"error": "Purchase not found"}
        self.assertEqual(result, expected_response)
        self.mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM Purchases WHERE item_id = %s AND purchase_id = %s",
            (item_id, purchase_id)
        )


class TestGetPurchase(TestCase):

    @patch("irentstuff_purchase_get.connect_to_db")
    @patch("irentstuff_purchase_get.retrieve_updated_purchase")
    def test_get_purchase_success(self, mock_retrieve, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        event = {
            "pathParameters": {
                "item_id": "item_123",
                "purchase_id": "purchase_456"
            }
        }
        context = {}

        # Mock the retrieve_updated_purchase function to return a valid response
        mock_retrieve.return_value = {
            "purchase_id": "purchase_456",
            "created_at": "2023-10-01T12:30:00",
            "owner_id": "owner_789",
            "buyer_id": "buyer_101",
            "item_id": "item_123",
            "purchase_date": "2023-10-01",
            "status": "completed",
            "purchase_price": 99.99
        }

        # Act
        response = get_purchase(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertEqual(json.loads(response["body"]), mock_retrieve.return_value)

        mock_retrieve.assert_called_once_with(mock_cursor, "item_123", "purchase_456")
        mock_conn.close.assert_called_once()

    @patch("irentstuff_purchase_get.connect_to_db")
    @patch("irentstuff_purchase_get.retrieve_updated_purchase")
    def test_get_purchase_db_error(self, mock_retrieve, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = pymysql.MySQLError("Database error")
        mock_connect.return_value = mock_conn

        event = {
            "pathParameters": {
                "item_id": "item_123",
                "purchase_id": "purchase_456"
            }
        }
        context = {}

        # Act
        response = get_purchase(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(response["headers"]["Content-Type"], "text/plain")
        self.assertIn("An error occurred while retrieving the purchase status: Database error", response["body"])

        # Check if the connection was closed after the error
        mock_conn.close.assert_called_once()

    @patch("irentstuff_purchase_get.connect_to_db")
    @patch("irentstuff_purchase_get.retrieve_updated_purchase")
    def test_get_purchase_no_item_or_purchase_id(self, mock_retrieve, mock_connect):
        # Arrange
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        # Mock retrieve_updated_purchase to return a valid response
        mock_retrieve.return_value = {
            "error": "Purchase not found"
        }

        event = {
            "pathParameters": {}
        }
        context = {}

        # Act
        response = get_purchase(event, context)

        # Assert
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertIn("Missing item_id or purchase_id", response["body"])

        # Ensure no DB calls were made as the IDs were missing
        mock_conn.cursor.assert_not_called()
