from django.test import SimpleTestCase

from .dashboard_views import DashboardViewSet


class DashboardViewSetTests(SimpleTestCase):
    def setUp(self):
        self.view = DashboardViewSet()

    def test_breakdown_total_uses_activity_total_for_carbon_dioxide_when_calculation_is_missing(self):
        result = self.view._breakdown_total_for_row(
            gas_type="Carbon dioxide",
            calc_total=0.0,
            activity_total=123.456,
        )

        self.assertEqual(result, 123.456)

    def test_breakdown_total_keeps_calculation_total_when_present(self):
        result = self.view._breakdown_total_for_row(
            gas_type="Carbon dioxide",
            calc_total=88.5,
            activity_total=123.456,
        )

        self.assertEqual(result, 88.5)

    def test_breakdown_total_does_not_fall_back_for_non_carbon_dioxide_gases(self):
        result = self.view._breakdown_total_for_row(
            gas_type="Methane",
            calc_total=0.0,
            activity_total=123.456,
        )

        self.assertEqual(result, 0.0)
