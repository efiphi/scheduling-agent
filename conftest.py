# Shared pytest fixtures for every workspace member. The database fixtures live in the db
# package so the db tests and the google-gateway tests connect the same way.
pytest_plugins = ["db.testing"]
