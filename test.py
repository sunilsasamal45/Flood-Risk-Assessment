"""
India Flood Intelligence — River Basin Configuration & Data Fetching
Updated: 2025

This module provides configuration of major Indian river basins and
monitoring sites, with real-time discharge data via Open-Meteo Flood API.
No API key required — Open-Meteo is free and works globally.

Data source: https://open-meteo.com/en/docs/flood-api
IMD rainfall thresholds: Heavy ≥ 64.5 mm/day, Very Heavy ≥ 115.5 mm/day
"""

import requests
from typing import Dict, List, Optional
from datetime import datetime, timezone
import json


# ============================================================================
# INDIA RIVER BASIN CONFIGURATION
# ============================================================================

REGION_CONFIG = {
    "IN-GANGA": {
        "name": "Ganga Basin",
        "code": "IN-GANGA",
        "description": "Ganga river basin — Uttarakhand, UP, Bihar, West Bengal",
        "center_lat": 26.0,
        "center_lng": 82.0,
        "zoom": 6,
        "state_codes": ["UK", "UP", "BR", "WB"],
        "sites": [
            "ganga_haridwar", "ganga_allahabad", "ganga_varanasi",
            "ganga_patna", "yamuna_delhi", "yamuna_agra",
            "ghaghra_ayodhya", "sone_arrah", "gandak_gandak_nagar"
        ]
    },
    "IN-BRAHMAPUTRA": {
        "name": "Brahmaputra Basin",
        "code": "IN-BRAHMAPUTRA",
        "description": "Brahmaputra river basin — Assam and Arunachal Pradesh",
        "center_lat": 26.5,
        "center_lng": 93.0,
        "zoom": 6,
        "state_codes": ["AS", "AR"],
        "sites": [
            "brahmaputra_guwahati", "brahmaputra_dibrugarh",
            "subansiri_north_lakhimpur", "barak_silchar",
            "kopili_kampur", "manas_beki"
        ]
    },
    "IN-MAHANADI": {
        "name": "Mahanadi Basin",
        "code": "IN-MAHANADI",
        "description": "Mahanadi river basin — Chhattisgarh and Odisha",
        "center_lat": 20.5,
        "center_lng": 82.5,
        "zoom": 6,
        "state_codes": ["CT", "OD"],
        "sites": [
            "mahanadi_hirakud", "mahanadi_cuttack",
            "tel_kantamal", "ib_brajrajnagar", "jonk_jonk"
        ]
    },
    "IN-GODAVARI": {
        "name": "Godavari Basin",
        "code": "IN-GODAVARI",
        "description": "Godavari river basin — Maharashtra, Telangana, Andhra Pradesh",
        "center_lat": 18.5,
        "center_lng": 79.5,
        "zoom": 6,
        "state_codes": ["MH", "TG", "AP"],
        "sites": [
            "godavari_nashik", "godavari_rajahmundry",
            "pranhita_pranhita", "indravati_jagdalpur",
            "wardha_arvi", "wainganga_bamni"
        ]
    },
    "IN-KRISHNA": {
        "name": "Krishna Basin",
        "code": "IN-KRISHNA",
        "description": "Krishna river basin — Maharashtra, Karnataka, Andhra Pradesh",
        "center_lat": 16.5,
        "center_lng": 77.0,
        "zoom": 6,
        "state_codes": ["MH", "KA", "AP"],
        "sites": [
            "krishna_sangam", "krishna_vijayawada",
            "tungabhadra_hospet", "bhima_yadgir",
            "ghataprabha_saundatti"
        ]
    },
    "IN-INDUS": {
        "name": "Indus Basin (India)",
        "code": "IN-INDUS",
        "description": "Indus tributaries — Punjab, Himachal Pradesh, J&K",
        "center_lat": 32.0,
        "center_lng": 76.0,
        "zoom": 6,
        "state_codes": ["PB", "HP", "JK"],
        "sites": [
            "sutlej_ropar", "beas_mandi",
            "ravi_madhopur", "chenab_akhnoor", "jhelum_sangam"
        ]
    },
    "IN-NARMADA": {
        "name": "Narmada Basin",
        "code": "IN-NARMADA",
        "description": "Narmada river basin — Madhya Pradesh and Gujarat",
        "center_lat": 22.5,
        "center_lng": 77.5,
        "zoom": 6,
        "state_codes": ["MP", "GJ"],
        "sites": [
            "narmada_jabalpur", "narmada_sardar_sarovar",
            "tawa_itarsi", "bargi_bargi"
        ]
    },
    "IN-KAVERI": {
        "name": "Kaveri Basin",
        "code": "IN-KAVERI",
        "description": "Kaveri river basin — Karnataka and Tamil Nadu",
        "center_lat": 12.5,
        "center_lng": 77.5,
        "zoom": 6,
        "state_codes": ["KA", "TN"],
        "sites": [
            "kaveri_krishnarajasagara", "kaveri_trichy",
            "hemavathi_gorur", "arkavathi_kanakpura",
            "bhavani_bhavani_sagar"
        ]
    }
}

# Site coordinate lookup for Open-Meteo API calls
INDIA_RIVER_SITES = {
    # Ganga Basin
    "ganga_haridwar":            ("Ganga at Haridwar",              29.9457,  78.1642),
    "ganga_allahabad":           ("Ganga at Prayagraj",              25.4358,  81.8463),
    "ganga_varanasi":            ("Ganga at Varanasi",               25.3176,  83.0062),
    "ganga_patna":               ("Ganga at Patna",                  25.5941,  85.1376),
    "yamuna_delhi":              ("Yamuna at Delhi",                 28.6139,  77.2090),
    "yamuna_agra":               ("Yamuna at Agra",                  27.1767,  78.0081),
    "ghaghra_ayodhya":           ("Ghaghra at Ayodhya",              26.7922,  82.1998),
    "sone_arrah":                ("Sone at Arrah",                   25.5566,  84.6640),
    "gandak_gandak_nagar":       ("Gandak at Gandak Nagar",          26.8956,  84.4509),
    # Brahmaputra Basin
    "brahmaputra_guwahati":      ("Brahmaputra at Guwahati",         26.1445,  91.7362),
    "brahmaputra_dibrugarh":     ("Brahmaputra at Dibrugarh",        27.4728,  94.9120),
    "subansiri_north_lakhimpur": ("Subansiri at North Lakhimpur",    27.2343,  94.1036),
    "barak_silchar":             ("Barak at Silchar",                24.8333,  92.7789),
    "kopili_kampur":             ("Kopili at Kampur",                26.0500,  92.6500),
    "manas_beki":                ("Manas at Beki Bridge",            26.5600,  90.9800),
    # Mahanadi Basin
    "mahanadi_hirakud":          ("Mahanadi at Hirakud Dam",         21.5235,  83.8714),
    "mahanadi_cuttack":          ("Mahanadi at Cuttack",             20.4625,  85.8830),
    "tel_kantamal":              ("Tel at Kantamal",                 20.6344,  83.7315),
    "ib_brajrajnagar":           ("Ib at Brajrajnagar",              21.8242,  83.9219),
    "jonk_jonk":                 ("Jonk at Jonk",                    21.2500,  82.3500),
    # Godavari Basin
    "godavari_nashik":           ("Godavari at Nashik",              20.0059,  73.7897),
    "godavari_rajahmundry":      ("Godavari at Rajahmundry",         17.0005,  81.7799),
    "pranhita_pranhita":         ("Pranhita at Pranhita",            18.8600,  79.7300),
    "indravati_jagdalpur":       ("Indravati at Jagdalpur",          19.0748,  82.0340),
    "wardha_arvi":               ("Wardha at Arvi",                  20.9934,  78.9241),
    "wainganga_bamni":           ("Wainganga at Bamni",              20.7000,  79.9500),
    # Krishna Basin
    "krishna_sangam":            ("Krishna at Sangam",               17.3753,  76.8200),
    "krishna_vijayawada":        ("Krishna at Vijayawada",           16.5062,  80.6480),
    "tungabhadra_hospet":        ("Tungabhadra at Hospet",           15.2689,  76.3909),
    "bhima_yadgir":              ("Bhima at Yadgir",                 16.7700,  77.1300),
    "ghataprabha_saundatti":     ("Ghataprabha at Saundatti",        15.7786,  75.1234),
    # Indus (India)
    "sutlej_ropar":              ("Sutlej at Ropar",                 30.9645,  76.5266),
    "beas_mandi":                ("Beas at Mandi",                   31.7096,  76.9321),
    "ravi_madhopur":             ("Ravi at Madhopur",                32.2783,  75.6347),
    "chenab_akhnoor":            ("Chenab at Akhnoor",               32.8800,  74.7300),
    "jhelum_sangam":             ("Jhelum near Sangam",              33.6400,  74.9900),
    # Narmada Basin
    "narmada_jabalpur":          ("Narmada at Jabalpur",             23.1815,  79.9864),
    "narmada_sardar_sarovar":    ("Narmada at Sardar Sarovar",       21.8270,  73.7496),
    "tawa_itarsi":               ("Tawa at Itarsi",                  22.6217,  77.7643),
    "bargi_bargi":               ("Narmada at Bargi Dam",            23.0500,  79.9000),
    # Kaveri Basin
    "kaveri_krishnarajasagara":  ("Kaveri at KRS Dam",               12.4262,  76.5716),
    "kaveri_trichy":             ("Kaveri at Tiruchirappalli",        10.7905,  78.7047),
    "hemavathi_gorur":           ("Hemavathi at Gorur Dam",          12.9600,  76.0800),
    "arkavathi_kanakpura":       ("Arkavathi at Kanakpura",          12.5450,  77.4180),
    "bhavani_bhavani_sagar":     ("Bhavani at Bhavani Sagar",        11.4450,  77.1200),
}


# ============================================================================
# OPEN-METEO FLOOD API FETCHER (Free, No Key Required)
# ============================================================================

class IndiaRiverDataFetcher:
    """
    Fetch real-time river discharge forecasts from Open-Meteo Flood API.
    Free — no API key required.
    API docs: https://open-meteo.com/en/docs/flood-api
    """

    FLOOD_API_URL    = "https://flood-api.open-meteo.com/v1/flood"
    WEATHER_API_URL  = "https://api.open-meteo.com/v1/forecast"

    def get_current_discharge(self, site_code: str) -> Optional[Dict]:
        """
        Get latest river discharge forecast for a site (m³/s).

        Args:
            site_code: Site code from INDIA_RIVER_SITES
                       e.g. 'ganga_patna', 'brahmaputra_guwahati'

        Returns:
            Dict with discharge data, or None on error
        """
        if site_code not in INDIA_RIVER_SITES:
            print(f"Unknown site code: {site_code}")
            return None

        name, lat, lon = INDIA_RIVER_SITES[site_code]
        params = {
            'latitude':     lat,
            'longitude':    lon,
            'daily':        'river_discharge,river_discharge_max,river_discharge_mean',
            'forecast_days': 7,
            'past_days':    1,
        }
        try:
            r = requests.get(self.FLOOD_API_URL, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            daily      = data.get('daily', {})
            dates      = daily.get('time', [])
            discharges = daily.get('river_discharge', [])
            max_vals   = daily.get('river_discharge_max', [])
            mean_vals  = daily.get('river_discharge_mean', [])

            if not discharges:
                return None

            latest_discharge = discharges[-1] or 0.0
            latest_max       = max_vals[-1]  if max_vals  else None
            latest_mean      = mean_vals[-1] if mean_vals else None

            return {
                'site_code':        site_code,
                'site_name':        name,
                'latitude':         lat,
                'longitude':        lon,
                'discharge_cumecs': round(latest_discharge, 2),   # m³/s
                'discharge_max':    round(latest_max, 2)  if latest_max  else None,
                'discharge_mean':   round(latest_mean, 2) if latest_mean else None,
                'date':             dates[-1] if dates else None,
                'forecast_7day':    list(zip(dates, discharges)),
                'timestamp':        datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            print(f"Error fetching discharge for {site_code}: {e}")
            return None

    def get_daily_data(self, site_code: str,
                       past_days: int = 7) -> Optional[Dict]:
        """
        Get daily discharge values for a site (last N days + 7-day forecast).

        Returns:
            Dict with time series data, or None on error
        """
        if site_code not in INDIA_RIVER_SITES:
            print(f"Unknown site code: {site_code}")
            return None

        name, lat, lon = INDIA_RIVER_SITES[site_code]
        params = {
            'latitude':     lat,
            'longitude':    lon,
            'daily':        'river_discharge,river_discharge_mean',
            'forecast_days': 7,
            'past_days':    past_days,
        }
        try:
            r = requests.get(self.FLOOD_API_URL, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            daily      = data.get('daily', {})
            dates      = daily.get('time', [])
            discharges = daily.get('river_discharge', [])
            means      = daily.get('river_discharge_mean', [])

            return {
                'site_code':  site_code,
                'site_name':  name,
                'values':     [
                    {'date': d, 'discharge_cumecs': v, 'mean_cumecs': m}
                    for d, v, m in zip(dates, discharges, means or [None]*len(dates))
                ],
                'unit':       'm³/s (cumecs)',
                'timestamp':  datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            print(f"Error fetching daily data for {site_code}: {e}")
            return None

    def get_rainfall_forecast(self, lat: float, lon: float,
                               location_name: str = "") -> Optional[Dict]:
        """
        Get 3-day rainfall forecast for any India location (Open-Meteo weather).
        IMD thresholds: Heavy ≥ 64.5 mm/day, Very Heavy ≥ 115.5 mm/day

        Returns:
            Dict with rainfall data, or None on error
        """
        params = {
            'latitude':          lat,
            'longitude':         lon,
            'daily':             'precipitation_sum,precipitation_probability_max,weather_code',
            'current':           'precipitation,rain,temperature_2m,relative_humidity_2m',
            'forecast_days':     3,
            'timezone':          'Asia/Kolkata',
            'precipitation_unit':'mm',
            'temperature_unit':  'celsius',
        }
        try:
            r = requests.get(self.WEATHER_API_URL, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()

            daily   = data.get('daily', {})
            current = data.get('current', {})
            dates   = daily.get('time', [])
            precip  = daily.get('precipitation_sum', [])

            def imd_category(mm: float) -> str:
                if   mm >= 204.5: return "Extremely Heavy Rain (IMD Red)"
                elif mm >= 115.5: return "Very Heavy Rain (IMD Orange)"
                elif mm >=  64.5: return "Heavy Rain (IMD Yellow)"
                elif mm >=  15.6: return "Moderate Rain"
                elif mm >=   2.5: return "Light Rain"
                else:             return "No/Trace Rain"

            forecast = [
                {
                    'date':     d,
                    'rain_mm':  round(v, 1) if v else 0.0,
                    'category': imd_category(v or 0.0)
                }
                for d, v in zip(dates, precip)
            ]

            return {
                'location':        location_name or f"{lat},{lon}",
                'latitude':        lat,
                'longitude':       lon,
                'current_rain_mm': current.get('rain', 0) or current.get('precipitation', 0),
                'temperature_c':   current.get('temperature_2m'),
                'humidity_pct':    current.get('relative_humidity_2m'),
                'forecast_3day':   forecast,
                'max_rain_mm':     max((f['rain_mm'] for f in forecast), default=0),
                'timestamp':       datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            print(f"Error fetching rainfall for {location_name}: {e}")
            return None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_region_sites(region_code: str) -> List[str]:
    """Get all site codes for a given India river basin region"""
    return REGION_CONFIG.get(region_code, {}).get("sites", [])


def get_all_sites() -> List[str]:
    """Get all site codes across all India regions"""
    all_sites = []
    for region in REGION_CONFIG.values():
        all_sites.extend(region["sites"])
    return all_sites


def get_regions_by_state(state_code: str) -> List[str]:
    """Get all regions that include a given India state code (e.g. 'UP', 'MH')"""
    return [
        code for code, data in REGION_CONFIG.items()
        if state_code in data["state_codes"]
    ]


def get_region_data(region_code: str) -> Optional[Dict]:
    """Get complete region configuration"""
    return REGION_CONFIG.get(region_code)


def build_wris_monitoring_url(site_code: str) -> str:
    """Build India WRIS (Water Resources Information System) search URL"""
    name, lat, lon = INDIA_RIVER_SITES.get(site_code, ("", 0, 0))
    return f"https://indiawris.gov.in/wris/#/riverMonitoring"


def fetch_region_current_data(region_code: str) -> Dict[str, Dict]:
    """
    Fetch current discharge data for all sites in a region.

    Args:
        region_code: Region code (e.g., 'IN-GANGA', 'IN-BRAHMAPUTRA')

    Returns:
        Dictionary mapping site codes to their current discharge data
    """
    sites   = get_region_sites(region_code)
    fetcher = IndiaRiverDataFetcher()
    results = {}

    for site_code in sites:
        data = fetcher.get_current_discharge(site_code)
        if data:
            results[site_code] = data

    return results


def export_config_to_json(filename: str = 'india_watershed_config.json'):
    """Export India basin configuration to JSON file"""
    with open(filename, 'w') as f:
        json.dump(REGION_CONFIG, f, indent=2)
    print(f"India basin configuration exported to {filename}")


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("India Flood Intelligence — River Basin Configuration")
    print("Data source: Open-Meteo Flood API (free, no key required)")
    print("=" * 70)

    fetcher = IndiaRiverDataFetcher()

    # --- 1. Region information ---
    print("\n1. Ganga Basin Information:")
    print("-" * 70)
    ganga = get_region_data("IN-GANGA")
    if ganga:
        print(f"Region:   {ganga['name']}")
        print(f"Desc:     {ganga['description']}")
        print(f"States:   {', '.join(ganga['state_codes'])}")
        print(f"Sites:    {len(ganga['sites'])} monitoring locations")

    # --- 2. List Brahmaputra sites ---
    print("\n2. Brahmaputra Basin Sites:")
    print("-" * 70)
    for i, code in enumerate(get_region_sites("IN-BRAHMAPUTRA"), 1):
        name, lat, lon = INDIA_RIVER_SITES.get(code, ("Unknown", 0, 0))
        print(f"  {i}. {code:35s} — {name} ({lat:.2f}°N, {lon:.2f}°E)")

    # --- 3. Current discharge (Ganga at Patna) ---
    print("\n3. Current Discharge — Ganga at Patna:")
    print("-" * 70)
    data = fetcher.get_current_discharge("ganga_patna")
    if data:
        print(f"  Site:        {data['site_name']}")
        print(f"  Discharge:   {data['discharge_cumecs']:,.1f} m³/s (cumecs)")
        if data['discharge_max']:
            print(f"  Max (7-day): {data['discharge_max']:,.1f} m³/s")
        print(f"  Date:        {data['date']}")
    else:
        print("  Could not fetch data — site may be temporarily offline.")

    # --- 4. 7-day time series (Brahmaputra at Guwahati) ---
    print("\n4. 7-Day Discharge — Brahmaputra at Guwahati:")
    print("-" * 70)
    ts = fetcher.get_daily_data("brahmaputra_guwahati", past_days=3)
    if ts:
        print(f"  Site: {ts['site_name']} ({ts['unit']})")
        for v in ts['values'][-5:]:
            print(f"    {v['date']}:  {v['discharge_cumecs']:>10,.1f} m³/s")
    else:
        print("  Could not fetch time-series data.")

    # --- 5. Rainfall forecast (Patna) ---
    print("\n5. 3-Day Rainfall Forecast — Patna, Bihar:")
    print("-" * 70)
    rain = fetcher.get_rainfall_forecast(25.5941, 85.1376, "Patna, Bihar")
    if rain:
        print(f"  Current rain:   {rain['current_rain_mm']} mm")
        print(f"  Temperature:    {rain['temperature_c']}°C")
        print(f"  Humidity:       {rain['humidity_pct']}%")
        print("  3-day forecast:")
        for f in rain['forecast_3day']:
            print(f"    {f['date']}:  {f['rain_mm']:>6.1f} mm  [{f['category']}]")
        print(f"  Peak expected: {rain['max_rain_mm']} mm/day")
    else:
        print("  Could not fetch rainfall data.")

    # --- 6. All Ganga basin sites (live fetch) ---
    print("\n6. Ganga Basin — Current Discharge (All Sites):")
    print("-" * 70)
    print("  Fetching data... (may take a few seconds)")
    ganga_data = fetch_region_current_data("IN-GANGA")
    print(f"  Successfully fetched {len(ganga_data)} of {len(get_region_sites('IN-GANGA'))} sites:")
    for code, d in ganga_data.items():
        print(f"    {d['site_name']:45s}  {d['discharge_cumecs']:>10,.1f} m³/s")

    # --- 7. Export config ---
    print("\n7. Export Configuration:")
    print("-" * 70)
    export_config_to_json('india_watershed_config.json')

    # --- 8. Statistics ---
    print("\n8. Configuration Statistics:")
    print("-" * 70)
    print(f"  Total basins:        {len(REGION_CONFIG)}")
    print(f"  Total sites:         {len(get_all_sites())}")
    print("\n  Sites per basin:")
    for code, data in REGION_CONFIG.items():
        print(f"    {code:20s} ({data['name']:25s}): {len(data['sites'])} sites")

    # --- 9. States covered ---
    print("\n9. UP Regions:")
    print("-" * 70)
    up_regions = get_regions_by_state("UP")
    print(f"  Uttar Pradesh is covered by: {', '.join(up_regions)}")

    print("\n" + "=" * 70)
    print("India Flood Intelligence — Configuration ready!")
    print("Emergency: NDMA helpline 1078 | IMD weather: mausam.imd.gov.in")
    print("=" * 70)
