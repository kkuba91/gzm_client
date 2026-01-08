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

```bash
❯ gzm-client update_api
╭───────────────────────────────────────────────────── API cached ─────────────────────────────────────────────────────╮
│ Updated database from API (stops + bikes).                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────── SKUP ────────────────────────────────────────────────────────╮
│ Ticket machines cached: 125                                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

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

```bash
❯ gzm-client junction Wojkowice Park
╭─────────────────────────────────── Junction for 'Wojkowice Park' (2 stops found). ───────────────────────────────────╮
│ ╭─────────────────────── Stop: Wojkowice Park | ID=2205 | ALT=1 | TYPE=Autobus | WOJKOWICE ────────────────────────╮ │
│ │ Lines: 24, 25, 52, 99, 104, 133, 722, 904N, M11                                                                  │ │
│ │ Ticket machine: NO                                                                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────────── Stop: Wojkowice Park | ID=2206 | ALT=2 | TYPE=Autobus | WOJKOWICE ────────────────────────╮ │
│ │ Lines: 24, 25, 43, 52, 99, 100, 103, 104, 700, 721, 722, 904N, 911N, M11                                         │ │
│ │ Ticket machine: NO                                                                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│                                                                                                                      │
│ Nearby bike stations                                                                                                 │
│ ┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓                                          │
│ ┃ Id        ┃ Station ┃ Location               ┃ Distance ┃ Bikes ┃ Docks ┃                                          │
│ ┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩                                          │
│ │ 451953727 │ 27542   │ [50.365813, 19.033542] │ 223m     │ 3     │ 2     │                                          │
│ └───────────┴─────────┴────────────────────────┴──────────┴───────┴───────┘                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

- `gzm-client stop STOP_ID`
	- Prints upcoming departures for a stop id
	- Includes nearby Nextbike stations and ticket-machine proximity info

Examples:

- `gzm-client list Wojkowice`

```bash
❯ gzm-client list Wojkowice
╭───────────────────────────────────────────────── Stops in Wojkowice ─────────────────────────────────────────────────╮
│ ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓                                                  │
│ ┃ Stop (group of platforms)    ┃ Platform IDs                     ┃                                                  │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩                                                  │
│ │ Kamyce Posesja 500           │ ["1263", "1262"]                 │                                                  │
│ │ Kamyce Remiza nż             │ ["1259", "1258"]                 │                                                  │
│ │ Kamyce Wygoda                │ ["1260", "1261"]                 │                                                  │
│ │ Wojkowice Akacjowa           │ ["5551", "5548"]                 │                                                  │
│ │ Wojkowice Brzeziny           │ ["3574", "3573"]                 │                                                  │
│ │ Wojkowice Brzeziny 76 nż     │ ["5341", "5342"]                 │                                                  │
│ │ Wojkowice Cmentarz           │ ["5543", "5542"]                 │                                                  │
│ │ Wojkowice Długosza           │ ["671", "670"]                   │                                                  │
│ │ Wojkowice Fabryczna          │ ["5311", "5310"]                 │                                                  │
│ │ Wojkowice Giełda             │ ["731", "732"]                   │                                                  │
│ │ Wojkowice Głowackiego 126 nż │ ["1097", "1098"]                 │                                                  │
│ │ Wojkowice Głowackiego 31 nż  │ ["1099", "1100"]                 │                                                  │
│ │ Wojkowice Harcerska          │ ["3609", "3608"]                 │                                                  │
│ │ Wojkowice Kościół            │ ["3576", "3579", "3578", "3577"] │                                                  │
│ │ Wojkowice Krzyżówka          │ ["1518", "1516", "1517"]         │                                                  │
│ │ Wojkowice Morcinka           │ ["5312", "5309"]                 │                                                  │
│ │ Wojkowice Morcinka Wiadukt   │ ["5547", "5546"]                 │                                                  │
│ │ Wojkowice Ośrodek Zdrowia nż │ ["1910", "1911"]                 │                                                  │
│ │ Wojkowice Park               │ ["2205", "2206"]                 │                                                  │
│ │ Wojkowice Skłodowskiej-Curie │ ["5549", "5552"]                 │                                                  │
│ │ Wojkowice Spokojna           │ ["5553", "5550"]                 │                                                  │
│ │ Wojkowice Spółdzielnia nż    │ ["5339", "5340"]                 │                                                  │
│ │ Wojkowice Sucharskiego       │ ["5545", "5544"]                 │                                                  │
│ │ Wojkowice Łęg                │ ["2990", "2992", "2991"]         │                                                  │
│ │ Żychcice Cmentarz            │ ["5314", "5313"]                 │                                                  │
│ │ Żychcice Piaski 117          │ ["75", "74"]                     │                                                  │
│ │ Żychcice Piaski 37           │ ["70", "71"]                     │                                                  │
│ │ Żychcice Piaski 79           │ ["73", "72"]                     │                                                  │
│ │ Żychcice Pętla               │ ["4439", "4438", "7431"]         │                                                  │
│ │ Żychcice Stara 113           │ ["79", "78"]                     │                                                  │
│ │ Żychcice Stara 54            │ ["76", "77"]                     │                                                  │
│ └──────────────────────────────┴──────────────────────────────────┘                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

- `gzm-client junction Nowak-Mosty Będzin Arena`

```bash
❯ gzm-client junction Nowak-Mosty Będzin Arena
╭────────────────────────────── Junction for 'Nowak-Mosty Będzin Arena' (8 stops found). ──────────────────────────────╮
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10053 | ALT=1 | TYPE=Autobus | BĘDZIN ────────────────────╮ │
│ │ Lines: 27, 40, 42, 61, 200, 616, 721, 902N, 916                                                                  │ │
│ │ Ticket machine: YES (18m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10054 | ALT=1t | TYPE=Tramwaj | BĘDZIN ───────────────────╮ │
│ │ Lines: 15, 21, 24, 26, 27, 34, 36                                                                                │ │
│ │ Ticket machine: YES (97m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10055 | ALT=2 | TYPE=Autobus | BĘDZIN ────────────────────╮ │
│ │ Lines: 16, 24, 25, 27, 28, 40, 67, 79, 97, 99, 104, 107, 124, 125, 200, 243, 260, 269, 612, 625, 722, 807, 901,  │ │
│ │ 904N, 916, 921, M19, M23                                                                                         │ │
│ │ Ticket machine: YES (66m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10056 | ALT=2t | TYPE=Tramwaj | BĘDZIN ───────────────────╮ │
│ │ Lines: 15, 21, 24, 26, 27, 34, 36                                                                                │ │
│ │ Ticket machine: YES (68m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10057 | ALT=3 | TYPE=Autobus | BĘDZIN ────────────────────╮ │
│ │ Lines: 16, 24, 25, 28, 40, 42, 61, 67, 79, 90, 97, 99, 104, 107, 124, 125, 200, 260, 269, 616, 625, 721, 722,    │ │
│ │ 800, 901, 902N, 904N, 921, M19, M23                                                                              │ │
│ │ Ticket machine: YES (23m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10060 | ALT=4 | TYPE=Autobus | BĘDZIN ────────────────────╮ │
│ │ Lines: 800, 813                                                                                                  │ │
│ │ Ticket machine: YES (39m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                               │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10058 | ALT=5 | TYPE=Autobus | BĘDZIN ────────────────────╮ │
│ │ Lines: 813, 916                                                                                                  │ │
│ │ Ticket machine: YES (165m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                              │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│ ╭─────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10059 | ALT=6 | TYPE=Autobus | BĘDZIN ────────────────────╮ │
│ │ Lines: 807, 916                                                                                                  │ │
│ │ Ticket machine: YES (110m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                              │ │
│ ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│                                                                                                                      │
│ Nearby bike stations                                                                                                 │
│ ┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓                                          │
│ ┃ Id        ┃ Station ┃ Location               ┃ Distance ┃ Bikes ┃ Docks ┃                                          │
│ ┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩                                          │
│ │ 339753256 │ 27784   │ [50.319485, 19.124995] │ 79m      │ 4     │ 1     │                                          │
│ └───────────┴─────────┴────────────────────────┴──────────┴───────┴───────┘                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

- `gzm-client stop 10055`

```bash
❯ gzm-client stop 10055
╭───────────────────────────── Stop: Nowak-Mosty Będzin Arena | ID=10055 | ALT=2 | BĘDZIN ─────────────────────────────╮
│ Departures                                                                                                           │
│ ┏━━━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓                              │
│ ┃ DID       ┃ Line ┃ Type ┃ Destination                                ┃ Arrival Time ┃                              │
│ ┡━━━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩                              │
│ │ 852702651 │ M19  │ Bus  │ Pyrzowice Port Lotniczy (Katowice Airport) │ 37 min       │                              │
│ │ 853524016 │ 67   │ Bus  │ Będzin Kościuszki                          │ 03:57        │                              │
│ │ 853770647 │ 97   │ Bus  │ Goląsza Dolna                              │ 04:03        │                              │
│ │ 852714208 │ 104  │ Bus  │ Bytom Dworzec                              │ 04:06        │                              │
│ │ 853140270 │ 40   │ Bus  │ Katowice Piotra Skargi                     │ 04:12        │                              │
│ │ 852699178 │ M19  │ Bus  │ Pyrzowice Port Lotniczy (Katowice Airport) │ 04:12        │                              │
│ │ 853028640 │ 25   │ Bus  │ Grodziec Różyckiego                        │ 04:13        │                              │
│ │ 853634004 │ 722  │ Bus  │ Będzin Kościuszki                          │ 04:19        │                              │
│ │ 852802836 │ 124  │ Bus  │ Będzin Kościuszki                          │ 04:19        │                              │
│ │ 852806090 │ 125  │ Bus  │ Będzin Kościuszki                          │ 04:24        │                              │
│ └───────────┴──────┴──────┴────────────────────────────────────────────┴──────────────┘                              │
│ Ticket machine: YES (66m) - Automat ŚKUP - BĘDZIN (Będzin Stadion)                                                   │
│                                                                                                                      │
│ Nearby bike stations                                                                                                 │
│ ┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━┓                                          │
│ ┃ Id        ┃ Station ┃ Location               ┃ Distance ┃ Bikes ┃ Docks ┃                                          │
│ ┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━┩                                          │
│ │ 339753256 │ 27784   │ [50.319485, 19.124995] │ 34m      │ 4     │ 1     │                                          │
│ └───────────┴─────────┴────────────────────────┴──────────┴───────┴───────┘                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

- `gzm-client --json stop 10055`

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

- `gzm-client go 852701434`  -  *IMPORTANT*: DID vehicle must begun the journey (if still not departured, error will appear)

```bash
❯ gzm-client go 852701434
╭──────────────────────────────────────────────────── Autobus: M19 ────────────────────────────────────────────────────╮
│ line: M19  |  did=852701434  |  id=104_3121  |  type=Autobus                                                         │
│ route: 'PYRZOWICE PORT LOTNICZY (KATOWICE AIRPORT) - SOSNOWIEC URZĄD MIASTA'                                         │
│ next stop: 'Sarnów Główna' with time: 0 min                                                                          │
│ deviation:                                                                                                           │
│ position: (50.374224, 19.148556)                                                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

#### 4) Nextbike (GZM bikes)

- `gzm-client bikes city CITY_PREFIX...`
	- Resolves a city/region from the cached region list and prints a summary with station count, total bikes/docks

- `gzm-client bikes station STATION_ID`
	- Prints bike station status with available ones info

Examples:

- `gzm-client bikes city Bobrowniki`

```bash
❯ gzm-client bikes city Bobrowniki
╭────────────────────────────────────── Bike region: Bobrowniki (GZM) (uid=1221) ──────────────────────────────────────╮
│ system: METROROWER,  hotline: +48800163030,  stations: 2,  booked: 0,  available bikes: 4                            │
│ stations:                                                                                                            │
│ -> id: 332519309,  name: None,  pos: (50.395951, 19.016923),  capacity: 5,  available: 3                             │
│  Available bikes: [587683, 587138, 584337]                                                                           │
│ -> id: 332520664,  name: None,  pos: (50.438768, 19.035108),  capacity: 4,  available: 1                             │
│  Available bikes: [586997]                                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

- `gzm-client bikes station 332519309`

```bash
❯ gzm-client bikes station 332519309
╭────────────────────────────────────── Bike station: id=332519309 | name=27084 ───────────────────────────────────────╮
│ Region: Bobrowniki (GZM) | (uid=1221) | system: METROROWER | hotline: +48800163030                                   │
│ Station | id: 332519309,  name: 27084,  pos: (50.395951, 19.016923),  capacity: 5,  available: 3                     │
│  Available bikes:                                                                                                    │
│  -> number: 587683,  type: 71,  state: OK,  electric lock: True,  board_id: 83300013618                              │
│  -> number: 587138,  type: 71,  state: OK,  electric lock: True,  board_id: 83300015858                              │
│  -> number: 584337,  type: 71,  state: OK,  electric lock: True,  board_id: 83300014102                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Notes on API integrations

This project tries to present a consistent mstops-like interface while integrating multiple upstream sources:

- **SDIP (transportgzm.pl)**: stops list, stop departures, vehicle endpoints
- **RJ API (rj.transportgzm.pl)**: ticket machines (ŚKUP)
- **Nextbike GBFS**: station locations + station status for GZM area

See the exact endpoints in: [src/gzm_client/constants.py](src/gzm_client/constants.py)
