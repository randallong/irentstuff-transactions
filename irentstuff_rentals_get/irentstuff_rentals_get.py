"""Retrieve a Rental from the Rentals db"""

from decimal import Decimal

import json
import logging
import pymysql
import os
import requests
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
    
    
def response_headers(content_type: str):
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Content-Type': content_type
    }
    return headers
    
    
def retrieve_updated_rental(cursor, item_id, rental_id):
    retrieve_query = "SELECT * FROM Rentals WHERE item_id = %s AND rental_id = %s"
    cursor.execute(retrieve_query, (item_id, rental_id))
    rental = cursor.fetchone()
    log.info(rental)
    
    if rental:
        response = {
            "rental_id": rental["rental_id"],
            "owner_id": rental["owner_id"],
            "renter_id": rental["renter_id"],
            "item_id": rental["item_id"],
            "start_date": rental["start_date"].isoformat() if isinstance(rental["start_date"], date) else rental["start_date"],
            "end_date": rental["end_date"].isoformat() if isinstance(rental["end_date"], date) else rental["end_date"],
            "status": rental["status"],
            "price_per_day": float(rental["price_per_day"]) if isinstance(rental["price_per_day"], Decimal) else rental["price_per_day"],
            "deposit": float(rental["deposit"]) if isinstance(rental["deposit"], Decimal) else rental["deposit"],
            "created_at": rental["created_at"].isoformat() if isinstance(rental["created_at"], (datetime, date)) else rental["created_at"],
            "updated_at": rental["updated_at"].isoformat() if isinstance(rental["updated_at"], (datetime, date)) else rental["updated_at"]
        }
        return response
    else:
        return {"error": "Rental not found"}


def get_rentals(event, context):
    log.info(event)
    transactions_conn = connect_to_db()

    path_params = event.get('pathParameters', {})
    item_id = path_params.get('item_id')
    rental_id = path_params.get('rental_id')  # rental_id is not compulsory
    log.info(f"{item_id=}, {rental_id=}")

    # Get the query type, 'latest' or 'all'. If no query type is provided, defaults to "all"
    query_params = event.get("queryStringParameters", {})
    query_type = query_params.get("type", "all") if query_params else "all"
    log.info(f"item_id: {item_id}, rental_id: {rental_id}, query_type: {query_type}")

    try:
        with transactions_conn.cursor(pymysql.cursors.DictCursor) as cursor:
            if rental_id:
                # Fetch the specific rental by rental_id and item_id
                select_query = "SELECT * FROM Rentals WHERE item_id = %s AND rental_id = %s"
                cursor.execute(select_query, (item_id, rental_id))
            elif query_type == 'latest':
                select_query = """
                    SELECT * FROM Rentals
                    WHERE item_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """
                cursor.execute(select_query, (item_id,))
            else:
                # Fetch all rentals for the given item_id
                select_query = "SELECT * FROM Rentals WHERE item_id = %s"
                cursor.execute(select_query, (item_id,))
            
            rentals = cursor.fetchall()
            log.info(rentals)
            
            # Format the response
            if rentals:
                response = [retrieve_updated_rental(cursor, rental["item_id"], rental["rental_id"]) for rental in rentals]
            else:
                response = {"message": "No rentals found"}
            
            return {
                "statusCode": 200,
                "headers": response_headers('application/json'),
                "body": json.dumps(response)
            }
    except pymysql.MySQLError as e:
        return {
            "statusCode": 500,
            "headers": response_headers('text/plain'),
            "body": f"An error occurred while retrieving the rentals: {str(e)}"
        }
    finally:
        transactions_conn.close()