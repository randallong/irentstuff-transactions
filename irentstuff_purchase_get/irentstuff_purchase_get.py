"""Retrieve a Purchase from the Purchases db"""

from decimal import Decimal

import json
import logging
import pymysql
import os
import sys

from pymysql.cursors import DictCursor
from datetime import datetime, date

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


def retrieve_updated_purchase(cursor, item_id, purchase_id):
    retrieve_query = "SELECT * FROM Purchases WHERE item_id = %s AND purchase_id = %s"
    cursor.execute(retrieve_query, (item_id, purchase_id))
    purchase = cursor.fetchone()
    log.info(purchase)

    if purchase:
        response = {
            "purchase_id": purchase["purchase_id"],
            "created_at": purchase["created_at"].isoformat() if isinstance(purchase["created_at"], (datetime, date)) else purchase["created_at"],
            "owner_id": purchase["owner_id"],
            "buyer_id": purchase["buyer_id"],
            "item_id": purchase["item_id"],
            "purchase_date": purchase["purchase_date"].isoformat() if isinstance(purchase["purchase_date"], date) else purchase["purchase_date"],
            "status": purchase["status"],
            "purchase_price": float(purchase["purchase_price"]) if isinstance(purchase["purchase_price"], Decimal) else purchase["purchase_price"],
            }
        return response
    else:
        return {"error": "Purchase not found"}


def get_purchase(event, context):
    transactions_conn = connect_to_db()

    item_id = event.get('pathParameters', {}).get('item_id')
    purchase_id = event.get('pathParameters', {}).get('purchase_id')
    log.info(f"item_id: {item_id}, purchase_id: {purchase_id}")

    if not item_id or not purchase_id:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({"error": "Missing item_id or purchase_id"})
        }

    try:
        with transactions_conn.cursor(pymysql.cursors.DictCursor) as cursor:
            response = retrieve_updated_purchase(cursor, item_id, purchase_id)

            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": json.dumps(response)
            }

    except pymysql.MySQLError as e:
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Content-Type": "text/plain"
            },
            "body": f"An error occurred while retrieving the purchase status: {str(e)}"
        }
    finally:
        if transactions_conn:
            transactions_conn.close()
