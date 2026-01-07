"""Constants used by the mstops-compatible client."""

DB_NAME_DEFAULT = "stops.db"

# GZM stops API URLs
ALL_STOPS_URL = "https://sdip.transportgzm.pl/main?command=basicdata&action=mstops"
DEPARTURE_URL = "https://sdip.transportgzm.pl/main?command=planner&action=sd&id={}"
STOP_URL = "https://rj.transportgzm.pl/api/v2/stops/{}/"
TICKET_MACHINES_URL = "https://rj.transportgzm.pl/api/v2/skup/data/"

VEHICLE_ALL_DID_URL = (
    "https://sdip.transportgzm.pl/main?command=planner&action=vr&did={}"
)
VEHICLE_VID_URL = "https://sdip.transportgzm.pl/main?command=planner&action=v&vid={}"

# GZM bikes (Nextbike)
GZM_BIKES_CITIES_URL = (
    "https://gbfs.nextbike.net/maps/gbfs/v1/nextbike_zz/pl/system_regions.json"
)
GZM_BIKES_STATIONS_LOCATIONS_URL = (
    "https://gbfs.nextbike.net/maps/gbfs/v1/nextbike_zz/pl/station_information.json"
)
GZM_BIKES_STATION_STATUS_SHORT_URL = (
    "https://gbfs.nextbike.net/maps/gbfs/v1/nextbike_zz/pl/station_status.json"
)
GZM_BIKES_STATION_STATUS_FULL_URL = (
    "https://api.nextbike.net/maps/nextbike-live.json?place={}"
)
GZM_BIKES_CITY_STATUS_FULL_URL = (
    "https://api.nextbike.net/maps/nextbike-live.json?city={}"
)

BIKES_NEARBY_METERS = 300  # Search in distance of 300 meters for nearby bike stations


VEHICLE_TYPE = {
    "0": "Tram",
    "3": "Bus",
    "11": "Trolleybus",
}
