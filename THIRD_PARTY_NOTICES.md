# Third-party notices

## Data and map services

Snow Watch fetches and displays data from these services. It is not affiliated
with or endorsed by any of them, and each keeps its own terms; check them before
running a public or commercial installation.

| Source | Used for | Terms |
|---|---|---|
| [Open-Meteo](https://open-meteo.com/) | Forecast models, ensembles, elevation, timezones | Data CC BY 4.0; the free API is for non-commercial use |
| [NOAA / National Weather Service](https://www.weather.gov/) | Alerts, forecast offices; HRRR and National Blend of Models forecasts for the map (NOAA Open Data Dissemination on AWS) | US public domain |
| [Environment and Climate Change Canada](https://eccc-msc.github.io/open-data/) | Radar (North American composite, precipitation type, nowcast), HRDPS, RDPS and GDPS forecasts and snow totals for the map | Open Government Licence – Canada |
| [RainViewer](https://www.rainviewer.com/) | Backup radar, when Environment Canada's is unavailable | Free API, with credit |
| [NRCS SNOTEL](https://www.nrcs.usda.gov/wps/portal/wcc/home/) | US snow stations | US public domain |
| [BC River Forecast Centre](https://www2.gov.bc.ca/gov/content/environment/air-land-water/water/drought-flooding-dikes-dams/river-forecast-centre) | BC snow pillows | Open Government Licence – British Columbia |
| [avalanche.org](https://avalanche.org/) | US avalanche forecasts | Each center's terms; shown as published, with a link |
| [Avalanche Canada](https://avalanche.ca/) | Canadian avalanche forecasts | Avalanche Canada's terms; shown as published, with a link |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) via Overpass | Ski runs, lifts, peaks | © OpenStreetMap contributors, ODbL |
| [OpenSkiMap](https://openskimap.org/) | The ski-area list for Manage | © OpenStreetMap contributors, ODbL |
| [OpenTopoMap](https://opentopomap.org/) | Topographic base map (cached by the server) | CC-BY-SA; tile use policy applies |
| [Esri](https://www.esri.com/) | Topographic and satellite base maps (cached by the server) | Esri terms of use |
| [Mapzen terrain tiles on AWS](https://registry.opendata.aws/terrain-tiles/) | 3D terrain | Various open licences, see the registry |
| [MapLibre demo tiles](https://demotiles.maplibre.org/) | Map label fonts (cached by the server) | See the MapLibre project |

## Software

Snow Watch's own code is MIT licensed (see [LICENSE](LICENSE)). It is built on
open-source packages, each under its own licence; the full lists are in
`backend/uv.lock` and `frontend/package-lock.json`. The main ones:

| Package | Licence |
|---|---|
| FastAPI, Pydantic, APScheduler, PyYAML, gribberish | MIT |
| Uvicorn, httpx, NumPy | BSD-3-Clause |
| Pillow | MIT-CMU |
| pywebpush, py-vapid | MPL-2.0 |
| tzdata | Apache-2.0 |
| Svelte, SvelteKit | MIT |
| MapLibre GL JS | BSD-3-Clause |
| Leaflet | BSD-2-Clause |
| d3-array, d3-scale, d3-shape, d3-time-format | ISC |
| Inter and Manrope fonts (via Fontsource) | SIL Open Font License 1.1 |
