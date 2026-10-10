import sqlite3
import os

DB_PATH = 'data/notki.sqlite3'
def initialize_database():
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute('ALTER TABLE users ADD COLUMN tags TEXT')
        print("tags column added")
    except sqlite3.OperationalError:
        print("tags column already exists")

initialize_database()
