# Ledger reconciliation

Pure Python service; put src on the import path. Review supported behavior violations without editing.

ledger.post retains signed integer cents. refunds.entry returns negative abs(amount). settlements.complete moves pending to posted and removes pending. reconciling.balance sums posted only. settlements.refund posts already signed entry unchanged. Zero entries retained; negative balances valid; IDs case-sensitive; snapshots copy lists.
