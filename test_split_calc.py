import unittest
from datetime import date

from split_calc import simulate


class SimulateTest(unittest.TestCase):
    def test_official_60000_yen_three_installment_example(self):
        payments = simulate(60_000, 3, date(2026, 8, 1))

        self.assertEqual(sum(p.amount for p in payments), 61_476)
        self.assertEqual(sum(p.principal for p in payments), 60_000)
        self.assertEqual(sum(p.fee for p in payments), 1_476)
        self.assertEqual([p.amount for p in payments], [20_492] * 3)
        self.assertEqual([p.month for p in payments], ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(payments[-1].balance, 0)

    def test_payment_remainder_is_added_to_first_payment(self):
        payments = simulate(10_001, 3, date(2026, 12, 1))

        self.assertGreaterEqual(payments[0].amount, payments[1].amount)
        self.assertEqual(payments[1].amount, payments[2].amount)
        self.assertEqual(sum(p.principal for p in payments), 10_001)
        self.assertEqual(payments[0].month, "2027-01")

    def test_rejects_amount_below_service_minimum(self):
        with self.assertRaisesRegex(ValueError, "1,000円以上"):
            simulate(999, 3)

    def test_rejects_unsupported_installment_count(self):
        with self.assertRaisesRegex(ValueError, "分割回数"):
            simulate(10_000, 7)


if __name__ == "__main__":
    unittest.main()
