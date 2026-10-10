"""Project paths, source-field mappings, and analysis defaults."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "HHS_Unaccompanied_Alien_Children_Program.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

SOURCE_TO_INTERNAL = {
    "Date": "date",
    "Children apprehended and placed in CBP custody*": "cbp_daily_intake",
    "Children in CBP custody": "cbp_custody",
    "Children transferred out of CBP custody": "transfers_to_hhs",
    "Children in HHS Care": "hhs_care",
    "Children discharged from HHS Care": "hhs_discharges",
}
REQUIRED_SOURCE_COLUMNS = tuple(SOURCE_TO_INTERNAL)
COUNT_COLUMNS = tuple(column for column in SOURCE_TO_INTERNAL.values() if column != "date")
STOCK_COLUMNS = ("cbp_custody", "hhs_care")
FLOW_COLUMNS = ("cbp_daily_intake", "transfers_to_hhs", "hhs_discharges")
DEFAULT_ROLLING_COVERAGE = 0.8
FORECAST_MIN_COVERAGE = 0.9
FORECAST_MAX_GAP_DAYS = 7

METRIC_LABELS = {
    "total_system_load": "Total System Load (children in custody/care)",
    "cbp_custody": "CBP Active Load (children)",
    "hhs_care": "HHS Active Load (children)",
    "cbp_daily_intake": "CBP Daily Intake (children/reporting record)",
    "transfers_to_hhs": "Transfers to HHS (children/reporting record)",
    "hhs_discharges": "HHS Discharges (children/reporting record)",
    "hhs_net_intake_pressure": "HHS Net Intake Pressure (children/reporting record)",
}
