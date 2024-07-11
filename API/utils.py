import configparser
from sqlalchemy import create_engine


def get_postgres_engine(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    postgres = config['POSTGRES']
    engine = create_engine(
        f"postgresql+psycopg2://{postgres['User']}:{postgres['Password']}@{postgres['Host']}:{postgres['Port']}/{postgres['Dbname']}"
    )
    return engine