def compute_shares(amount, n):
    base, remainder = divmod(amount, n)
    return [base + 1 if i < remainder else base for i in range(n)]