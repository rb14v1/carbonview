import sys


try:
	__import__("pysqlite3")
except ImportError:
	pass
else:
	sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
