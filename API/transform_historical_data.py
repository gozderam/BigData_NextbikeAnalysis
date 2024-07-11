import pandas as pd
import os
import logging
import argparse
import meteostat
from utils import get_postgres_engine


def load_data(dir_path, city_uids):
    bikes_data = pd.read_csv(os.path.join(dir_path, 'bike_list.csv'))
    bikes_data['appeared'] = pd.to_datetime(bikes_data['appeared'], format='%Y-%m-%d %H:%M:%S')
    bikes_data['disappeared'] = pd.to_datetime(bikes_data['disappeared'], format='%Y-%m-%d %H:%M:%S')
    places = pd.read_csv(os.path.join(dir_path, 'places.csv'))
    places = places.loc[(places['lat'].abs() <= 90) & (places['lng'].abs() <= 180)]
    cities = pd.read_csv(os.path.join(dir_path, 'cities.csv'))
    cities = cities.loc[cities.uid.isin(city_uids)]
    countries = pd.read_csv(os.path.join(dir_path, 'countries.csv'))
    cities_countries = cities.merge(countries[['guid', 'country_name']], left_on='countryguid', right_on='guid',
                                    how='left', suffixes=['', '_country'])
    places_cities_countries = places.merge(cities_countries[['guid', 'uid', 'name', 'country_name']], left_on='cityguid',
                                           right_on='guid', suffixes=['', '_cities']).rename(
        columns={'uid_cities': 'city_uid', 'name_cities': 'city_name'})
    places_cities_countries = places_cities_countries[['guid', 'uid', 'lat', 'lng', 'city_uid',
                                                       'city_name', 'country_name']].rename(columns={'guid': 'placeguid'})
    return bikes_data, places_cities_countries


def aggregate_data(df, group_cols, series_name):
    s = df.groupby(group_cols).size()
    s.name = series_name
    return s.reset_index()


def get_weather_data(lat, lng, start, end, city_name, city_uid):
    point = meteostat.Point(lat, lng)
    weather_data = meteostat.Hourly(point, start, end)
    weather_data = weather_data.fetch()
    weather_data['city_name'] = city_name
    weather_data['city_uid'] = city_uid
    return weather_data


def main(folder, engine, city_uids):
    logging.warning('Loading data')
    bikes_data, places = load_data(folder, city_uids)
    all_data = bikes_data.merge(places, on='placeguid')

    logging.warning('Data transformations')
    for col in ['appeared', 'disappeared']:
        all_data[f'{col}_rounded'] = all_data[col].dt.round('5min')
    # logging.warning(len(all_data))
    returns = aggregate_data(all_data, ['appeared_rounded', 'placeguid', 'lat', 'lng', 'city_uid',
                                          'city_name', 'country_name'], 'returned')
    collections = aggregate_data(all_data, ['disappeared_rounded', 'placeguid', 'lat', 'lng', 'city_uid',
                                              'city_name', 'country_name'], 'collected')

    data = collections.merge(returns, left_on=['placeguid', 'disappeared_rounded'],
                             right_on=['placeguid', 'appeared_rounded'], how='outer')
    for col_out, col1, col2 in zip(['timestamp', 'lat', 'lng', 'city_uid', 'city_name', 'country_name'],
                                   ['appeared_rounded', 'lat_x', 'lng_x', 'city_uid_x', 'city_name_x', 'country_name_x'],
                                   ['disappeared_rounded', 'lat_y', 'lng_y', 'city_uid_y', 'city_name_y', 'country_name_y']):
        data[col_out] = data[col1].fillna(data[col2])

    data['collected'] = data['collected'].fillna(0)
    data['returned'] = data['returned'].fillna(0)

    data['timestamp_start'] = data['timestamp'] - pd.Timedelta(minutes=2, seconds=30)
    data['timestamp_end'] = data['timestamp'] + pd.Timedelta(minutes=2, seconds=30)

    data = data[['timestamp_start', 'timestamp_end', 'placeguid', 'lat', 'lng', 'returned', 'collected', 'city_uid', 'city_name', 'country_name']]

    logging.warning(f'Saving {len(data)} rows to db')
    data.to_sql(
        'intervals_usage',
        engine,
        if_exists='append',
        chunksize=1000,
        index=False,
        method='multi'
    )
    logging.warning('Weather data')
    city_coords = data.groupby(['city_uid', 'city_name']).agg({'lat': 'mean', 'lng': 'mean',
                                                               'timestamp_start': 'min',
                                                               'timestamp_end': 'max'}).reset_index()
    for i, row in city_coords.iterrows():
        weather_data = get_weather_data(row['lat'], row['lng'], row['timestamp_start'],
                                        row['timestamp_end'], row['city_name'], row['city_uid'])
        logging.warning(f'Saving {len(weather_data)} rows to db')
        weather_data.to_sql(
            'weather_data',
            engine,
            if_exists='append',
            chunksize=1000,
            method='multi'
        )

    logging.warning('Finished')


if __name__ == '__main__':

    FORMAT = '%(asctime)s %(message)s'
    logging.basicConfig(format=FORMAT)

    parser = argparse.ArgumentParser()
    parser.add_argument('--data_folder', type=str, nargs='?')
    parser.add_argument('--postgres_config_file', type=str, nargs='?')
    parser.add_argument('--city_uids', type=int, nargs='*')
    args = parser.parse_args()
    engine = get_postgres_engine(args.postgres_config_file)
    main(args.data_folder, engine, args.city_uids)


