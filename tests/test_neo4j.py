from neo4j import GraphDatabase

# URI examples: "neo4j://localhost", "neo4j+s://xxx.databases.neo4j.io"
URI = "neo4j+s://303ba842.databases.neo4j.io"
AUTH = ("303ba842", "<OdTlYVsWoQJQyTwsi2trxq_5sfHFtx0S0aGBWqLrjGQ>")

with GraphDatabase.driver(URI, auth=AUTH) as driver:
    driver.verify_connectivity()