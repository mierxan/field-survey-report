"""Run this file in PyCharm (right-click > Run 'test_mysql') to check the MySQL login."""
import db_mysql
ok, message = db_mysql.test_connection()
print("OK  " if ok else "FAILED  ", message)
