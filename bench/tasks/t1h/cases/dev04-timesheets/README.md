# Timesheet invoicing

Pure Python service; put src on the import path. Review supported behavior violations without editing.

Duration end-start minutes, zero allowed; inverted interval raises ValueError. approval.billable keeps approved only. Rate cents/hour means pricing.cents floors minutes*rate/60. invoicing.invoice sums lines then fee once even empty. Labels preserve case; empty duration sum zero; export copies list.
