import pandas as pd
import json
import requests
import folium
from folium.features import GeoJsonTooltip

from bokeh.models import ColumnDataSource, FactorRange, HoverTool
from bokeh.transform import cumsum
from bokeh.plotting import figure
from math import pi

import panel as pn
import osmnx as ox


file_path = '/data/cancer.csv'
data = pd.read_csv(file_path)


def geocode_state(state_name):
    try:
        # Get the latitude and longitude using osmnx
        location = ox.geocode(state_name)
        return location[0], location[1]  # latitude, longitude
    except Exception as e:
        print(f"Error geocoding {state_name}: {e}")
        return None, None
# Ensure the DataFrame has a 'State' column and geocode
if 'State' in data.columns:
    data[['Latitude', 'Longitude']] = data['State'].apply(lambda x: geocode_state(x)).apply(pd.Series)
else:
    print("Error: No 'State' column found in the CSV file.")

url = 'https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json'
states_geojson = json.loads(requests.get(url).text)

# Integrate 'Total.Number' and age-specific rates into the GeoJSON features
age_columns = ['Rates.Age.< 18', 'Rates.Age.18-45', 'Rates.Age.45-64', 'Rates.Age.> 64']
for feature in states_geojson['features']:
    state_name = feature['properties']['name']
    state_data = data[data['State'] == state_name].iloc[0] if not data[data['State'] == state_name].empty else None
    feature['properties']['Total.Number'] = state_data['Total.Number'] if state_data is not None else 0
    feature['properties']['Total.Population'] = state_data['Total.Population'] if state_data is not None else 0
    for col in age_columns:
        feature['properties'][col] = state_data[col] if state_data is not None and col in state_data else 0


# Initialize Panel with necessary extensions
pn.extension()

state_options = ['All'] + sorted(data['State'].dropna().unique().tolist())
state_selector = pn.widgets.Select(name='State', options=state_options, value='All', width_policy='max')


def create_map(selected_state):
    center = [50, -115]
    zoom_start = 3
    m = folium.Map(location=center, zoom_start=zoom_start, tiles='CartoDB positron')

    # Add a Choropleth layer and GeoJson for tooltips
    choropleth = folium.Choropleth(
        geo_data=states_geojson,
        name='choropleth',
        data=data,
        columns=['State', 'Total.Number'],
        key_on='feature.properties.name',
        fill_color='OrRd',
        fill_opacity=0.9,
        line_opacity=0.2,
        legend_name='Cancer Deaths'
    ).add_to(m)

    folium.GeoJson(
        data=states_geojson,
        style_function=lambda feature: {'fillColor': '#transparent', 'color': '#transparent', 'fillOpacity': 0,
                                        'weight': 0},  # Make transparent
        highlight_function=lambda x: {'weight': 0, 'fillColor': 'transparent', 'color': 'transparent',
                                      'weight': 0},
        tooltip=GeoJsonTooltip(
            fields=['name', 'Total.Population', 'Total.Number'],
            aliases=['State:', 'Cumulative Population:', 'Total Deaths:'],
            localize=True
        ),
        clickable=False

    ).add_to(m)

    if selected_state != 'All':
        state_geo = next(
            (feat for feat in states_geojson['features'] if feat['properties']['name'] == selected_state), None)
        if state_geo:
            style_function = lambda feature: {
                'fillColor': choropleth.color_scale(feature['properties']['Total.Number']),
                'color': 'red',
                'weight': 2,
                'dashArray': '5, 5',
                'fillOpacity': 0.9
            }
            selected_state_geojson = folium.GeoJson(
                data=state_geo,
                style_function=style_function,
                tooltip=GeoJsonTooltip(
                    fields=['name', 'Total.Population', 'Total.Number'] + age_columns,
                    aliases=['State:', 'Cumulative Population', 'Total Cancer Deaths:'] + [
                        'Rates(per 100,000) under 18 Age:', 'Rates(per 100,000) from 18 to 45:',
                        'Rates(per 100,000) from 45 to 64:', 'Rates(per 100,000) over 64 Age:'],
                    localize=True
                )
            )
            selected_state_geojson.add_to(m)
            m.fit_bounds(selected_state_geojson.get_bounds())

    return m._repr_html_()


def create_pie_chart(selected_state):
    df = data.copy()
    # Filter data for the selected state or use all states
    if selected_state != 'All':
        df = df[df['State'] == selected_state]
    else:
        num_states = len(df['State'].unique())

    # Create a mapping of the types to more friendly names
    type_to_name = {
        'Types.Breast.Total': 'Breast Cancer',
        'Types.Colorectal.Total': 'Colorectal Cancer',
        'Types.Lung.Total': 'Lung Cancer'
    }

    # Update the cancer_types with the friendly names
    cancer_types = [type_to_name[typ] for typ in type_to_name.keys()]
    counts = [int(df[typ].sum()) for typ in type_to_name.keys()]  # Ensure counts are integers
    if selected_state == 'All':
        # Calculate average counts per state if 'All' is selected
        counts = [int(df[typ].sum() / num_states) for typ in type_to_name.keys()]
    else:
        counts = [int(df[typ].sum()) for typ in
                  type_to_name.keys()]  # Ensure counts are integers for selected state

    # Convert counts to angle
    data_for_pie = pd.DataFrame({'cancer_types': cancer_types, 'counts': counts})
    data_for_pie['angle'] = data_for_pie['counts'] / data_for_pie['counts'].sum() * 2 * pi

    # Define a custom palette
    type_palette = ['#FAD5A5', '#7E0202', '#A36A00']

    data_for_pie['color'] = type_palette[:len(cancer_types)]

    source = ColumnDataSource(data_for_pie)

    hover = HoverTool(tooltips=[("Type", "@cancer_types"), (
        "Rate(per 100,000)", "@counts{0,0}")])  # The format here should show the actual count

    p = figure(height=450,
               title=f"Type in {selected_state}" if selected_state != 'All' else "Type for All States",
               toolbar_location=None, tools=[hover], x_range=(-0.5, 1.0))

    p.wedge(x=0, y=1, radius=0.4,
            start_angle=cumsum('angle', include_zero=True), end_angle=cumsum('angle'),
            line_color="white", fill_color='color', legend_field='cancer_types', source=source)

    p.axis.axis_label = None
    p.axis.visible = False
    p.grid.grid_line_color = None

    # Position and style the legend
    p.legend.location = "bottom_right"
    p.legend.orientation = "vertical"
    p.legend.label_text_font_size = '10pt'  # Adjust font size
    p.legend.padding = 2  # Decrease padding to move legend closer
    p.legend.margin = 2  # Decrease margin to move legend closer

    return p


# Define categories and races for the bar chart
races = ['White', 'Hispanic', 'Asian', 'Black', 'Indigenous']
genders = ['Female', 'Male']

female_palette = {
    'Hispanic': '#B30000',
    'White': '#7E0202',
    'Indigenous': '#ffbfbf',
    'Asian': '#DA7070',
    'Black': '#ce8686'
}
male_palette = {
    'Hispanic': '#D18700',
    'White': '#754C00',
    'Indigenous': '#FFE5B4',
    'Asian': '#FFB52E',
    'Black': '#A36A00'
}


def create_nested_bars(selected_state):
    df = data.copy()
    # Filter data for the selected state or use all states
    if selected_state != 'All':
        df = df[df['State'] == selected_state]
    else:
        num_states = len(df['State'].unique())
    # Calculate the sums for each race and gender
    rows = []
    for race in races:
        for gender in genders:
            count = df[f'Rates.Race and Sex.{gender}.{race}'].sum()
            if selected_state == 'All' and num_states > 0:
                count /= num_states  # Calculate the average count per state
            rows.append({
                'Gender': gender,
                'Race': race,
                'Count': count,
                'Color': male_palette[race] if gender == 'Male' else female_palette[race]
                # Assign color based on gender
            })
    df = pd.DataFrame(rows)
    df['Gender_Race'] = df.apply(lambda x: (x['Gender'], x['Race']), axis=1)
    source = ColumnDataSource(df)

    title = f"Race and Gender in {selected_state}" if selected_state != 'All' else "Race and Gender for All States"
    p = figure(x_range=FactorRange(*df['Gender_Race'].unique()), height=350, title=title, toolbar_location=None,
               sizing_mode='scale_width')

    p.vbar(x='Gender_Race', top='Count', width=0.9, source=source,
           line_color='white', fill_color='Color')

    p.add_tools(
        HoverTool(tooltips=[("Gender", "@Gender"), ("Race", "@Race"), ("Rate(per 100,000)", "@Count{0,0}")]))
    p.y_range.start = 0
    p.xgrid.grid_line_color = None
    p.xaxis.major_label_orientation = 1

    return p


pn.depends(state_selector.param.value)


def update_components(selected_state):
    map_html = create_map(selected_state)
    return pn.Column(pn.pane.HTML(map_html, sizing_mode='stretch_width'),
                     pn.Row(create_pie_chart(selected_state), create_nested_bars(selected_state)))


# Create a Markdown pane for the heading
heading = pn.pane.Markdown("# Cancer Deaths in the USA (2007-2013)")
heading.style = {'font-size': '20pt', 'font-weight': 'bold', 'margin': '10px 0 20px 0', }

dashboard = pn.Column(heading, state_selector, update_components)