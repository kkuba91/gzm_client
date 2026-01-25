# gzm-client

[![gzm_client](https://github.com/kkuba91/gzm_client/actions/workflows/python-package.yml/badge.svg)](https://github.com/kkuba91/gzm_client/actions/workflows/python-package.yml)

Python library + CLI for GZM public transport data (stops, departures, vehicles) with optional integrations:

- GZM SDIP endpoints (stops list, departures, simplified vehicle info)
- GZM RJ endpoint (ticket machines / ŚKUP)
- Nextbike GBFS (bike stations + availability)

All upstream URLs used by this project are centralized in: [src/gzm_client/constants.py](src/gzm_client/constants.py)

Library works as client proxy for getting the most interesting data for public transport Users and returning them as:

 - pretty Rich tables/panels (CLI mode)
 - JSON output (`--json` CLI flag)
 - Python API return values as dicts/lists (from `gzm_client.client`)

## Requirements

- Python: **3.10+**

## Installation

From a local clone:

- Install (regular): `pip install gzm_client`
- Install (uv): `uv run pip install gzm_client`

This installs the console script: `gzm-client`

## Python API usage

```python
from gzm_client.client import GzmClient

client = GzmClient(db_path="stops.db")

# One-time cache build (required before other commands)
client.update_api(to_stdout=False)

# Use the same methods as the CLI
data = client.junction("Nowak-Mosty Będzin Arena", to_stdout=False)
print(data["name"], len(data["variants"]))
```

## CLI usage

Help output:

```text
gzm-client -h
usage: gzm-client [-h] [--db DB] [--json] {update_api,update_file,list,junction,stop,go,bikes} ...

positional arguments:
	{update_api,update_file,list,junction,stop,go,bikes}
		update_api          Fetches data from the API and updates the database.
		update_file         Loads data from a local JSON file and updates the database.
		list                Lists stops for the given city.
		junction            Prints all variants for a junction stop, including stop IDs and served lines.
		stop                Prints upcoming departures from the stop.
		go                  Fetches trip data by did (vehicle-all), enriches it by vid and prints a summary.
		bikes               Nextbike (GZM bikes) related commands.

options:
	-h, --help            show this help message and exit
	--db DB               SQLite database path (default: stops.db in current working dir)
	--json                Print JSON output (disables rich stdout rendering)
```

### Global options

- `--db DB`: path to the SQLite cache (default: `stops.db` in the current directory)
- `--json`: prints JSON to stdout and disables Rich panels/tables (internally calls methods with `to_stdout=False`)

### Commands

#### 1) Cache update

- `gzm-client update_api`
	- Downloads and caches:
		- stops database
		- Nextbike city list
		- ticket machines (ŚKUP) from `TICKET_MACHINES_URL`

- `gzm-client update_file PATH`
	- Loads stops from a local JSON file (mstops-compatible format) into the SQLite cache

Examples:

- `gzm-client update_api`

![update_api](./img/update_api.gif)

- `gzm-client --db my.db update_api`

#### 2) Stops

- `gzm-client list CITY`
	- Lists grouped stop names for the municipality

- `gzm-client junction STOP_NAME...`
	- Prints all stop variants (platforms) for an exact junction name
	- Includes:
		- served lines
		- nearby Nextbike stations (with average distance)
		- ticket machine proximity info (300m radius)

![junction](./img/junction.gif)

- `gzm-client stop STOP_ID`
	- Prints upcoming departures for a stop id
	- Includes nearby Nextbike stations and ticket-machine proximity info

Examples:

- `gzm-client list Wojkowice`

![list](./img/list.gif)

- `gzm-client junction Nowak-Mosty Będzin Arena`  - example with platform for trams and busses

![bedzin](./img/bedzin.gif)

- `gzm-client stop 2205`

![stop](./img/stop.gif)

- `gzm-client --json stop 10055`. - other stop's location, all data in stdout returned in JSON

```bash
❯ gzm-client --json stop 10055
{
  "stop": {
    "id": "10055",
    "alt_id": "2",
    "name": "Nowak-Mosty Będzin Arena",
    "municipality": "BĘDZIN",
    "lat": 50.31970275,
    "lon": 19.12465927,
    "ticket_machine": true,
    "ticket_machine_distance_m": 66.38439872764141,
    "ticket_machine_name": "Automat ŚKUP - BĘDZIN (Będzin Stadion) "
  },
  "ticket_machine": true,
  "nearby_bikes": [
    {
      "station_id": "339753256",
      "name": "27784",
      "short_name": "27784",
      "position": [
        50.319485,
        19.124995
      ],
      "capacity": 5,
      "bikes_available": 4,
      "docks_available": 1,
      "bike_list": null,
      "distance_m": 33.976826442185555
    }
  ],
  "departures": [
    {
      "did": "852702651",
      "line_type": "3",
      "line": "M19",
      "destination": "Pyrzowice Port Lotniczy (Katowice Airport)",
      "time": "35 min"
    },
    {
      "did": "853524016",
      "line_type": "3",
      "line": "67",
      "destination": "Będzin Kościuszki",
      "time": "03:57"
    },
    ... [removed elements from long list] ...
    {
      "did": "852806090",
      "line_type": "3",
      "line": "125",
      "destination": "Będzin Kościuszki",
      "time": "04:24"
    }
  ]
}
```

#### 3) Vehicle tracking

- `gzm-client go DID`
	- Fetches trip data by `did` ('dependency id' or 'departure id') and enriches it by `vid` (vehicle id)

Example:

- `gzm-client go 873172286`  -  *IMPORTANT*: DID vehicle must begun the journey (if still not departured, error will appear)

![go](./img/go.gif)

#### 4) Nextbike (GZM bikes)

- `gzm-client bikes city CITY_PREFIX...`
	- Resolves a city/region from the cached region list and prints a summary with station count, total bikes/docks

- `gzm-client bikes station STATION_ID`
	- Prints bike station status with available ones info

Examples:

- `gzm-client bikes city Wojkowice`

![bikes_city](./img/bikes_city.gif)

- `gzm-client bikes station 332519309`

![bikes_station](./img/bikes_station.gif)

## Notes on API integrations

This project tries to present a consistent mstops-like interface while integrating multiple upstream sources:

- **SDIP (transportgzm.pl)**: stops list, stop departures, vehicle endpoints
- **RJ API (rj.transportgzm.pl)**: ticket machines (ŚKUP)
- **Nextbike GBFS**: station locations + station status for GZM area

See the exact endpoints in: [src/gzm_client/constants.py](src/gzm_client/constants.py)
