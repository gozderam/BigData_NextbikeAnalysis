import pandas as pd
import argparse
import get_data_from_api
import logging
from utils import get_postgres_engine


def add_timestamp_to_dict(result):
    timestamp = result.get('timestamp', pd.to_datetime('1970-01-01 00:00'))
    result_list = result['countries']['cities']['places']
    city_uid = result['countries']['cities']['uid']
    city_name = result['countries']['cities']['name']
    country = result['countries']['country_name']
    for d in result_list:
        d['timestamp'] = timestamp
        d['country_name'] = country
        d['city_uid'] = city_uid
        d['city_name'] = city_name
    return result_list


def add_related_columns(nextbike_results_df):
    df = nextbike_results_df.sort_values(['uid', 'timestamp']).reset_index(drop=True)
    df['bike_numbers_shifted'] = df['bike_numbers'].shift(1).combine(df['bike_numbers'],
                                                                     (lambda x, y: x if isinstance(x, list) else y))
    df['timestamp_shifted'] = df['timestamp'].shift(1, fill_value=pd.to_datetime('1970-01-01 00:00'))
    df['uid_shifted'] = df['uid'].shift(1, fill_value=-1)
    return df


def calculate_usage(df_with_columns, minutes_interval_to_validate=10):
    s1 = set(df_with_columns['bike_numbers'])
    s2 = set(df_with_columns['bike_numbers_shifted'])
    time_diff_validation = (df_with_columns['timestamp'] - df_with_columns['timestamp_shifted']) <\
                           pd.Timedelta(minutes=minutes_interval_to_validate)
    return_dict = {'timestamp_start': df_with_columns['timestamp_shifted'],
                   'timestamp_end': df_with_columns['timestamp'],
                   'uid': df_with_columns['uid'],
                   'city_uid': df_with_columns['city_uid'],
                   'city_name': df_with_columns['city_name'],
                   'country_name': df_with_columns['country_name'],
                   'lat': df_with_columns['lat'],
                   'lng': df_with_columns['lng']}
    if df_with_columns['uid'] == df_with_columns['uid_shifted']:
        return_dict.update({'returned': len(s1-s2), 'collected': len(s2-s1), 'valid': time_diff_validation})
    else:
        return_dict.update({'returned': -1, 'collected': -1, 'valid': False})
    return return_dict


def main(db, engine, cityuid):
    logging.warning('Collecting data from mongo')
    mongo_src = db.bikes.aggregate([
        {"$unwind": "$countries"},
        {"$unwind": "$countries.cities"},
        {"$match":
             {"countries.cities.uid": {"$in": cityuid}}
         }
    ])
    df = pd.concat([pd.DataFrame(add_timestamp_to_dict(doc)) for doc in mongo_src])
    logging.warning(f'Data collected - {len(df)} rows')
    logging.warning('Data transformation')
    df_columns = add_related_columns(df)
    logging.warning('Dataframe update')
    df_usage = df_columns.apply(calculate_usage, axis=1, result_type='expand')
    df_usage = df_usage.loc[df_usage['valid']].rename(columns={'uid': 'placeguid'})
    df_usage = df_usage[['timestamp_start', 'timestamp_end', 'placeguid', 'country_name', 'city_uid',
                         'city_name', 'lat', 'lng', 'returned', 'collected']]
    logging.warning(f'Uploading {len(df_usage)} rows to the database')
    try:
        df_usage.to_sql(
            'intervals_usage',
            engine,
            if_exists='append',
            chunksize=1000,
            index=False,
            method='multi'
        )
    except Exception as e:
        logging.warning(e)
    logging.warning('Data uploaded')


if __name__ == '__main__':
    FORMAT = '%(asctime)s %(message)s'
    logging.basicConfig(format=FORMAT)

    parser = argparse.ArgumentParser()
    parser.add_argument('--cityuid', type=int, nargs='*')
    parser.add_argument('--postgres_config_file', type=str, nargs='?')
    args = parser.parse_args()
    client = get_data_from_api.create_mong_client()
    source_database_client = client['bda']

    target_database_engine = get_postgres_engine(args.postgres_config_file)
    main(source_database_client, target_database_engine, args.cityuid)
