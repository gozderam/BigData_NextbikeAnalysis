from dash import Dash, dcc, html, Input, Output
import plotly.express as px
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import plotly.express as px
import datetime
import pymongo

DATABASE_NAME = 'bda'
CONNECTION_STRING = "mongodb://34.118.42.39:27017/"
API_ADRESS = 'https://api.nextbike.net/maps/nextbike-live.json'
COLLECTION_NAME = 'bikes_last'

# functions
def create_mong_client():
    client = pymongo.MongoClient(CONNECTION_STRING, directConnection=True,serverSelectionTimeoutMS = 60000)
    return client


def return_collecion(client,collection_name):
    # create database
    database = client[DATABASE_NAME]
    bikes = database[collection_name]
    return bikes

def get_data(collection,cityname):
    '''getting data about the bikes in a chosen city'''
    doc = collection.aggregate([
      {"$unwind":"$countries"},
      {"$unwind":"$countries.cities"}, 
      {"$match": {"countries.cities.name":cityname}},
      {"$unwind":"$countries.cities.places"},
      { "$project": { "countries.cities.places.uid": 1, "countries.cities.places.lat": 1,"countries.cities.places.lng": 1,"countries.cities.places.bikes_available_to_rent": 1,'timestamp':1}}
      
    ])
    df = pd.DataFrame.from_records(list(doc))
    new_df = pd.concat([pd.concat([pd.json_normalize(x) for x in df['countries']], ignore_index=True), df['timestamp']],axis =1, ignore_index=True)
    new_df.columns = ['uid','lat','lng','bikes_available_to_rent','timestamp']
    return new_df

def return_list(collection):
    """ list of all possible cities"""
    doc = collection.aggregate([
      {"$unwind":"$countries"},
      {"$unwind":"$countries.cities"},
      {'$project':{'countries.cities.name':1}}])
    df = pd.DataFrame.from_records(list(doc))
    df = pd.concat([pd.json_normalize(x) for x in df['countries']])
    return sorted(list(df['cities.name'])  )


# Dash app

app = Dash(__name__)

client = create_mong_client()
collection = return_collecion(client, COLLECTION_NAME)
cities = return_list(collection)

app.layout = html.Div([
    html.H4(f'Number of avaiable bikes in the chosen city'),
    html.P("Select a city:"),
    dcc.Dropdown(
        id='animations-x-selection',
        options=cities,
        value=cities[0]
    ),
    dcc.Loading(dcc.Graph(id="animations-x-graph"), type="cube"),
    dcc.Interval(
            id='interval-component',
            interval=1*30000, # in milliseconds
            n_intervals=0
        )
],style={'textAlign': 'center'})


@app.callback(
    Output("animations-x-graph", "figure"), 
    Input("animations-x-selection", "value"),
    Input('interval-component', 'n_intervals'))
def display_animated_graph(selection,interval):

    df = get_data(collection,selection)
    animations = {
        selection : px.scatter_mapbox(df, lat='lat',
                    lon='lng',title  = f'Last update {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                    size='bikes_available_to_rent',mapbox_style = "open-street-map",width=1200, height=600,zoom = 10)
    }
    return animations[selection]


if __name__ == "__main__":
    px.set_mapbox_access_token(open(".mapbox_token").read())
    
    app.run_server(debug=True)
