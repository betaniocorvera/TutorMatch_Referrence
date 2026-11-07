# ============================================================
# db.py — MySQL helpers
#
# Rules for this file:
#   1. Every value goes through the `params` tuple.
#   2. Never build SQL with f-strings or string concatenation.
#      That is how SQL injection happens.
#   3. Connections are short-lived. Open, use, close.
# ============================================================

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor

load_dotenv(Path(__file__).resolve().parent / ".env")


def get_connection():
    """Open one MySQL connection with dictionary rows."""
    connection = pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "tutormatch"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )

    # Store every DATETIME in UTC so timestamps are consistent.
    with connection.cursor() as cursor:
        cursor.execute("SET time_zone = '+00:00'")

    return connection


def query_one(sql, params=()):
    """Run a SELECT and return the first row, or None."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    finally:
        connection.close()


def query_all(sql, params=()):
    """Run a SELECT and return all rows as a list of dictionaries."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    finally:
        connection.close()


def execute(sql, params=()):
    """Run INSERT/UPDATE/DELETE, commit, and return lastrowid."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            connection.commit()
            return cursor.lastrowid
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def test_connection():
    """Return True when MySQL is reachable."""
    try:
        row = query_one("SELECT 1 AS ok")
        return bool(row and row["ok"] == 1)
    except Exception:
        return False
