from neo4j import GraphDatabase

from app.config import Config


class GraphDB:

	def __init__(self, config: Config) -> None:
		self.config = config
		self.driver = GraphDatabase.driver(uri=config.neo4j_config.url, auth=(config.neo4j_config.user, config.neo4j_config.password))

	def close(self) -> None:
		self.driver.close()