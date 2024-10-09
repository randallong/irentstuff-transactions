"""Retrieve purchases related to a user from the Purchases table in the Transactions DB"""

import json
import logging
import pymysql
import os
import sys
from pymysql.cursors import DictCursor

log = logging.getLogger()
log.setLevel(logging.INFO)


def connect_to_db():
    "Connect to Transactions DB"
    transactions_conn = None
    transactions_db_user_name = os.environ["DB1_USER_NAME"]
    transactions_db_password = os.environ["DB1_PASSWORD"]
    transactions_db_rds_proxy_host = os.environ["DB1_RDS_PROXY_HOST"]
    transactions_db_name = os.environ["DB1_NAME"]

    try:
        transactions_conn = pymysql.connect(
            host=transactions_db_rds_proxy_host,
            user=transactions_db_user_name,
            passwd=transactions_db_password,
            db=transactions_db_name,
            connect_timeout=5,
            cursorclass=DictCursor
        )
        log.info("SUCCESS: Connection to Transactions DB succeeded")
    except pymysql.MySQLError as e:
        log.error("ERROR: Unexpected error: Could not connect to MySQL instance.")
        log.error(e)
        sys.exit(1)
    return transactions_conn


def response_header(content_type: str):
    header = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": content_type
    }
    return header


def get_user_purchases(event, context):
    log.info(event)
    transactions_conn = connect_to_db()

    user_id = event["pathParameters"]["user_id"]
    query_params = event.get("queryStringParameters", {})
    as_role = query_params.get("as", {}) if query_params else None
    log.info(f"Getting all purchases as {as_role} for {user_id}")

    try:
        with transactions_conn.cursor(pymysql.cursors.DictCursor) as cursor:
            if user_id:
                if as_role == "owner":
                    select_query = "SELECT * FROM Purchases WHERE owner_id = %s"
                    cursor.execute(select_query, user_id)
                elif as_role == "buyer":
                    select_query = "SELECT * FROM Purchases WHERE buyer_id = %s"
                    cursor.execute(select_query, user_id)
                else:
                    return {
                        "statusCode": 400,
                        "headers": response_header('text/plain'),
                        "body": f"Unable to get purchases related to {user_id}. 'as' query string should be 'owner' or 'buyer'."
                    }

                purchases = cursor.fetchall()

                if purchases:
                    for purchase in purchases:
                        log.info(purchase)

                    return {
                        "statusCode": 200,
                        "headers": response_header('application/json'),
                        "body": json.dumps(purchases, default=str)  # default=str handles date/decimal formatting
                    }
                else:
                    return {
                        "statusCode": 200,
                        "headers": response_header('application/json'),
                        "body": json.dumps([])  # Return an empty array if no rentals found
                    }
    except pymysql.MySQLError as e:
        return {
            "statusCode": 500,
            "headers": response_header('text/plain'),
            "body": f"An error occurred while retrieving the purchases: {str(e)}"
        }
    finally:
        transactions_conn.close()
