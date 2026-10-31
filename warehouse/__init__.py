"""
Warehouse transaction monitoring, inventory and analytics (no widgets).

    periods       reporting periods (today, this week ... custom range)
    transactions  saved inspection reports -> Receiving / Withdrawal lines
    inventory     the inventory ledger: balances, statuses, aging,
                  unmatched / inconsistent transactions
    analytics     KPIs, daily / weekly / monthly summaries, Bad Order
    store         loading the reports (Excel / MySQL) and the warehouse
                  side file (reconciliation decisions, Bad Order case status)
    exports       Excel and PDF reports
    sample_data   the isolated TEST-... demo data set

The inspection reports stay the only source of transactions: nothing here
copies or changes them.
"""
