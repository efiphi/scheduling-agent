# Shared pytest fixtures for every workspace member. The database fixtures live in the db
# package so the db tests and the google-gateway tests connect the same way; the Redis
# fixture lives with the gateway tests (on the pytest pythonpath).
pytest_plugins = ["db.testing", "gateway_redis"]
