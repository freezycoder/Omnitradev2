from api import main


def test_kronos_forecast_routes_are_removed():
    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/forecast/{ticker}" not in paths
    assert "/api/forecast-health" not in paths
