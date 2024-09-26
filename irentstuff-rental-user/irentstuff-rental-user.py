"""Retrieve rentals related to a user from the Rentals table in the Transactions DB"""

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


def response_headers(content_type: str):
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Content-Type': content_type
    }
    return headers


def get_user_rentals(event, context):
    log.info(event)
    transactions_conn = connect_to_db()

    user_id = event["pathParameters"]["user_id"]
    query_params = event.get("queryStringParameters", {})
    as_role = query_params.get("as", {}) if query_params else None
    log.info(f"Getting all rentals as {as_role} for {user_id}")

    try:
        with transactions_conn.cursor(pymysql.cursors.DictCursor) as cursor:
            if user_id:
                if as_role == "owner":
                    select_query = "SELECT * FROM Rentals WHERE owner_id = %s"
                    cursor.execute(select_query, user_id)
                elif as_role == "renter":
                    select_query = "SELECT * FROM Rentals WHERE renter_id = %s"
                    cursor.execute(select_query, user_id)
                else:
                    return {
                        "statusCode": 400,
                        "headers": response_headers("text/plain"),
                        "body": f"Unable to get rentals related to {user_id}. 'as' query string should be 'owner' or 'renter'."
                    }

                rentals = cursor.fetchall()

                if rentals:
                    for rental in rentals:
                        log.info(rental)

                    return {
                        "statusCode": 200,
                        "headers": response_headers("application/json"),
                        "body": json.dumps(rentals, default=str)  # default=str handles date/decimal formatting
                    }
                else:
                    return {
                        "statusCode": 200,
                        "headers": response_headers("application/json"),
                        "body": json.dumps([])  # Return an empty array if no rentals found
                    }
    except pymysql.MySQLError as e:
        return {
            "statusCode": 500,
            "headers": response_headers("text/plain"),
            "body": f"An error occurred while retrieving the rentals: {str(e)}"
        }
    finally:
        transactions_conn.close()
