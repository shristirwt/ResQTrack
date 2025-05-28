import firebase_admin
from firebase_admin import credentials, db
import networkx as nx
from geopy.distance import geodesic
import folium
import openrouteservice
from openrouteservice import convert
import os

# Firebase initialization
cred = credentials.Certificate(r"C:\Users\SHRISTI\Downloads\resqtrack-309e7-firebase-adminsdk-fbsvc-188cedef0a.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://resqtrack-309e7-default-rtdb.firebaseio.com/'
})

# Fetching hospital data from Firebase
ref = db.reference("Hospital/elements")
elements = ref.get()

if not elements:
    print("Error: No hospital data found in Firebase. Exiting...")
    exit(1)

# Create graph
G = nx.Graph()
for place in elements:
    G.add_node(place['name'], pos=(place['lat'], place['lon']))

# Fetching driver location
driver_ref=db.reference("drivers/QW146W5tjvNg1alV0AUIhq7UTgu1")
driver_data=driver_ref.get()

driver_lat=driver_data.get("latitude")
driver_long=driver_data.get("longitude")

if driver_lat is None or driver_long is None:
    print("Driver location not found in otp section. Exiting...")
    exit(1)
    
otp_ref=db.reference("otp/xlFT4NSVFCSUqaamJs5Z6aHFvPi1")
otp_data=otp_ref.get()

if not otp_data or otp_data.get("connectedHospital")!="Yes":
    print("Driver is not connected to the hospital. Existing...")
    exit(1)

print(f"Driver location from Firebase: {driver_lat}, {driver_long}")
G.add_node("Driver", pos=(driver_lat, driver_long))

# Create map
map = folium.Map(location=[driver_lat, driver_long], zoom_start=15)

# Add hospital markers
for place in elements:
    folium.Marker(
        [place['lat'], place['lon']],
        popup=place['name'],
        icon=folium.Icon(color='blue', icon='plus-sign')
    ).add_to(map)

# Add patient marker
folium.Marker(
    [driver_lat, driver_long],
    popup="Driver",
    icon=folium.Icon(color='red')
).add_to(map)

# Add edges to the graph with weights
all_places = elements + [{"name": "Driver", "lat": driver_lat, "lon": driver_long}]
for i in range(len(all_places)):
    for j in range(i + 1, len(all_places)):
        node1 = all_places[i]['name']
        node2 = all_places[j]['name']
        pos1 = (all_places[i]['lat'], all_places[i]['lon'])
        pos2 = (all_places[j]['lat'], all_places[j]['lon'])
        distance = geodesic(pos1, pos2).kilometers
        G.add_edge(node1, node2, weight=distance)

# Find nearest hospital using A* algorithm
min_dist = float('inf')
nearest_hospital = None
for place in elements:
    if "Driver" in G.nodes and place['name'] in G.nodes:
        try:
            dist = nx.astar_path_length(
                G, "Driver", place['name'],
                heuristic=lambda u, v: geodesic(G.nodes[u]['pos'], G.nodes[v]['pos']).kilometers,
                weight='weight'
            )
            if dist < min_dist:
                min_dist = dist
                nearest_hospital = place['name']
        except nx.NetworkXNoPath:
            continue

if nearest_hospital:
    print(f"Nearest hospital: {nearest_hospital}, Distance: {min_dist:.2f} kilometers")
    path = nx.astar_path(
        G, "Driver", nearest_hospital,
        heuristic=lambda u, v: geodesic(G.nodes[u]['pos'], G.nodes[v]['pos']).kilometers,
        weight='weight'
    )
    print("Shortest path:", path)
    
    hospital_lat = None
    hospital_lon = None
    for place in elements:
        if place['name'] == nearest_hospital:
            hospital_lat = place['lat']
            hospital_lon = place['lon']
            break
    
    nearest_ref=db.reference("Hospital/elements/")
    otp_ref.update({
        "hospital_lat": hospital_lat,
        "hospital_lon": hospital_lon
    })

    path_coords = []
    for node in path:
        if node == "Driver":
            path_coords.append([driver_lat, driver_long])
        else:
            for place in elements:
                if place['name'] == node:
                    path_coords.append([place['lat'], place['lon']])
                    break

    # Draw route on the map using ORS API
    ors_key = os.getenv("ORS_API_KEY", '5b3ce3597851110001cf62484a003152f27642ac930ca70e06506056')
    client = openrouteservice.Client(key=ors_key)
    coords = ((driver_long, driver_lat), (G.nodes[nearest_hospital]['pos'][1], G.nodes[nearest_hospital]['pos'][0]))
    try:
        routes = client.directions(coords, radiuses=[5000, 5000])  # Increased radius
        geometry = routes['routes'][0]['geometry']
        decoded = convert.decode_polyline(geometry)
        route_coords = [(point[1], point[0]) for point in decoded['coordinates']]
        folium.PolyLine(route_coords, color="red", weight=5, opacity=0.8).add_to(map)
    except openrouteservice.exceptions.ApiError as e:
        print(f"Routing error: {e}. Adding straight-line route.")
        folium.PolyLine(path_coords, color="orange", weight=2, opacity=0.8).add_to(map)
else:
    print("No path found to any hospital.")

# Save the map
map.save("hospital_map.html")
print("Map saved as hospital_map.html. Open it in your browser.")