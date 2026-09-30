import unittest

import base
from pocketful.shares import compute_shares


class TestComputeShares(unittest.TestCase):
    def test_table_rows_exact(self):
        self.assertEqual(compute_shares(1000, 3), [334, 333, 333])
        self.assertEqual(compute_shares(1, 3), [1, 0, 0])
        self.assertEqual(compute_shares(10, 3), [4, 3, 3])
        self.assertEqual(compute_shares(999, 3), [333, 333, 333])
        self.assertEqual(compute_shares(5, 5), [1, 1, 1, 1, 1])

    def test_shares_sum_to_amount_and_differ_by_at_most_one(self):
        for amount in (1, 2, 7, 100, 999, 12345, 1000000000):
            for n in range(1, 33):
                shares = compute_shares(amount, n)
                self.assertEqual(sum(shares), amount)
                self.assertLessEqual(max(shares) - min(shares), 1)
                self.assertTrue(all(isinstance(s, int) for s in shares))

    def test_order_dependence_moves_extra_unit(self):
        self.assertEqual(compute_shares(10, 3), [4, 3, 3])
        self.assertEqual(list(reversed(compute_shares(10, 3))), [3, 3, 4])
        self.assertEqual(compute_shares(1, 3), [1, 0, 0])
        self.assertEqual(list(reversed(compute_shares(1, 3))), [0, 0, 1])

    def test_single_participant(self):
        self.assertEqual(compute_shares(42, 1), [42])

    def test_zero_share_legal(self):
        shares = compute_shares(2, 5)
        self.assertEqual(shares, [1, 1, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()